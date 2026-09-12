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

from datetime import datetime
from typing import Annotated

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse, StreamingResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from collections import Counter

from .. import config, db, dictionary, history, library, media, progress
from ..report.takes import recurrence_threshold
from ..analysis.diff import accuracy as _accuracy
from ..drill import dictation
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


def _place(connection, segment_id: int, unit: int) -> dict:
    """这一句在它那份素材里排第几，以及前后能练的是哪一句。

    翻页按句子走，不在片段边界上断掉——那个边界是切素材时的实现细节。
    但不跨素材：两份素材各练各的。
    """
    source_id = db.get_segment(connection, segment_id)["source_id"]
    sentences = _sentences(connection, source_id)
    here = next((i for i, item in enumerate(sentences)
                 if item["segment"] == segment_id and item["unit"] == unit), None)
    if here is None:
        return {"number": unit, "total_units": len(sentences),
                "prev_unit": None, "next_unit": None, "source": "",
                "source_id": source_id}

    def hunt(step: int):
        index = here + step
        while 0 <= index < len(sentences):
            if sentences[index]["usable"]:
                return sentences[index]
            index += step
        return None

    return {"number": here + 1, "total_units": len(sentences),
            "source": sentences[here]["source"], "source_id": source_id,
            "prev_unit": hunt(-1), "next_unit": hunt(1)}


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
    start, end = media.unit_bounds(Path(source["audio_path"]), words,
                                   low=segment["start_sec"], high=segment["end_sec"])
    if not dest.exists():
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
    """一份素材的全部句子，按先后排成一条。

    「片段」只是切素材时为了保住语义块用的中间层，练的是句子。
    所以对外只有句子和它的序号，翻页也是一句接一句，不在段边界上断掉。
    """
    source = db.get_source(connection, source_id)
    if source is None or source["status"] != db.STATUS_READY:
        return []
    out = []
    for segment in db.list_segments(connection, source_id):
        full = db.get_segment(connection, segment["id"])
        for number, words in enumerate(split_into_units(full["words"]), 1):
            problem = media.unit_problem(source["audio_path"], words)
            out.append({
                "segment": segment["id"],
                "unit": number,
                "source": source["title"],
                "text": " ".join(w.text for w in words),
                "seconds": words[-1].end - words[0].start,
                "words": len(words),
                "blanks": sum(w.is_blank for w in words),
                "usable": problem is None,
                "problem": problem,
            })
    for order, item in enumerate(out, 1):
        item["number"] = order
    return out


@app.get("/")
def home():
    """首页就是当前那份素材；一份能练的都没有，就去素材库导入。"""
    chosen = library.current(_db())
    return RedirectResponse(f"/sources/{chosen}" if chosen else "/sources",
                            status_code=303)


@app.get("/sources/{source_id}", response_class=HTMLResponse)
def source_page(request: Request, source_id: int):
    connection = _db()
    source = db.get_source(connection, source_id)
    if source is None or source["status"] != db.STATUS_READY:
        return RedirectResponse("/sources", status_code=303)
    library.select(connection, source_id)     # 打开哪份，哪份就是当前
    catalogue = _sentences(connection, source_id)
    done, issues, ratings = {}, {}, {}
    # 只看这份素材上的记录：两份素材里文字相同的句子不能串在一起
    for run in db.source_runs(connection, source_id):
        text = run["unit_text"]
        metrics = db.run_metrics(connection, run["id"])
        # 中途取消留下的空记录不算练过
        if not text or not (run["blind_rating"] is not None
                            or run["gapfill_total"] is not None or metrics):
            continue
        done.setdefault(text, []).append(run)
        if run["blind_rating"] is not None:
            ratings[text] = run["blind_rating"]
        if metrics:
            issues[text] = _recurring(metrics)
    for item in catalogue:
        item["runs"] = len(done.get(item["text"], ()))
        item["issues"] = issues.get(item["text"], 0)
        item["rating"] = ratings.get(item["text"])
    # 没练过的第一句：有个直达入口就不用浏览列表，也就不会被剧透
    next_unit = next((i for i in catalogue if not i["runs"] and i["usable"]), None)
    return templates.TemplateResponse(
        request, "index.html",
        {"catalogue": catalogue, "source": source, "next_unit": next_unit,
         "practised": sum(1 for item in catalogue if item["runs"]),
         "days": progress.calendar(connection)},
    )


@app.get("/practice/{segment_id}/{unit}", response_class=HTMLResponse)
def practice(request: Request, segment_id: int, unit: int):
    connection = _db()
    segment, words = _unit_words(connection, segment_id, unit)
    step = _place(connection, segment_id, unit)
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
            "tokens": [_token(w.text) for w in words],
            "seconds": round(words[-1].end - words[0].start, 1),
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


def _token(text: str) -> dict:
    """默写框的三段：框前的标点、要写的词、框后的标点。"""
    token = dictation.split(text)
    return {"lead": token.lead, "core": token.core, "trail": token.trail,
            "box": dictation.needs_box(text)}


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
    try:
        segment, unit = int(payload["segment"]), int(payload["unit"])
        answers = {int(item["index"]): dictation.Answer(
                       guess=str(item.get("guess") or ""), unknown=bool(item.get("unknown")))
                   for item in payload.get("answers", [])}
        replays = int(payload.get("replays") or 0)
    except (KeyError, TypeError, ValueError, AttributeError):
        raise HTTPException(400, "默写提交的格式不对。")
    connection = _db()
    _, words = _unit_words(connection, segment, unit)
    marks = dictation.grade(words, answers)
    correct, wrong, unknown = dictation.tally(marks)
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
        "correct": correct, "wrong": wrong, "unknown": unknown, "total": len(marks),
        "replays": replays, "run_id": run_id, "sentence": sentence,
        "dictionary": dictionary.installed(),
        "items": [{
            "index": mark.index, "answer": mark.answer, "guess": mark.guess,
            "status": mark.status, "in_vocab": dictation.key(mark.answer) in saved,
            "entry": (None if mark.status == dictation.OK
                      else _entry_json(entries.get(dictation.key(mark.answer)))),
        } for mark in marks],
    }


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
    best = result.best
    problems = [
        {"kind": t.kind, "ref": t.ref_text, "usr": t.usr_text}
        for t in best.tokens
        if t.kind != "equal" and t.ref_index not in result.shaky
    ]
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
        "problems": problems,
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
