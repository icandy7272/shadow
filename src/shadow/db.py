"""SQLite 存储层。所有写入只追加，状态字段是唯一可变的东西。"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

from . import config
from .models import Segment, words_from_json, words_to_json

STATUS_PENDING = "pending"
STATUS_PROBING = "probing"          # 查标题和时长
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

-- 键值设置。目前只有 current_source：首页显示哪份素材，电脑和手机一致
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- 删掉的素材只留下打卡：哪天、哪句、几轮。格子和连续天数靠它照算
CREATE TABLE IF NOT EXISTS practice_archive (
    day      TEXT NOT NULL,
    sentence TEXT NOT NULL,
    rounds   INTEGER NOT NULL
);

-- 生词本。出处不设外键：删素材时生词和原句都要留下
CREATE TABLE IF NOT EXISTS vocab (
    word        TEXT PRIMARY KEY,
    first_added TEXT NOT NULL,
    last_added  TEXT NOT NULL,
    times       INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS vocab_sources (
    word       TEXT NOT NULL,
    sentence   TEXT NOT NULL,
    segment_id INTEGER,
    unit_index INTEGER,
    added_at   TEXT NOT NULL,
    PRIMARY KEY (word, sentence)
);

-- 自己开口说的录音：每天的复述、周六的自由说。不挂在素材上——
-- 说的是自己的话，不是哪一句；换素材、删素材都还要留着和上周比
CREATE TABLE IF NOT EXISTS talks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    day        TEXT NOT NULL,
    kind       TEXT NOT NULL,
    audio_path TEXT NOT NULL,
    seconds    REAL NOT NULL,
    picks_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- 日课勾选：哪天、哪一步。按本地日期存，第二天自然是空的
CREATE TABLE IF NOT EXISTS plan_checks (
    day        TEXT NOT NULL,
    step       TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    done       INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (day, step)
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
    ("practice_runs", "saw_text", "INTEGER"),
    ("practice_runs", "gapfill_unknown", "INTEGER"),
    # 点掉的那一步也要记下来：老库里有行就等于勾上了，默认 1 正好对上
    ("plan_checks", "done", "INTEGER NOT NULL DEFAULT 1"),
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


def update_segment_words(
    conn: sqlite3.Connection, segment_id: int, words: Sequence
) -> None:
    """改写一个片段的词时间戳（强制对齐之后）。文本不动，只动时间。"""
    conn.execute("UPDATE segments SET words_json = ? WHERE id = ?",
                 (words_to_json(words), segment_id))
    conn.commit()


def get_segment(conn: sqlite3.Connection, segment_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM segments WHERE id = ?", (segment_id,)).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["words"] = words_from_json(row["words_json"])
    return data


def segment_edges(conn: sqlite3.Connection, segment_id: int) -> tuple[float, float]:
    """这个片段里的句子，音频最远能往前、往后切到哪儿：前一段的结尾、后一段的开头。

    片段自己的起止只是第一个词的开头、最后一个词的结尾——词尾的余音、词头的爆破音
    都在线外。拿它当边界，每段最后一句的词尾都会被切掉。第一段往前、最后一段往后不设限。
    """
    row = conn.execute("SELECT source_id, idx FROM segments WHERE id = ?",
                       (segment_id,)).fetchone()
    if row is None:
        raise KeyError(f"片段 {segment_id} 不存在")
    before = conn.execute(
        "SELECT end_sec FROM segments WHERE source_id = ? AND idx < ?"
        " ORDER BY idx DESC LIMIT 1", (row["source_id"], row["idx"])).fetchone()
    after = conn.execute(
        "SELECT start_sec FROM segments WHERE source_id = ? AND idx > ?"
        " ORDER BY idx LIMIT 1", (row["source_id"], row["idx"])).fetchone()
    return (before["end_sec"] if before else 0.0,
            after["start_sec"] if after else float("inf"))


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


def set_dictation(conn: sqlite3.Connection, run_id: int, *, correct: int, total: int,
                  unknown: int, replays: int) -> None:
    """整句默写的记分。沿用填空时代的列名，gapfill_heard 不再写。

    重听次数要记：「重听十遍才写出来」和「一遍就写对」差得很远，
    不记下来，两者会被混成同一个分数。
    """
    conn.execute(
        "UPDATE practice_runs SET gapfill_correct = ?, gapfill_total = ?,"
        " gapfill_unknown = ?, gapfill_replays = ? WHERE id = ?",
        (correct, total, unknown, replays, run_id))
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


def mark_saw_text(conn: sqlite3.Connection, run_id: int, seen: bool) -> None:
    """这一轮跟读前有没有看过原文。看不看对音高节奏影响多大，只能靠数据回答。"""
    conn.execute("UPDATE practice_runs SET saw_text = ? WHERE id = ?",
                 (1 if seen else 0, run_id))
    conn.commit()


def run_attempts(conn: sqlite3.Connection, run_id: int) -> list[sqlite3.Row]:
    return list(conn.execute(
        "SELECT * FROM attempts WHERE run_id = ? ORDER BY id", (run_id,)))


def set_attempt_metrics(
    conn: sqlite3.Connection, attempt_id: int, metrics: dict[str, Any] | None
) -> None:
    """重算之后改写一遍录音的指标。None 表示这一遍已不可用，不再计入。"""
    payload = None if metrics is None else json.dumps(metrics, ensure_ascii=False)
    conn.execute("UPDATE attempts SET metrics_json = ? WHERE id = ?",
                 (payload, attempt_id))
    conn.commit()


def relabel_run(
    conn: sqlite3.Connection, run_id: int, *, unit_index: int, unit_text: str
) -> None:
    """切分规则变了，同一句可能换了序号。按文本找回来之后校正。"""
    conn.execute("UPDATE practice_runs SET unit_index = ?, unit_text = ? WHERE id = ?",
                 (unit_index, unit_text, run_id))
    conn.commit()


def run_metrics(conn: sqlite3.Connection, run_id: int) -> list[dict[str, Any]]:
    """一次练习里各 take 的指标。"""
    rows = conn.execute(
        "SELECT metrics_json FROM attempts WHERE run_id = ? ORDER BY id", (run_id,)
    )
    return [json.loads(row["metrics_json"]) for row in rows if row["metrics_json"]]


# --- 素材库 -----------------------------------------------------------------


def update_source_meta(conn: sqlite3.Connection, source_id: int, *,
                       title: str, duration_sec: float) -> None:
    """查到标题和时长后补上。网页导入先用链接占位，好让卡片马上出现。"""
    conn.execute("UPDATE sources SET title = ?, duration_sec = ? WHERE id = ?",
                 (title, duration_sec, source_id))
    conn.commit()


def importing_source(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """正在导入的那一份。同一时间只允许一个。"""
    placeholders = ", ".join("?" for _ in TERMINAL_STATUSES)
    return conn.execute(
        f"SELECT * FROM sources WHERE status NOT IN ({placeholders}) ORDER BY id LIMIT 1",
        TERMINAL_STATUSES,
    ).fetchone()


def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return None if row is None else row["value"]


def set_setting(conn: sqlite3.Connection, key: str, value: str | None) -> None:
    if value is None:
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))
    else:
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)"
                     " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                     (key, value))
    conn.commit()


def source_runs(conn: sqlite3.Connection, source_id: int) -> list[sqlite3.Row]:
    """这份素材上做完的练习记录。"""
    return list(conn.execute(
        "SELECT practice_runs.* FROM practice_runs"
        " JOIN segments ON segments.id = practice_runs.segment_id"
        " WHERE segments.source_id = ? AND practice_runs.finished_at IS NOT NULL"
        " ORDER BY practice_runs.id",
        (source_id,),
    ))


def count_takes(conn: sqlite3.Connection, source_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM attempts"
        " JOIN practice_runs ON practice_runs.id = attempts.run_id"
        " JOIN segments ON segments.id = practice_runs.segment_id"
        " WHERE segments.source_id = ?",
        (source_id,),
    ).fetchone()[0]


def list_archive(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT day, sentence, rounds FROM practice_archive"))


@dataclass(frozen=True, slots=True)
class Removed:
    """删掉一份素材后，留给调用方去删的磁盘文件。"""

    audio_paths: tuple[str, ...]    # 原音和每遍录音
    segment_ids: tuple[int, ...]    # 句子音频缓存按片段号命名


def delete_source(conn: sqlite3.Connection, source_id: int, *,
                  archive: Sequence[tuple[str, str, int]] = ()) -> Removed:
    """一个事务里删掉素材和挂在它下面的一切，同时写进打卡归档。

    外键没有级联，得按依赖顺序手动删。磁盘文件交给调用方——
    文件删一半失败，不该让数据库也跟着回不去。
    """
    source = get_source(conn, source_id)
    segment_ids = tuple(row["id"] for row in conn.execute(
        "SELECT id FROM segments WHERE source_id = ?", (source_id,)))
    marks = ", ".join("?" for _ in segment_ids) or "NULL"
    takes = tuple(row["audio_path"] for row in conn.execute(
        "SELECT attempts.audio_path FROM attempts"
        " JOIN practice_runs ON practice_runs.id = attempts.run_id"
        f" WHERE practice_runs.segment_id IN ({marks})", segment_ids))
    with conn:
        conn.executemany(
            "INSERT INTO practice_archive (day, sentence, rounds) VALUES (?, ?, ?)", archive)
        conn.execute("DELETE FROM attempts WHERE run_id IN"
                     f" (SELECT id FROM practice_runs WHERE segment_id IN ({marks}))",
                     segment_ids)
        conn.execute(f"DELETE FROM practice_runs WHERE segment_id IN ({marks})", segment_ids)
        conn.execute(f"DELETE FROM saved_phrases WHERE segment_id IN ({marks})", segment_ids)
        conn.execute("DELETE FROM segments WHERE source_id = ?", (source_id,))
        conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    own = (source["audio_path"],) if source is not None and source["audio_path"] else ()
    return Removed(audio_paths=own + takes, segment_ids=segment_ids)


# --- 生词本 -----------------------------------------------------------------


def add_vocab(conn: sqlite3.Connection, word: str, *, sentence: str,
              segment_id: int | None = None, unit_index: int | None = None) -> int:
    """记下一个生词，返回记过几次。同一句的出处不重复记。"""
    now = _now()
    with conn:
        conn.execute(
            "INSERT INTO vocab (word, first_added, last_added, times) VALUES (?, ?, ?, 1)"
            " ON CONFLICT(word) DO UPDATE SET last_added = excluded.last_added,"
            " times = times + 1", (word, now, now))
        conn.execute(
            "INSERT OR IGNORE INTO vocab_sources"
            " (word, sentence, segment_id, unit_index, added_at) VALUES (?, ?, ?, ?, ?)",
            (word, sentence, segment_id, unit_index, now))
    return conn.execute("SELECT times FROM vocab WHERE word = ?", (word,)).fetchone()["times"]


def vocab_words(conn: sqlite3.Connection) -> set[str]:
    return {row["word"] for row in conn.execute("SELECT word FROM vocab")}


def list_vocab(conn: sqlite3.Connection, *, by: str = "recent") -> list[dict[str, Any]]:
    """生词本，每个词带上全部出处。

    by="recent" 最近记下的在前，by="times" 记得最多的在前。同一秒里记下的几个词
    按插入顺序倒着排——时间戳只精确到秒，不然同一秒的几个词会按字母排。
    """
    order = ("times DESC, last_added DESC, rowid DESC" if by == "times"
             else "last_added DESC, rowid DESC")
    items = [dict(row) for row in conn.execute(f"SELECT * FROM vocab ORDER BY {order}")]
    sources: dict[str, list[dict[str, Any]]] = {}
    for row in conn.execute("SELECT * FROM vocab_sources ORDER BY added_at, rowid"):
        sources.setdefault(row["word"], []).append(dict(row))
    return [{**item, "sources": sources.get(item["word"], [])} for item in items]


def remove_vocab(conn: sqlite3.Connection, word: str) -> bool:
    with conn:
        conn.execute("DELETE FROM vocab_sources WHERE word = ?", (word,))
        cursor = conn.execute("DELETE FROM vocab WHERE word = ?", (word,))
    return cursor.rowcount > 0


# --- 日课 -------------------------------------------------------------------


def add_talk(conn: sqlite3.Connection, *, day: str, kind: str, audio_path: str,
             seconds: float, picks: Sequence[str] = ()) -> int:
    """记下一段自己说的。picks 是开口前挑的那几个表达，回头才知道这段在练什么。"""
    cursor = conn.execute(
        "INSERT INTO talks (day, kind, audio_path, seconds, picks_json, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (day, kind, audio_path, seconds, json.dumps(list(picks), ensure_ascii=False), _now()))
    conn.commit()
    return int(cursor.lastrowid)


def list_talks(conn: sqlite3.Connection, *, kind: str,
               limit: int = 20) -> list[dict[str, Any]]:
    """同一种里最近的几段，新的在前。复述和自由说各比各的，不混在一起。"""
    rows = conn.execute(
        "SELECT * FROM talks WHERE kind = ? ORDER BY day DESC, id DESC LIMIT ?",
        (kind, limit))
    return [{**dict(row), "picks": json.loads(row["picks_json"])} for row in rows]


def talk_kinds_on(conn: sqlite3.Connection, day: str) -> set[str]:
    """这一天录过哪几种。日课里「说」的那一步靠它自己划掉，不用再勾一次。"""
    return {row["kind"] for row in conn.execute(
        "SELECT DISTINCT kind FROM talks WHERE day = ?", (day,))}


def remove_talk(conn: sqlite3.Connection, talk_id: int) -> str | None:
    """删掉一段，返回它的音频路径好让调用方删文件。没有这一段就返回 None。"""
    row = conn.execute("SELECT audio_path FROM talks WHERE id = ?", (talk_id,)).fetchone()
    if row is None:
        return None
    conn.execute("DELETE FROM talks WHERE id = ?", (talk_id,))
    conn.commit()
    return row["audio_path"]


def plan_checks(conn: sqlite3.Connection, day: str) -> dict[str, bool]:
    """这一天自己点过的那几步，勾上还是点掉。day 是本地日期 YYYY-MM-DD。

    点掉要和「没点过」分开记：系统自己看得出来做完了的那几步会默认勾上，
    只有明确点掉的那一次能压住它。
    """
    return {row["step"]: bool(row["done"]) for row in conn.execute(
        "SELECT step, done FROM plan_checks WHERE day = ?", (day,))}


def set_plan_check(conn: sqlite3.Connection, day: str, step: str, done: bool) -> None:
    conn.execute(
        "INSERT INTO plan_checks (day, step, checked_at, done) VALUES (?, ?, ?, ?)"
        " ON CONFLICT(day, step) DO UPDATE SET done = excluded.done,"
        " checked_at = excluded.checked_at",
        (day, step, _now(), int(done)))
    conn.commit()
