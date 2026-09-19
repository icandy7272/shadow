"""素材库：当前练哪一份、每份的概况、彻底删除。只管数据和文件，不碰 HTTP。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import config, db, progress
from .drill.units import split_into_units

log = logging.getLogger(__name__)

CURRENT = "current_source"
STEPS = {
    db.STATUS_PENDING: "查信息",
    db.STATUS_PROBING: "查信息",
    db.STATUS_DOWNLOADING: "下载",
    db.STATUS_TRANSCRIBING: "转写",
    db.STATUS_SEGMENTING: "切句",
}


class LibraryError(RuntimeError):
    """做不了的操作。消息直接给人看。"""


@dataclass(frozen=True, slots=True)
class Card:
    id: int
    title: str
    status: str
    step: str | None            # 导入进行到哪一步；导完或失败为 None
    error: str | None
    minutes: float
    sentences: int
    practised: int              # 练过几句
    rounds: int                 # 一共几轮练习
    takes: int                  # 一共几遍录音
    last_practised: str | None  # 上次练的时间戳，页面上用 day 过滤器写成日期
    current: bool


def _ready(conn) -> list:
    return [row for row in db.list_sources(conn) if row["status"] == db.STATUS_READY]


def _last_practised(runs) -> str | None:
    return max((run["finished_at"] for run in runs), default=None)


def current(conn) -> int | None:
    """首页该显示哪份：上次打开的那份；它不在了，挑最近练过的；都没练过，挑最新导入的。"""
    ready = _ready(conn)
    ids = {row["id"] for row in ready}
    chosen = db.get_setting(conn, CURRENT)
    if chosen is not None and int(chosen) in ids:
        return int(chosen)
    practised = [(last, row["id"]) for row in ready
                 if (last := _last_practised(db.source_runs(conn, row["id"])))]
    if practised:
        return max(practised)[1]
    return ready[-1]["id"] if ready else None


def select(conn, source_id: int) -> None:
    db.set_setting(conn, CURRENT, str(source_id))


def _usable_texts(conn, source_id: int) -> list[str]:
    """能练的句子原文，按先后排。音频里没有这句、时间戳挤坏了的不算——列表里也不列它们。"""
    from . import media

    audio = db.get_source(conn, source_id)["audio_path"]
    return [" ".join(word.text for word in words)
            for row in db.list_segments(conn, source_id)
            for words in split_into_units(db.get_segment(conn, row["id"])["words"])
            if media.unit_problem(audio, words) is None]


def cards(conn) -> list[Card]:
    """每份素材一张卡片，新导入的在前。"""
    chosen = current(conn)
    out = []
    for row in reversed(db.list_sources(conn)):
        runs = db.source_runs(conn, row["id"])
        texts = _usable_texts(conn, row["id"]) if row["status"] == db.STATUS_READY else []
        # 和列表对得上：练过、后来又不列了的句子不算进「练过几句」
        done = {run["unit_text"] for run in runs if run["unit_text"]}
        out.append(Card(
            id=row["id"], title=row["title"], status=row["status"],
            step=STEPS.get(row["status"]), error=row["error"],
            minutes=row["duration_sec"] / 60,
            sentences=len(texts),
            practised=sum(1 for text in texts if text in done),
            rounds=len(runs), takes=db.count_takes(conn, row["id"]),
            last_practised=_last_practised(runs),
            current=row["id"] == chosen,
        ))
    return out


def remove(conn, source_id: int) -> int | None:
    """彻底删掉一份素材，只留下打卡。返回删完之后的当前素材。"""
    row = db.get_source(conn, source_id)
    if row is None:
        raise LibraryError("这份素材已经不在了。")
    if row["status"] not in db.TERMINAL_STATUSES:
        raise LibraryError("这份素材还在导入，等它完成或失败再删。")
    removed = db.delete_source(conn, source_id,
                               archive=progress.archive_rows(conn, source_id))
    if db.get_setting(conn, CURRENT) == str(source_id):
        db.set_setting(conn, CURRENT, None)
    _delete_files(removed)
    return current(conn)


def _delete_files(removed: db.Removed) -> None:
    """只删数据目录里的文件：库里记的路径不能拿来随便删。删不掉只记日志。"""
    root = config.data_dir().resolve()
    paths = [Path(path) for path in removed.audio_paths]
    for segment_id in removed.segment_ids:
        paths.extend(config.segment_audio_dir().glob(f"{segment_id}-u*.wav"))
    for path in paths:
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            log.warning("不在数据目录里，不删：%s", path)
            continue
        try:
            resolved.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("删不掉 %s：%s", path, exc)
