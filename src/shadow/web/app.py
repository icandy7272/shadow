"""网页版：命令行逻辑的一层薄壳。

所有分析都复用现有模块，这里只负责取数据、渲染页面、接收提交。
不用前端框架：四步各是一段，服务端渲染 + 表单提交就够了，
唯一需要 JS 的是浏览器录音。
"""

from __future__ import annotations

import json
import logging
import shlex
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from pathlib import Path

from datetime import date, datetime
from typing import Annotated

from fastapi import Body, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse, StreamingResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from collections import Counter

from .. import (config, dates, db, dictionary, filters, history, library, media, plan,
                progress)
from ..report.takes import recurrence_threshold
from ..analysis.diff import accuracy as _accuracy
from ..drill import dictation
from ..drill.cues import cues
from ..drill.units import split_into_units
from .. import review as review_mod
from ..ingest.downloader import DownloadError
from . import importer
from .view import feedback_view

log = logging.getLogger(__name__)
HERE = Path(__file__).parent
templates = Jinja2Templates(directory=str(HERE / "templates"))

def _asset_version() -> str:
    """静态文件的最新修改时间。

    改了 js/css 而浏览器还跑着缓存里的旧版，是最难察觉的一类问题——
    页面看着正常，行为却是上一版的。挂在 URL 上，改了就自动失效。
    """
    stamps = [item.stat().st_mtime for item in (HERE / "static").iterdir()
              if item.is_file()]
    return str(int(max(stamps))) if stamps else "0"


def _start_command() -> str:
    """服务断了时页面上给的那条命令，粘进终端就能跑。

    光说「服务断了」没用——人得知道去哪个目录、敲什么。
    """
    project = HERE.parents[2]
    if not (project / "pyproject.toml").exists():
        return "shadow serve"
    return f"cd {shlex.quote(str(project))} && uv run shadow serve"


templates.env.filters["day"] = lambda stamp: dates.day_label(stamp, _today())
templates.env.globals["assets"] = _asset_version
templates.env.globals["start_command"] = _start_command()

@asynccontextmanager
async def _lifespan(app):
    # 导入跑在后台线程里，服务一重启线程就没了；卡在半路的记录标成中断，可以重试
    connection = _db()
    try:
        db.reset_stale_sources(connection)
    finally:
        connection.close()
    yield


app = FastAPI(title="Shadow", lifespan=_lifespan)
app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

# 这些路径由页面里的 JS 或 <audio> 取用，出错时得回 JSON，前端要读 detail
_MACHINE_PATHS = ("/api/", "/audio/", "/take/", "/talk/audio/", "/static/")


@app.exception_handler(StarletteHTTPException)
async def _missing_page(request: Request, exc: StarletteHTTPException):
    """浏览器里直接打开的页面找不到时，给一个能点回去的页面，而不是满屏一行 JSON。

    过期的句子链接最常见：素材删掉或重新导入过，编号就对不上了。
    """
    wants_page = (exc.status_code == 404 and request.method == "GET"
                  and "text/html" in request.headers.get("accept", "")
                  and not request.url.path.startswith(_MACHINE_PATHS))
    if not wants_page:
        return await http_exception_handler(request, exc)
    return templates.TemplateResponse(request, "missing.html", status_code=404)


@app.get("/sources", response_class=HTMLResponse)
def library_page(request: Request):
    connection = _db()
    return templates.TemplateResponse(
        request, "library.html",
        {"cards": library.cards(connection),
         "importing": db.importing_source(connection) is not None},
    )


@app.get("/api/sources")
def sources_api():
    cards = [asdict(card) for card in library.cards(_db())]
    return JSONResponse({"sources": cards}, headers={"Cache-Control": "no-store"})


@app.post("/api/sources", status_code=201)
def import_api(url: str = Form(...)):
    try:
        return {"id": importer.start(url)}
    except DownloadError as exc:
        raise HTTPException(400, str(exc))
    except importer.Busy as exc:
        raise HTTPException(409, str(exc))


@app.post("/api/sources/{source_id}/retry", status_code=201)
def retry_api(source_id: int):
    try:
        return {"id": importer.retry(source_id)}
    except (importer.NotRetryable, importer.Busy) as exc:
        raise HTTPException(409, str(exc))


@app.delete("/api/sources/{source_id}")
def delete_api(source_id: int):
    connection = _db()
    if db.get_source(connection, source_id) is None:
        raise HTTPException(404, "这份素材已经不在了。")
    try:
        after = library.remove(connection, source_id)
    except library.LibraryError as exc:
        raise HTTPException(409, str(exc))
    return {"next": f"/sources/{after}" if after else "/sources"}


@app.get("/api/health")
async def health():
    """页面顶上那盏灯靠它判断服务还在不在。

    顺带报静态文件的版本：页面跑着旧脚本时，灯要能提醒刷新。
    """
    return JSONResponse({"ok": True, "assets": _asset_version()},
                        headers={"Cache-Control": "no-store"})


def _db():
    connection = db.connect()
    db.init_db(connection)
    return connection


def _units(connection, segment_id: int):
    segment = db.get_segment(connection, segment_id)
    if segment is None:
        raise HTTPException(404, f"片段 {segment_id} 不存在")
    return segment, split_into_units(segment["words"])


def _unit_words(connection, segment_id: int, unit: int):
    segment, units = _units(connection, segment_id)
    if not 1 <= unit <= len(units):
        raise HTTPException(404, f"片段 {segment_id} 没有第 {unit} 个单元")
    return segment, units[unit - 1]


def _all_units(connection, source_id: int) -> list[dict]:
    """一份素材切出来的每一句，按先后排成一条，练得了的和练不了的都在。"""
    source = db.get_source(connection, source_id)
    if source is None or source["status"] != db.STATUS_READY:
        return []
    out = []
    for segment in db.list_segments(connection, source_id):
        full = db.get_segment(connection, segment["id"])
        for number, words in enumerate(split_into_units(full["words"]), 1):
            out.append({
                "segment": segment["id"],
                "unit": number,
                "source": source["title"],
                "text": " ".join(w.text for w in words),
                "seconds": words[-1].end - words[0].start,
                "words": len(words),
                "usable": media.unit_problem(source["audio_path"], words) is None,
            })
    return out


def _numbered(units: list[dict]) -> list[dict]:
    """能练的句子连着编号。练不了的（音频里没有这句、时间戳挤坏了）不列、不计数、不占编号。"""
    usable = [item for item in units if item["usable"]]
    return [{**item, "number": order} for order, item in enumerate(usable, 1)]


def _practice_states(connection, source_id: int) -> dict[str, filters.State]:
    """这份素材上每句话练到了什么程度：练过几轮、上次的问题、自评、最后哪天练的、几号该复习。

    只看这份素材上的记录：两份素材里文字相同的句子不能串在一起。
    到期日是一路算出来的，不存库：评分规则改了，老记录跟着重算，不会留下一批按旧规矩排的队。
    """
    runs, issues, ratings, last, first, levels = {}, {}, {}, {}, {}, {}
    for run in db.source_runs(connection, source_id):
        text = run["unit_text"]
        metrics = db.run_metrics(connection, run["id"])
        # 中途取消留下的空记录不算练过
        if not text or not (run["blind_rating"] is not None
                            or run["gapfill_total"] is not None or metrics):
            continue
        runs[text] = runs.get(text, 0) + 1
        if run["blind_rating"] is not None:
            ratings[text] = run["blind_rating"]
        if metrics:
            issues[text] = _recurring(metrics)
        levels[text] = plan.next_level(
            levels.get(text, -1),
            plan.result_of(rating=run["blind_rating"], issues=issues.get(text, 0)))
        when = _local_day(run["finished_at"] or run["started_at"])
        if when is not None and (text not in last or when > last[text]):
            last[text] = when
        if when is not None and (text not in first or when < first[text]):
            first[text] = when
    return {text: filters.State(
                runs=count, issues=issues.get(text, 0), rating=ratings.get(text),
                last_day=last.get(text), first_day=first.get(text),
                due=plan.due_day(last[text], levels[text]) if text in last else None)
            for text, count in runs.items()}


def _place(connection, segment_id: int, unit: int, queue: str | None = None) -> dict:
    """这一句在它那份素材里排第几，以及前后能练的是哪一句。

    翻页按句子走，不在片段边界上断掉——那个边界是切素材时的实现细节。
    但不跨素材：两份素材各练各的。练不了的句子没有编号；直接打开这种句子
    （旧链接、生词本里的出处）时，前后照样指到最近的能练的那句。

    从列表的筛选点进来时（queue），前后只在符合这个筛选的句子里找：
    挑着练过的话，原文的下一句可能根本不用复习，甚至还没练过。
    """
    source_id = db.get_segment(connection, segment_id)["source_id"]
    units = _all_units(connection, source_id)
    sentences = _numbered(units)
    position = next((i for i, item in enumerate(units)
                     if item["segment"] == segment_id and item["unit"] == unit), None)
    if position is None:
        return {"number": unit, "total_units": len(sentences),
                "prev_unit": None, "next_unit": None, "source": "",
                "source_id": source_id, "queue": None}
    by_key = {(item["segment"], item["unit"]): item for item in sentences}

    def numbered(index):
        return None if index is None else by_key[(units[index]["segment"], units[index]["unit"])]

    usable = [item["usable"] for item in units]
    if queue is None:
        picked = filters.Selection(
            order=tuple(index for index, ok in enumerate(usable) if ok))
        after = filters.after(picked, position, wrap=False)
        view = None
    else:
        states = _practice_states(connection, source_id)
        here = [states.get(item["text"], filters.NEVER) for item in units]
        picked = filters.select(queue, here, _today(), usable=usable)
        after = filters.after(picked, position)
        view = filters.view(queue, remaining=filters.remaining(picked, position))
    before = filters.before(picked, position)
    here = by_key.get((segment_id, unit))
    return {"number": here["number"] if here else None,
            "total_units": len(sentences),
            "source": units[position]["source"], "source_id": source_id,
            "prev_unit": numbered(before), "next_unit": numbered(after), "queue": view}


def _unit_reference(connection, segment_id: int, unit: int):
    """按需裁出单元音频并缓存，同时把词的时间戳平移到以裁剪起点为 0。

    库里的时间戳是整段素材里的绝对秒数，裁出来的单元音频只有一两秒。
    不平移的话，按绝对秒数去这段音频里取音高会一帧都取不到，
    图 2 的原声轮廓会整条变平，跟着连升降调的判断也一起失效。
    命令行的 _segment_reference 一直是这么做的，网页这边漏了。
    """
    segment, words = _unit_words(connection, segment_id, unit)
    source = db.get_source(connection, segment["source_id"])
    if source is None or not source["audio_path"]:
        raise HTTPException(404, "素材音频缺失")
    dest = config.segment_audio_dir() / f"{segment_id}-u{unit}.wav"
    # 边界是前后相邻片段，不是本段自己的起止——那样每段最后一句的词尾会被切掉
    low, high = db.segment_edges(connection, segment_id)
    start, end = media.unit_bounds(Path(source["audio_path"]), words, low=low, high=high)
    # 缓存按时长认：切法改过的旧文件（比如切掉了词尾的）自动重切
    if not media.cut_matches(dest, end - start):
        media.cut_segment(Path(source["audio_path"]), dest, start=start, end=end)
    # 裁剪点贴到停顿上之后可能晚于转写给的首词起点，钳到 0
    rebased = tuple(
        replace(word, start=max(0.0, word.start - start), end=word.end - start)
        for word in words
    )
    return dest, rebased


def _unit_audio(connection, segment_id: int, unit: int) -> Path:
    return _unit_reference(connection, segment_id, unit)[0]


def _recurring(metrics: list[dict]) -> int:
    """上一轮反复出现的问题有几条。偶尔犯一次的不算。"""
    counted = Counter(issue["title"] for take in metrics
                      for issue in take.get("issues", ()))
    threshold = recurrence_threshold(len(metrics))
    return sum(1 for hits in counted.values() if hits >= threshold)


def _sentences(connection, source_id: int) -> list[dict]:
    """一份素材里能练的句子，按先后排成一条、连着编号。

    「片段」只是切素材时为了保住语义块用的中间层，练的是句子。
    所以对外只有句子和它的序号，翻页也是一句接一句，不在段边界上断掉。
    """
    return _numbered(_all_units(connection, source_id))


@app.get("/")
def home():
    """首页就是当前那份素材；一份能练的都没有，就去素材库导入。"""
    chosen = library.current(_db())
    return RedirectResponse(f"/sources/{chosen}" if chosen else "/sources",
                            status_code=303)


def _today() -> date:
    """本地日期。日课按这台电脑上的日子算；测试里会换掉它。"""
    return datetime.now().astimezone().date()


def _local_day(stamp: str | None) -> date | None:
    try:
        return datetime.fromisoformat(stamp).astimezone().date()
    except (TypeError, ValueError):
        return None


def _plan_finished(connection, today: date, review: filters.Selection,
                   new_today: int) -> dict[str, bool]:
    """练习记录里看得出来的那几步，今天做完了没有。

    卡片本来就写着今天有没有到期的，勾还要人自己点一次，等于同一件事确认两遍。
    说的那一步同理：今天在页面上录过，就是做过了。这里只给默认值——
    自己点掉的那一步以点掉为准（见 _step_done）。
    """
    reviewed = not review.order          # 到期的都练完了（或今天本来就没有）
    talked = db.talk_kinds_on(connection, today.isoformat())
    return {"review": reviewed, "redo": reviewed,
            "new": new_today >= plan.NEW_SENTENCES,
            plan.RETELL: plan.RETELL in talked,
            plan.FREE_TALK: plan.FREE_TALK in talked}


def _step_done(key: str, marks: dict[str, bool], finished: dict[str, bool]) -> bool:
    """自己点过就听自己的，没点过才用练习记录里看出来的那个结论。"""
    return marks[key] if key in marks else finished.get(key, False)


def _plan_progress(connection, today: date) -> tuple[filters.Selection, int]:
    """当前素材上：今天还有几句该复习、今天新练了几句。"""
    source_id = library.current(connection)
    if source_id is None:
        return filters.Selection(), 0
    catalogue = _sentences(connection, source_id)
    states = _practice_states(connection, source_id)
    here = [states.get(item["text"], filters.NEVER) for item in catalogue]
    return (filters.select(filters.REVIEW, here, today),
            sum(1 for state in here if state.first_day == today))


def _plan_view(connection, today: date, review: filters.Selection,
               new_today: int, week_count: int) -> dict:
    """首页日课卡片要的东西：今天是星期几、哪几步、做完了哪些、该复习几句、顺延几句。

    能从练习记录里看出来的几步自己划掉；剩下的测不出来，还是手动勾。
    """
    weekday = today.weekday()
    marks = db.plan_checks(connection, today.isoformat())
    finished = _plan_finished(connection, today, review, new_today)
    steps = [{"key": step.key, "title": step.title, "detail": step.detail,
              "link": step.link, "done": _step_done(step.key, marks, finished)}
             for step in plan.steps_for(weekday)]
    return {"heading": plan.heading(weekday), "steps": steps,
            "all_done": all(step["done"] for step in steps),
            "review_count": len(review.order), "deferred": len(review.deferred),
            "week_count": week_count}


def _practised_since(connection, since: date) -> list[dict]:
    """当前素材上从某天起练过的句子，按原文顺序。连起来跟和自由说都要它。"""
    source_id = library.current(connection)
    if source_id is None:
        return []
    states = _practice_states(connection, source_id)
    return [item for item in _sentences(connection, source_id)
            if (states.get(item["text"], filters.NEVER).last_day or date.min) >= since]


CHAIN_GAP_SEC = 0.6     # 两句之间留一口气，和 chain.js 里的一致；估时长要算上


def _chain_view(scope: str, today: date) -> dict:
    """连着跟的两种口径：今天练过的（串起来）、本周练过的（整段跟读）。

    同一件事、同一个页面，差别只在筛哪一段时间、跟几遍。
    """
    if scope == "week":
        return {"scope": "week", "step": "whole", "title": "整段跟读",
                "since": plan.week_start(today), "rounds": plan.WHOLE_ROUNDS,
                "lede": "本周练过的句子从头跟到尾，中间不停下来改。单句练的是「像」，"
                        "整段练的是「不断」。",
                "other": {"href": "/chain", "label": "只连今天练过的 · 串起来 →"}}
    return {"scope": "today", "step": "chain", "title": "串起来",
            "since": today, "rounds": plan.CHAIN_ROUNDS,
            "lede": "今天练过的几句连着跟，中间不停下来改——这一步练的是把单句接成一段话的"
                    "节奏，错一两个词没关系。",
            "other": {"href": "/chain?scope=week", "label": "本周练过的都连上 · 整段跟读 →"}}


@app.get("/chain", response_class=HTMLResponse)
def chain_page(request: Request, scope: str = Query("today")):
    """练过的句子连着放——日课里的「串起来」和周六的「整段跟读」。

    单句练得再准，接成一段话时节奏还是断的：这一步只放音，不比对，中间不停。
    """
    connection = _db()
    today = _today()
    view = _chain_view("week" if scope == "week" else "today", today)
    sentences = _practised_since(connection, view["since"])
    seconds = sum(item["seconds"] + CHAIN_GAP_SEC for item in sentences) * view["rounds"]
    return templates.TemplateResponse(
        request, "chain.html",
        {**view, "sentences": sentences, "minutes": max(1, round(seconds / 60)),
         # 跟完了自己在日课里划掉；不是今天的步骤就别勾（周六没有「串起来」这一步）
         "tick": view["step"] if plan.is_step(today.weekday(), view["step"]) else ""})


# --- 自己开口说：每天的复述、周六的自由说 -----------------------------------

TALK_PICKS = 12         # 页面上最多列这么多个表达，挑 3–5 个就够说 2 分钟
TALK_HISTORY = 8        # 录过的列这么几段。要的是和上周比，不是翻一年的档案
MAX_PICK_CHARS = 200


def _week_picks(connection, today: date) -> list[dict]:
    """「本周学到的表达」：这周记进生词本的词，带它出自哪句。

    默写里写不出的词就是这周真正欠的表达，挑出来用一次，比另找话题有用。
    这周一个词都没记下（没做默写）时退回本周练过的句子，总得有东西可挑。
    """
    start = plan.week_start(today)
    seen, words = set(), []
    for item in db.list_vocab(connection):          # 最近记下的在前
        for source in item["sources"]:
            day = _local_day(source["added_at"])
            if day is None or day < start or item["word"] in seen:
                continue
            seen.add(item["word"])
            words.append({"text": item["word"], "from": source["sentence"]})
    if words:
        return words[:TALK_PICKS]
    recent = _practised_since(connection, start)[-TALK_PICKS:]
    return [{"text": item["text"], "from": ""} for item in reversed(recent)]


def _retell_passage(connection, today: date) -> dict | None:
    """复述讲哪几句：今天新练的；今天只做了复习，就讲上次新练的那几句。

    新句子是顺着原文往下练的，连得成一段；复习的散在全文各处，拼不成一件事，
    讲起来就只剩背句子。页面上只给关键词，不给原句。
    """
    source_id = library.current(connection)
    if source_id is None:
        return None
    states = _practice_states(connection, source_id)
    by_day: dict[date, list[dict]] = {}
    for item in _sentences(connection, source_id):
        first = states.get(item["text"], filters.NEVER).first_day
        if first is not None and first <= today:
            by_day.setdefault(first, []).append(item)
    if not by_day:
        return None
    day = max(by_day)
    items = sorted(by_day[day], key=lambda item: item["number"])
    return {"day": day, "today": day == today, "count": len(items),
            "first": items[0]["number"], "last": items[-1]["number"],
            "cues": cues([item["text"] for item in items])}


def _mmss(seconds: float) -> str:
    whole = int(round(seconds))
    return f"{whole // 60}:{whole % 60:02d}"


def _when(day: date, today: date) -> str:
    """这段是什么时候录的。要比的是「这周」和「上周」，所以按周说，不按天数说。"""
    if day == today:
        return "今天"
    weeks = max(0, (plan.week_start(today) - plan.week_start(day)).days // 7)
    return ("本周", "上周")[weeks] if weeks < 2 else f"{weeks} 周前"


def _talk_item(row: dict, today: date) -> dict:
    day = date.fromisoformat(row["day"])
    return {"id": row["id"], "when": _when(day, today), "date": row["day"],
            "length": _mmss(row["seconds"]), "picks": row["picks"],
            "url": f"/talk/audio/{Path(row['audio_path']).name}"}


@app.get("/talk", response_class=HTMLResponse)
def talk_page(request: Request, kind: str | None = Query(None)):
    """合上材料自己说一段，录下来。日课里的「复述」和周六的「自由说」。

    跟读练不出「自己组织语言说出来」，这一步才练。原来只写着「手机录音」——
    录在哪、上周那段在哪，都得自己想办法，于是最容易被跳过。
    """
    today = _today()
    spec = plan.TALKS.get(kind) or plan.talk_for(today.weekday())
    connection = _db()
    takes = [_talk_item(row, today)
             for row in db.list_talks(connection, kind=spec.kind, limit=TALK_HISTORY)]
    return templates.TemplateResponse(
        request, "talk.html",
        {"spec": spec, "takes": takes,
         "picks": _week_picks(connection, today) if spec.kind == plan.FREE_TALK else [],
         "passage": _retell_passage(connection, today) if spec.kind == plan.RETELL else None,
         "other": plan.TALKS[plan.RETELL if spec.kind == plan.FREE_TALK else plan.FREE_TALK]})


@app.post("/api/talk", status_code=201)
async def save_talk(kind: Annotated[str, Form()],
                    file: Annotated[UploadFile, File()],
                    picks: Annotated[list[str] | None, Form()] = None):
    """收下一段录音。不转写、不比对——这一步的反馈是自己回听，和上周那段比。"""
    if kind not in plan.TALKS:
        raise HTTPException(400, "没有这一种。")
    today = _today()
    stamp = datetime.now().strftime("%H%M%S")
    dest = config.talk_audio_dir() / f"{kind}-{today.isoformat()}-{stamp}.wav"
    try:
        media.convert_upload(await file.read(), dest)
        media.validate_attempt(dest)      # 太短、接近静音就地拦下，别攒一堆废录音
        seconds = media.probe_duration(dest)
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, str(exc))
    chosen = [pick.strip()[:MAX_PICK_CHARS]
              for pick in (picks or []) if pick.strip()][:TALK_PICKS]
    talk_id = db.add_talk(_db(), day=today.isoformat(), kind=kind, audio_path=str(dest),
                          seconds=seconds, picks=chosen)
    return {"talk": _talk_item({"id": talk_id, "day": today.isoformat(), "seconds": seconds,
                                "picks": chosen, "audio_path": str(dest)}, today)}


@app.delete("/api/talk/{talk_id}")
def remove_talk_api(talk_id: int):
    """删掉一段。16k 的 wav 一分钟两兆，攒一年是要占地方的。"""
    path = db.remove_talk(_db(), talk_id)
    if path is None:
        raise HTTPException(404, "这一段已经不在了。")
    Path(path).unlink(missing_ok=True)
    return {"removed": True}


@app.get("/talk/audio/{name}")
def talk_audio(name: str):
    """回放自己说的那一段。只认录音目录里的文件名，不接受路径。"""
    folder = config.talk_audio_dir().resolve()
    path = (folder / name).resolve()
    if path.parent != folder or not path.exists():
        raise HTTPException(404, "录音不存在")
    return FileResponse(path, media_type="audio/wav")


@app.get("/plan", response_class=HTMLResponse)
def plan_page(request: Request):
    return templates.TemplateResponse(request, "plan.html", {})


@app.post("/api/plan")
def save_plan_check(payload: dict = Body(...)):
    """勾上或取消今天日课里的一步。周六的「自由说」不能在周一勾。"""
    today = _today()
    step, done = payload.get("step"), payload.get("done")
    if not isinstance(done, bool):
        raise HTTPException(400, "要说明是勾上还是取消。")
    if not isinstance(step, str) or not plan.is_step(today.weekday(), step):
        raise HTTPException(400, "今天的日课里没有这一步。")
    connection = _db()
    db.set_plan_check(connection, today.isoformat(), step, done)
    marks = db.plan_checks(connection, today.isoformat())
    finished = _plan_finished(connection, today, *_plan_progress(connection, today))
    all_done = all(_step_done(item.key, marks, finished)
                   for item in plan.steps_for(today.weekday()))
    return {"step": step, "done": done, "all_done": all_done}


@app.get("/sources/{source_id}", response_class=HTMLResponse)
def source_page(request: Request, source_id: int):
    connection = _db()
    source = db.get_source(connection, source_id)
    if source is None or source["status"] != db.STATUS_READY:
        return RedirectResponse("/sources", status_code=303)
    library.select(connection, source_id)     # 打开哪份，哪份就是当前
    catalogue = _sentences(connection, source_id)
    states = _practice_states(connection, source_id)
    today = _today()
    here = [states.get(item["text"], filters.NEVER) for item in catalogue]
    # 该复习的那几句排过急迫程度，名次带给前端：点「该复习」时列表按它重排
    review = filters.select(filters.REVIEW, here, today)
    new_today = sum(1 for state in here if state.first_day == today)
    # 周六的「整段跟读」要连的就是这些：本周练过的
    since = plan.week_start(today)
    week_count = sum(1 for state in here if state.last_day and state.last_day >= since)
    ranks = {index: rank for rank, index in enumerate(review.order, 1)}
    for index, item in enumerate(catalogue):
        state = here[index]
        item["runs"] = state.runs
        item["issues"] = state.issues
        item["rating"] = state.rating
        item["review"] = index in ranks
        item["review_rank"] = ranks.get(index, 0)
    # 没练过的第一句：有个直达入口就不用浏览列表，也就不会被剧透
    next_unit = next((i for i in catalogue if not i["runs"] and i["usable"]), None)
    return templates.TemplateResponse(
        request, "index.html",
        {"catalogue": catalogue, "source": source, "next_unit": next_unit,
         "practised": sum(1 for item in catalogue if item["runs"]),
         "days": progress.calendar(connection),
         "plan": _plan_view(connection, today, review, new_today, week_count)},
    )


@app.get("/practice/{segment_id}/{unit}", response_class=HTMLResponse)
def practice(request: Request, segment_id: int, unit: int,
             from_: Annotated[str | None, Query(alias="from")] = None):
    """from 是列表上点进来时用的筛选：下一句在同一个筛选里找。"""
    connection = _db()
    segment, words = _unit_words(connection, segment_id, unit)
    step = _place(connection, segment_id, unit, filters.parse(from_))
    source = db.get_source(connection, segment["source_id"])
    problem = media.unit_problem(source["audio_path"] if source else None, words)
    if problem:
        # 不能只回一句 JSON：练下一句会把人送进来，再没有出口就卡死了
        return templates.TemplateResponse(
            request, "unusable.html",
            {"segment": segment_id, "unit": unit, "problem": problem, **step},
            status_code=409,
        )
    return templates.TemplateResponse(
        request, "practice.html",
        {
            "segment": segment_id,
            "unit": unit,
            **step,
            "words": words,
            # 默写这一步只给要写几个词，不给原文——着色用的原文等对完答案再带回来
            "word_total": sum(1 for w in words if dictation.needs_box(w.text)),
            "seconds": round(words[-1].end - words[0].start, 1),
            # 原声里真出声的时长（不含词间停顿）。录音「说完了自己停」拿它当下限：
            # 按整段时长算的话，跟得比原声快的人永远够不着，只能自己点
            "spoken": round(sum(word.duration for word in words), 1),
            "min_take_sec": config.MIN_ATTEMPT_SEC,
            # 只传给第三步。里面带着句子原文的片段，提前露出来盲听就废了。
            "history": history.last_practice(connection, segment_id, unit),
        },
    )


@app.get("/audio/{segment_id}/{unit}")
def audio(segment_id: int, unit: int):
    connection = _db()
    return FileResponse(_unit_audio(connection, segment_id, unit),
                        media_type="audio/wav")


def _run_for(connection, segment: int, unit: int, run_id: int | None, words):
    """同一次练习的三步记进同一行，与命令行 practice 一致。"""
    if run_id is not None:
        return run_id
    return db.start_run(connection, segment_id=segment, unit_index=unit,
                        unit_text=" ".join(w.text for w in words))


@app.post("/api/rating")
def save_rating(segment: int = Form(...), unit: int = Form(...),
                rating: int = Form(...), run_id: int | None = Form(None)):
    if not 1 <= rating <= 5:
        raise HTTPException(400, "评分必须是 1-5")
    connection = _db()
    _, words = _unit_words(connection, segment, unit)
    run_id = _run_for(connection, segment, unit, run_id, words)
    db.set_blind_rating(connection, run_id, rating)
    # 每步结束都收尾一次：只做了第一步就离开的话，记录也该算数
    db.finish_run(connection, run_id)
    return {"ok": True, "run_id": run_id}


MAX_DICTATION_CHARS = 2000


def _line(words, marks) -> list[dict]:
    """整句逐词：标点照原文放，要写的词带上判定。前端着色全靠它，页面上不先放原文。"""
    status_of = {mark.index: mark.status for mark in marks}
    line = []
    for index, word in enumerate(words):
        token = dictation.split(word.text)
        line.append({"lead": token.lead, "core": token.core, "trail": token.trail,
                     "index": index, "status": status_of.get(index)})
    return line


def _entry_json(entry) -> dict | None:
    if entry is None:
        return None
    lemma = entry.lemma
    return {"word": entry.word, "phonetic": entry.phonetic,
            "meanings": list(entry.meanings),
            "lemma": None if lemma is None
            else {"word": lemma.word, "meanings": list(lemma.meanings)}}


@app.post("/api/dictation")
def save_dictation(payload: dict = Body(...)):
    """一整句写的内容，和原文按词对齐后判分：漏一个词只算这一个漏写。"""
    try:
        segment, unit = int(payload["segment"]), int(payload["unit"])
        replays = int(payload.get("replays") or 0)
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "默写提交的格式不对。")
    text = payload.get("text")
    if not isinstance(text, str) or len(text) > MAX_DICTATION_CHARS:
        raise HTTPException(400, "默写提交的格式不对。")
    connection = _db()
    _, words = _unit_words(connection, segment, unit)
    graded = dictation.grade(words, text)
    marks = graded.marks
    correct, wrong, unknown, missing = dictation.tally(marks)
    sentence = " ".join(w.text for w in words)
    run_id = _run_for(connection, segment, unit, payload.get("run_id"), words)
    db.set_dictation(connection, run_id, correct=correct, total=len(marks),
                     unknown=unknown, replays=replays)
    # 不会的自动进生词本；写错的可能只是手滑，由人决定
    for mark in marks:
        if mark.status == dictation.UNKNOWN:
            db.add_vocab(connection, dictation.key(mark.answer), sentence=sentence,
                         segment_id=segment, unit_index=unit)
    db.finish_run(connection, run_id)
    saved = db.vocab_words(connection)
    entries = dictionary.lookup_many(
        dictation.key(mark.answer) for mark in marks if mark.status != dictation.OK)
    return {
        "correct": correct, "wrong": wrong, "missing": missing, "unknown": unknown,
        "total": len(marks), "extras": list(graded.extras),
        "replays": replays, "run_id": run_id, "sentence": sentence,
        "dictionary": dictionary.installed(),
        "items": [{
            "index": mark.index, "answer": mark.answer, "guess": mark.guess,
            "status": mark.status, "in_vocab": dictation.key(mark.answer) in saved,
            "entry": (None if mark.status == dictation.OK
                      else _entry_json(entries.get(dictation.key(mark.answer)))),
        } for mark in marks],
        "line": _line(words, marks),
    }


def _vocab_link(connection, source: dict) -> str | None:
    """原句还能不能点回去练：素材删了、切分变了，就只留文字。"""
    segment_id, unit = source["segment_id"], source["unit_index"]
    if segment_id is None or unit is None:
        return None
    segment = db.get_segment(connection, segment_id)
    if segment is None or not 1 <= unit <= len(split_into_units(segment["words"])):
        return None
    return f"/practice/{segment_id}/{unit}"


VOCAB_SORTS = ("recent", "times")


@app.get("/vocab", response_class=HTMLResponse)
def vocab_page(request: Request, sort: str = Query("recent")):
    connection = _db()
    sort = sort if sort in VOCAB_SORTS else "recent"
    items = db.list_vocab(connection, by=sort)
    entries = dictionary.lookup_many(item["word"] for item in items)
    shown = [{
        **item,
        "entry": entries.get(item["word"]),
        "first_day": item["first_added"],
        "sources": [{**source, "link": _vocab_link(connection, source)}
                    for source in item["sources"]],
    } for item in items]
    return templates.TemplateResponse(
        request, "vocab.html",
        {"items": shown, "dictionary": dictionary.installed(), "sort": sort})


def _optional_int(value) -> int | None:
    return None if value is None else int(value)


@app.post("/api/vocab")
def add_vocab_api(payload: dict = Body(...)):
    """写错的词由人决定要不要记；不会的词在对答案时已经自动记过了。"""
    word = dictation.key(str(payload.get("word") or ""))
    if not dictation.needs_box(word):
        raise HTTPException(400, "没有要记的词。")
    try:
        segment_id = _optional_int(payload.get("segment"))
        unit_index = _optional_int(payload.get("unit"))
    except (TypeError, ValueError):
        raise HTTPException(400, "原句的编号不对。")
    times = db.add_vocab(_db(), word, sentence=str(payload.get("sentence") or "").strip(),
                         segment_id=segment_id, unit_index=unit_index)
    return {"word": word, "times": times}


@app.delete("/api/vocab/{word}")
def remove_vocab_api(word: str):
    if not db.remove_vocab(_db(), dictation.key(word)):
        raise HTTPException(404, "生词本里没有这个词。")
    return {"removed": True}


MAX_ADVICE = 3


@app.get("/take/{name}")
def take_audio(name: str):
    """回放某一遍录音。只认录音目录里的文件名，不接受路径。"""
    folder = config.attempt_audio_dir().resolve()
    path = (folder / name).resolve()
    if path.parent != folder or not path.exists():
        raise HTTPException(404, "录音不存在")
    return FileResponse(path, media_type="audio/wav")


@app.post("/api/takes")
async def submit_takes(
    segment: Annotated[int, Form()],
    unit: Annotated[int, Form()],
    files: Annotated[list[UploadFile], File()],
    run_id: Annotated[int | None, Form()] = None,
    saw_text: Annotated[int, Form()] = 0,
):
    """转写加比对要跑十几秒，结果分行流式返回，前端拿它画进度条。"""
    connection = _db()
    try:
        ref_path, ref_words = _unit_reference(connection, segment, unit)
    finally:
        connection.close()

    stamp = datetime.now().strftime("%m%d-%H%M%S")
    paths = []
    rejected = []
    for index, upload in enumerate(files, 1):
        dest = config.attempt_audio_dir() / f"{segment}-u{unit}-{stamp}-{index}.wav"
        try:
            media.convert_upload(await upload.read(), dest)
            media.validate_attempt(dest)
        except Exception as exc:
            # 坏一遍不该让整批作废——那等于逼人从头再录三遍。剔掉继续。
            rejected.append({"index": index, "reason": str(exc)})
            dest.unlink(missing_ok=True)
            continue
        paths.append(dest)

    if not paths:
        reasons = "；".join(f"第 {r['index']} 遍{r['reason']}" for r in rejected)
        raise HTTPException(400, f"没有一遍能用：{reasons}")

    return StreamingResponse(
        _review_stream(segment=segment, unit=unit, ref_path=ref_path,
                       ref_words=ref_words, paths=paths, run_id=run_id,
                       stamp=stamp, rejected=rejected, saw_text=bool(saw_text)),
        media_type="application/x-ndjson",
    )


def _event(payload: dict) -> str:
    """NDJSON 的一行。"""
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _step_label(step, count: int) -> str:
    return ("转写原声" if step.stage == "reference"
            else f"转写第 {step.index}/{count} 遍")


def _review_stream(*, segment, unit, ref_path, ref_words, paths, run_id, stamp,
                   rejected=(), saw_text=False):
    """每一步开工前发一行进度，最后一行是 result 或 error。

    生成器跑在 Starlette 的线程池里，sqlite 连接不能跨线程用，写库时现开一个。
    """
    total = len(paths) + 1          # 原声一步，每遍一步
    try:
        steps = review_mod.run(ref_path, ref_words, paths)
        while True:
            try:
                step = next(steps)
            except StopIteration as stop:
                result = stop.value
                break
            yield _event({"done": step.done, "total": total,
                          "label": _step_label(step, len(paths))})

        if result is None:
            yield _event({"error": "所有录音的转写时间戳都对不上，没法比较。"
                                   "换个安静点的环境重录。"})
            return

        connection = _db()
        try:
            run_id = _run_for(connection, segment, unit, run_id, ref_words)
            _store_takes(connection, run_id, result)
            db.mark_saw_text(connection, run_id, saw_text)
            db.finish_run(connection, run_id)
        finally:
            connection.close()

        yield _event({"result": _review_payload(
            result, run_id, rejected=rejected,
            audio={"ref": f"/audio/{segment}/{unit}"},
            takes={str(take.path): f"/take/{take.path.name}"
                   for take in result.takes})})
    except Exception as exc:
        log.exception("片段 %s 单元 %s 的比对失败", segment, unit)
        yield _event({"error": f"比对失败：{exc}"})


def _review_payload(result, run_id: int, *, audio: dict, takes: dict,
                    rejected=()) -> dict:
    summary = result.summary
    # 机器没听对的词放在每一遍自己的视图里（view.takes[].problems），切到哪一遍就显示哪一遍的
    return {
        "run_id": run_id,
        "view": feedback_view(result, MAX_ADVICE, audio=audio, takes=takes),
        "count": summary.count,
        "skipped": [{"index": i, "drift": round(d, 1)}
                    for i, _n, d in result.skipped],
        "rejected": list(rejected),
        "accuracy": round(summary.accuracy.median * 100),
        "speech": round(summary.speech_ratio.median, 2),
        "pause": None if summary.pause_ratio is None
                 else round(summary.pause_ratio.median, 2),
        "issues": [
            {"title": i.advice.title, "detail": i.advice.detail,
             "action": i.advice.action, "hits": i.hits, "total": i.total}
            for i in summary.issues[:MAX_ADVICE]
        ],
        "good": list(review_mod.good_words(result))[:12],
    }


def _store_takes(connection, run_id: int, result) -> None:
    for take in result.takes:
        connection_metrics = {
            "accuracy": _accuracy(take.tokens),
            "speech_ratio": take.rhythm.speech_ratio,
            "pause_ratio": take.rhythm.pause_ratio,
            "issues": [{"kind": a.kind, "ref_index": a.ref_index,
                        "score": a.score, "title": a.title} for a in take.advice],
        }
        db.add_attempt(connection, run_id=run_id, audio_path=str(take.path),
                       asr_text=" ".join(w.text for w in take.words),
                       metrics=connection_metrics)
