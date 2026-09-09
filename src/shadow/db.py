"""SQLite 存储层。所有写入只追加，状态字段是唯一可变的东西。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any, Sequence

from . import config
from .models import Segment, words_from_json, words_to_json

STATUS_PENDING = "pending"
STATUS_DOWNLOADING = "downloading"
STATUS_TRANSCRIBING = "transcribing"
STATUS_SEGMENTING = "segmenting"
STATUS_READY = "ready"
STATUS_FAILED = "failed"

TERMINAL_STATUSES = (STATUS_READY, STATUS_FAILED)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    url           TEXT NOT NULL,
    title         TEXT NOT NULL,
    duration_sec  REAL NOT NULL,
    audio_path    TEXT,
    status        TEXT NOT NULL,
    error         TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS segments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id  INTEGER NOT NULL REFERENCES sources(id),
    idx        INTEGER NOT NULL,
    start_sec  REAL NOT NULL,
    end_sec    REAL NOT NULL,
    text       TEXT NOT NULL,
    words_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS practice_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    segment_id      INTEGER NOT NULL REFERENCES segments(id),
    blind_rating    INTEGER,
    gapfill_correct INTEGER,
    gapfill_total   INTEGER,
    started_at      TEXT NOT NULL,
    finished_at     TEXT
);

CREATE TABLE IF NOT EXISTS attempts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER NOT NULL REFERENCES practice_runs(id),
    audio_path   TEXT NOT NULL,
    asr_text     TEXT,
    diff_json    TEXT,
    prosody_json TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS saved_phrases (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    segment_id INTEGER NOT NULL REFERENCES segments(id),
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_segments_source ON segments(source_id);
CREATE INDEX IF NOT EXISTS idx_attempts_run ON attempts(run_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    config.ensure_dirs()
    connection = sqlite3.connect(config.db_path())
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def create_source(
    conn: sqlite3.Connection, *, url: str, title: str, duration_sec: float
) -> int:
    cursor = conn.execute(
        "INSERT INTO sources (url, title, duration_sec, status, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (url, title, duration_sec, STATUS_PENDING, _now()),
    )
    conn.commit()
    return int(cursor.lastrowid)


def set_source_status(conn: sqlite3.Connection, source_id: int, status: str) -> None:
    conn.execute("UPDATE sources SET status = ? WHERE id = ?", (status, source_id))
    conn.commit()


def fail_source(conn: sqlite3.Connection, source_id: int, error: str) -> None:
    conn.execute(
        "UPDATE sources SET status = ?, error = ? WHERE id = ?",
        (STATUS_FAILED, error, source_id),
    )
    conn.commit()


def finish_source(conn: sqlite3.Connection, source_id: int, *, audio_path: str) -> None:
    conn.execute(
        "UPDATE sources SET status = ?, audio_path = ?, error = NULL WHERE id = ?",
        (STATUS_READY, audio_path, source_id),
    )
    conn.commit()


def get_source(conn: sqlite3.Connection, source_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()


def list_sources(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM sources ORDER BY id"))


def reset_stale_sources(conn: sqlite3.Connection) -> int:
    """进程重启后，把卡在中间态的记录一律标记为 failed，避免留下永远转圈的僵尸记录。"""
    placeholders = ", ".join("?" for _ in TERMINAL_STATUSES)
    cursor = conn.execute(
        f"UPDATE sources SET status = ?, error = ?"
        f" WHERE status NOT IN ({placeholders})",
        (STATUS_FAILED, "导入过程被中断（进程退出）", *TERMINAL_STATUSES),
    )
    conn.commit()
    return cursor.rowcount


def insert_segments(
    conn: sqlite3.Connection, source_id: int, segments: Sequence[Segment]
) -> None:
    conn.executemany(
        "INSERT INTO segments (source_id, idx, start_sec, end_sec, text, words_json)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                source_id,
                segment.idx,
                segment.start,
                segment.end,
                segment.text,
                words_to_json(segment.words),
            )
            for segment in segments
        ],
    )
    conn.commit()


def list_segments(conn: sqlite3.Connection, source_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM segments WHERE source_id = ? ORDER BY idx", (source_id,)
        )
    )


def get_segment(conn: sqlite3.Connection, segment_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM segments WHERE id = ?", (segment_id,)).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["words"] = words_from_json(row["words_json"])
    return data
