"""网页版：命令行逻辑的一层薄壳。

所有分析都复用现有模块，这里只负责取数据、渲染页面、接收提交。
不用前端框架：四步各是一段，服务端渲染 + 表单提交就够了，
唯一需要 JS 的是浏览器录音。
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path

from datetime import datetime
from typing import Annotated

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, RedirectResponse,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import config, db, media
from ..analysis.diff import accuracy as _accuracy
from ..drill.gapfill import blanks_of
from ..drill.units import is_usable, split_into_units
from .. import review as review_mod
from .view import feedback_view

log = logging.getLogger(__name__)
HERE = Path(__file__).parent
templates = Jinja2Templates(directory=str(HERE / "templates"))

app = FastAPI(title="Shadow")
app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")


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
    start = max(segment["start_sec"], words[0].start - config.UNIT_PAD_SEC)
    end = min(segment["end_sec"], words[-1].end + config.UNIT_PAD_SEC)
    if not dest.exists():
        media.cut_segment(Path(source["audio_path"]), dest, start=start, end=end)
    rebased = tuple(
        replace(word, start=word.start - start, end=word.end - start)
        for word in words
    )
    return dest, rebased


def _unit_audio(connection, segment_id: int, unit: int) -> Path:
    return _unit_reference(connection, segment_id, unit)[0]


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    connection = _db()
    sources = db.list_sources(connection)
    catalogue = []
    for source in sources:
        if source["status"] != db.STATUS_READY:
            continue
        for segment in db.list_segments(connection, source["id"]):
            full = db.get_segment(connection, segment["id"])
            for number, words in enumerate(split_into_units(full["words"]), 1):
                catalogue.append({
                    "segment": segment["id"],
                    "unit": number,
                    "text": " ".join(w.text for w in words),
                    "seconds": words[-1].end - words[0].start,
                    "words": len(words),
                    "blanks": sum(w.is_blank for w in words),
                    "usable": is_usable(words),
                })
    done = {}
    for run in db.list_runs(connection):
        # 中途取消留下的空记录不算练过
        if run["unit_text"] and (run["blind_rating"] is not None
                                 or run["gapfill_total"] is not None
                                 or db.run_metrics(connection, run["id"])):
            done.setdefault(run["unit_text"], []).append(run)
    for item in catalogue:
        item["runs"] = len(done.get(item["text"], ()))
    # 没练过的第一句：有个直达入口就不用浏览列表，也就不会被剧透
    next_unit = next((i for i in catalogue if not i["runs"] and i["usable"]), None)
    return templates.TemplateResponse(
        request, "index.html",
        {"catalogue": catalogue, "sources": sources, "next_unit": next_unit},
    )


@app.get("/practice/{segment_id}/{unit}", response_class=HTMLResponse)
def practice(request: Request, segment_id: int, unit: int):
    connection = _db()
    segment, words = _unit_words(connection, segment_id, unit)
    if not is_usable(words):
        raise HTTPException(
            409, "这个单元的词级时间戳异常（十几个词挤在半秒里），没法练。换一个吧。"
        )
    _, units = _units(connection, segment_id)
    return templates.TemplateResponse(
        request, "practice.html",
        {
            "segment": segment_id,
            "unit": unit,
            "total_units": len(units),
            "words": words,
            "blanks": blanks_of(words),
            "seconds": round(words[-1].end - words[0].start, 1),
            "min_take_sec": config.MIN_ATTEMPT_SEC,
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


@app.post("/api/gapfill")
def save_gapfill(payload: dict = Body(...)):
    connection = _db()
    segment = int(payload["segment"])
    unit = int(payload["unit"])
    _, words = _unit_words(connection, segment, unit)
    blanks = {b.word_index: b for b in blanks_of(words)}

    items, correct, heard = [], 0, 0
    for answer in payload.get("answers", []):
        blank = blanks.get(int(answer["index"]))
        if blank is None:
            continue
        guess = (answer.get("guess") or "").strip()
        guessed = bool(answer.get("guessed"))
        ok = blank.matches(guess)
        if ok:
            correct += 1
            if not guessed:
                heard += 1
        items.append({
            "answer": blank.answer, "guess": guess, "correct": ok,
            "heard": ok and not guessed, "ms": round(blank.duration * 1000),
        })

    replays = int(payload.get("replays") or 0)
    run_id = _run_for(connection, segment, unit, payload.get("run_id"), words)
    db.set_gapfill(connection, run_id, correct, len(blanks), heard, replays)
    db.finish_run(connection, run_id)
    return {"correct": correct, "total": len(blanks), "heard": heard,
            "replays": replays, "items": items, "run_id": run_id}


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
                       stamp=stamp, rejected=rejected),
        media_type="application/x-ndjson",
    )


def _event(payload: dict) -> str:
    """NDJSON 的一行。"""
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _step_label(step, count: int) -> str:
    return ("转写原声" if step.stage == "reference"
            else f"转写第 {step.index}/{count} 遍")


def _review_stream(*, segment, unit, ref_path, ref_words, paths, run_id, stamp,
                   rejected=()):
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
            db.finish_run(connection, run_id)
        finally:
            connection.close()

        yield _event({"result": _review_payload(
            result, run_id, rejected=rejected,
            audio={"ref": f"/audio/{segment}/{unit}",
                   "usr": f"/take/{result.best.path.name}"})})
    except Exception as exc:
        log.exception("片段 %s 单元 %s 的比对失败", segment, unit)
        yield _event({"error": f"比对失败：{exc}"})


def _review_payload(result, run_id: int, *, audio: dict, rejected=()) -> dict:
    summary = result.summary
    best = result.best
    problems = [
        {"kind": t.kind, "ref": t.ref_text, "usr": t.usr_text}
        for t in best.tokens
        if t.kind != "equal" and t.ref_index not in result.shaky
    ]
    return {
        "run_id": run_id,
        "view": feedback_view(result, MAX_ADVICE, audio=audio),
        "count": summary.count,
        "skipped": [{"name": n, "drift": round(d, 1)} for n, d in result.skipped],
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
