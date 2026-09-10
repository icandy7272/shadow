"""SQLite 存储层。所有写入只追加，状态字段是唯一可变的东西。"""

from __future__ import annotations

import json
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


# 已有数据库要就地加列。老库是 M1 建的，那时还没有练习单元和指标存储。
MIGRATIONS = (
    ("practice_runs", "unit_index", "INTEGER"),
    ("practice_runs", "unit_text", "TEXT"),
    ("practice_runs", "gapfill_heard", "INTEGER"),
    ("practice_runs", "gapfill_replays", "INTEGER"),
    ("attempts", "metrics_json", "TEXT"),
)


def _ensure_columns(conn: sqlite3.Connection) -> None:
    for table, column, column_type in MIGRATIONS:
        present = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in present:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
    conn.commit()


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
    _ensure_columns(conn)


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


# --- 练习记录 ---------------------------------------------------------------


def start_run(
    conn: sqlite3.Connection,
    *,
    segment_id: int,
    unit_index: int | None,
    unit_text: str | None = None,
) -> int:
    """记下练的是哪一句，而不只是序号——切分规则一变，序号就失去意义。"""
    cursor = conn.execute(
        "INSERT INTO practice_runs (segment_id, unit_index, unit_text, started_at)"
        " VALUES (?, ?, ?, ?)",
        (segment_id, unit_index, unit_text, _now()),
    )
    conn.commit()
    return int(cursor.lastrowid)


def set_blind_rating(conn: sqlite3.Connection, run_id: int, rating: int) -> None:
    conn.execute(
        "UPDATE practice_runs SET blind_rating = ? WHERE id = ?", (rating, run_id)
    )
    conn.commit()


def set_gapfill(
    conn: sqlite3.Connection, run_id: int, correct: int, total: int,
    heard: int | None = None, replays: int | None = None,
) -> None:
    """heard = 答对且自称听出来的；replays = 重听次数。

    重听次数是必要的：「给无限次重听能挖出来」和「一遍就听懂」差得很远，
    不记下来，两者会被混成同一个分数。
    """
    conn.execute(
        "UPDATE practice_runs SET gapfill_correct = ?, gapfill_total = ?,"
        " gapfill_heard = ?, gapfill_replays = ? WHERE id = ?",
        (correct, total, heard, replays, run_id),
    )
    conn.commit()


def finish_run(conn: sqlite3.Connection, run_id: int) -> None:
    conn.execute(
        "UPDATE practice_runs SET finished_at = ? WHERE id = ?", (_now(), run_id)
    )
    conn.commit()


def add_attempt(
    conn: sqlite3.Connection,
    *,
    run_id: int,
    audio_path: str,
    asr_text: str,
    metrics: dict[str, Any],
) -> int:
    cursor = conn.execute(
        "INSERT INTO attempts (run_id, audio_path, asr_text, metrics_json, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (run_id, audio_path, asr_text, json.dumps(metrics, ensure_ascii=False), _now()),
    )
    conn.commit()
    return int(cursor.lastrowid)


def discard_if_empty(conn: sqlite3.Connection, run_id: int) -> bool:
    """一条什么都没记下的练习记录（中途取消）不该算作练过。"""
    row = conn.execute(
        "SELECT blind_rating, gapfill_total FROM practice_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        return False
    has_take = conn.execute(
        "SELECT 1 FROM attempts WHERE run_id = ? LIMIT 1", (run_id,)
    ).fetchone()
    if row["blind_rating"] is None and row["gapfill_total"] is None and not has_take:
        conn.execute("DELETE FROM practice_runs WHERE id = ?", (run_id,))
        conn.commit()
        return True
    return False


def list_runs(
    conn: sqlite3.Connection,
    *,
    segment_id: int | None = None,
    unit_index: int | None = None,
) -> list[sqlite3.Row]:
    clauses, params = ["finished_at IS NOT NULL"], []
    if segment_id is not None:
        clauses.append("segment_id = ?")
        params.append(segment_id)
    if unit_index is not None:
        clauses.append("unit_index = ?")
        params.append(unit_index)
    where = " AND ".join(clauses)
    return list(
        conn.execute(f"SELECT * FROM practice_runs WHERE {where} ORDER BY id", params)
    )


def run_metrics(conn: sqlite3.Connection, run_id: int) -> list[dict[str, Any]]:
    """一次练习里各 take 的指标。"""
    rows = conn.execute(
        "SELECT metrics_json FROM attempts WHERE run_id = ? ORDER BY id", (run_id,)
    )
    return [json.loads(row["metrics_json"]) for row in rows if row["metrics_json"]]
