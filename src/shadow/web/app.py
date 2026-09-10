"""网页版：命令行逻辑的一层薄壳。

所有分析都复用现有模块，这里只负责取数据、渲染页面、接收提交。
不用前端框架：四步各是一段，服务端渲染 + 表单提交就够了，
唯一需要 JS 的是浏览器录音。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Body, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import config, db, media
from ..drill.gapfill import blanks_of
from ..drill.units import split_into_units

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


def _unit_audio(connection, segment_id: int, unit: int) -> Path:
    """按需裁出单元音频并缓存。"""
    segment, words = _unit_words(connection, segment_id, unit)
    source = db.get_source(connection, segment["source_id"])
    if source is None or not source["audio_path"]:
        raise HTTPException(404, "素材音频缺失")
    dest = config.segment_audio_dir() / f"{segment_id}-u{unit}.wav"
    start = max(segment["start_sec"], words[0].start - 0.1)
    end = min(segment["end_sec"], words[-1].end + 0.1)
    if not dest.exists():
        media.cut_segment(Path(source["audio_path"]), dest, start=start, end=end)
    return dest


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
                })
    done = {}
    for run in db.list_runs(connection):
        if run["unit_text"]:
            done.setdefault(run["unit_text"], []).append(run)
    for item in catalogue:
        item["runs"] = len(done.get(item["text"], ()))
    return templates.TemplateResponse(
        request, "index.html",
        {"catalogue": catalogue, "sources": sources},
    )


@app.get("/practice/{segment_id}/{unit}", response_class=HTMLResponse)
def practice(request: Request, segment_id: int, unit: int):
    connection = _db()
    segment, words = _unit_words(connection, segment_id, unit)
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
        },
    )


@app.get("/audio/{segment_id}/{unit}")
def audio(segment_id: int, unit: int):
    connection = _db()
    return FileResponse(_unit_audio(connection, segment_id, unit),
                        media_type="audio/wav")


@app.post("/api/rating")
def save_rating(segment: int = Form(...), unit: int = Form(...),
                rating: int = Form(...)):
    if not 1 <= rating <= 5:
        raise HTTPException(400, "评分必须是 1-5")
    connection = _db()
    _, words = _unit_words(connection, segment, unit)
    run_id = db.start_run(connection, segment_id=segment, unit_index=unit,
                          unit_text=" ".join(w.text for w in words))
    db.set_blind_rating(connection, run_id, rating)
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
    run_id = db.start_run(connection, segment_id=segment, unit_index=unit,
                          unit_text=" ".join(w.text for w in words))
    db.set_gapfill(connection, run_id, correct, len(blanks), heard, replays)
    db.finish_run(connection, run_id)
    return {"correct": correct, "total": len(blanks), "heard": heard,
            "replays": replays, "items": items, "run_id": run_id}
