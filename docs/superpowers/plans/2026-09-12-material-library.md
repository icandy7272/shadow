# 素材库 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 网页上贴链接导入素材、素材彼此分开、在素材库里切换和彻底删除（只保留打卡）。

**Architecture:** 数据层（`db.py`）加两张表和按素材查询/删除；`progress.py` 把归档并进打卡统计；新模块 `library.py` 管「当前素材、卡片概况、删除」；`ingest/pipeline.py` 拆成「建记录」和「跑完」两步；新模块 `web/importer.py` 在后台线程里跑导入；`web/app.py` 加素材库页面和接口，句子列表按素材分开。

**Tech Stack:** Python 3.14、FastAPI 0.141 / Starlette 1.6、SQLite、Jinja2、原生 JS、pytest。

设计文档：`docs/superpowers/specs/2026-09-12-material-library-design.md`

测试命令一律 `uv run pytest ... -q -p no:warnings`。

---

## 文件结构

| 文件 | 动作 | 职责 |
|---|---|---|
| `src/shadow/db.py` | 改 | `probing` 状态、`settings` 和 `practice_archive` 表、按素材查练习、事务删除 |
| `src/shadow/progress.py` | 改 | 打卡统计并入归档；算出删除前要归档的行 |
| `src/shadow/library.py` | 新建 | 当前素材、卡片概况、彻底删除（含磁盘文件） |
| `src/shadow/ingest/pipeline.py` | 改 | `begin_import` / `run_import`，`import_source` 串起两步 |
| `src/shadow/web/importer.py` | 新建 | 后台线程导入、同一时间只导一份、重试 |
| `src/shadow/web/app.py` | 改 | 启动清理、`/` 跳转、素材列表页、素材库页、导入/重试/删除接口、句子按素材分开 |
| `src/shadow/web/templates/base.html` | 改 | 顶栏「素材库」入口、加载 `library.js` |
| `src/shadow/web/templates/index.html` | 改 | 标题换成素材名和进度 |
| `src/shadow/web/templates/library.html` | 新建 | 导入框和卡片 |
| `src/shadow/web/templates/practice.html`、`unusable.html` | 改 | 顶上素材名可点 |
| `src/shadow/web/static/library.js` | 新建 | 导入提交、轮询、重试、删除确认 |
| `src/shadow/web/static/app.css` | 改 | 入口按钮、卡片样式 |
| `tests/test_db.py`、`test_progress.py`、`test_pipeline.py`、`test_web.py` | 改 | 见各任务 |
| `tests/test_library.py`、`tests/test_importer.py` | 新建 | 见各任务 |

---

### Task 1: 数据层

**Files:**
- Modify: `src/shadow/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: 写失败的测试**（追加到 `tests/test_db.py` 末尾）

```python
def _source_with_practice(conn, *, title, text="It was."):
    source_id = db.create_source(conn, url=f"https://x/{title}", title=title,
                                 duration_sec=8.0)
    db.finish_source(conn, source_id, audio_path=f"/tmp/{title}.wav")
    db.insert_segments(conn, source_id, (Segment(
        idx=0, start=0.0, end=1.0,
        words=(Word("It", 0.0, 0.5), Word("was.", 0.5, 1.0))),))
    segment_id = db.list_segments(conn, source_id)[0]["id"]
    run_id = db.start_run(conn, segment_id=segment_id, unit_index=1, unit_text=text)
    db.add_attempt(conn, run_id=run_id, audio_path=f"/tmp/{title}-take.wav",
                   asr_text=text, metrics={"issues": []})
    db.finish_run(conn, run_id)
    return source_id, segment_id


def test_settings_round_trip(conn):
    assert db.get_setting(conn, "current_source") is None
    db.set_setting(conn, "current_source", "3")
    db.set_setting(conn, "current_source", "4")
    assert db.get_setting(conn, "current_source") == "4"
    db.set_setting(conn, "current_source", None)
    assert db.get_setting(conn, "current_source") is None


def test_importing_source_is_the_one_not_finished(conn):
    ready = db.create_source(conn, url="https://x/a", title="A", duration_sec=1.0)
    db.finish_source(conn, ready, audio_path="a.wav")
    assert db.importing_source(conn) is None
    busy = db.create_source(conn, url="https://x/b", title="B", duration_sec=0.0)
    db.set_source_status(conn, busy, db.STATUS_PROBING)
    assert db.importing_source(conn)["id"] == busy


def test_source_meta_is_filled_in_after_probing(conn):
    source_id = db.create_source(conn, url="https://x/y", title="https://x/y",
                                 duration_sec=0.0)
    db.update_source_meta(conn, source_id, title="Talk", duration_sec=90.0)
    row = db.get_source(conn, source_id)
    assert (row["title"], row["duration_sec"]) == ("Talk", 90.0)


def test_source_runs_and_takes_only_cover_that_source(conn):
    first, _ = _source_with_practice(conn, title="A")
    _source_with_practice(conn, title="B")
    assert len(db.source_runs(conn, first)) == 1
    assert db.count_takes(conn, first) == 1


def test_delete_source_leaves_nothing_behind(conn):
    doomed, doomed_segment = _source_with_practice(conn, title="A")
    kept, _ = _source_with_practice(conn, title="B")

    removed = db.delete_source(conn, doomed, archive=[("2026-09-10", "It was.", 1)])

    assert db.get_source(conn, doomed) is None
    assert db.list_segments(conn, doomed) == []
    assert db.source_runs(conn, doomed) == []
    assert conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1
    assert set(removed.audio_paths) == {"/tmp/A.wav", "/tmp/A-take.wav"}
    assert removed.segment_ids == (doomed_segment,)
    assert len(db.source_runs(conn, kept)) == 1
    assert [tuple(row) for row in db.list_archive(conn)] == [("2026-09-10", "It was.", 1)]
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `uv run pytest tests/test_db.py -q -p no:warnings`
Expected: FAIL，`AttributeError: module 'shadow.db' has no attribute 'get_setting'` 之类

- [ ] **Step 3: 实现**

`db.py` 顶部 import 加 `from dataclasses import dataclass`；状态常量加：

```python
STATUS_PENDING = "pending"
STATUS_PROBING = "probing"
```

`SCHEMA` 里 `saved_phrases` 之后、索引之前加：

```sql
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS practice_archive (
    day      TEXT NOT NULL,
    sentence TEXT NOT NULL,
    rounds   INTEGER NOT NULL
);
```

`finish_source` 之后加：

```python
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
```

文件末尾加：

```python
# --- 按素材 -----------------------------------------------------------------


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
    文件删一半失败不该让数据库也跟着回不去。
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
```

- [ ] **Step 4: 跑测试，确认通过**

Run: `uv run pytest tests/test_db.py -q -p no:warnings`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/shadow/db.py tests/test_db.py
git commit -m "feat: 数据层支持当前素材、打卡归档、按素材删除"
```

---

### Task 2: 打卡统计并入归档

**Files:**
- Modify: `src/shadow/progress.py:42-54`
- Test: `tests/test_progress.py`

- [ ] **Step 1: 写失败的测试**（追加）

```python
def test_deleting_a_source_keeps_the_grid_and_streak(tmp_path, monkeypatch):
    """删素材是彻底删，但每天练了几句、连续几天得留下来。"""
    conn, segment_id = _seeded(tmp_path, monkeypatch)
    for unit, days_ago in ((1, 0), (1, 0), (2, 1), (3, 2)):
        _round(conn, segment_id, unit=unit, days_ago=days_ago)
    source_id = db.get_segment(conn, segment_id)["source_id"]
    before = progress.calendar(conn, weeks=4)

    db.delete_source(conn, source_id, archive=progress.archive_rows(conn, source_id))

    after = progress.calendar(conn, weeks=4)
    assert after == before
    assert (after.today, after.streak) == (1, 3)
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `uv run pytest tests/test_progress.py -q -p no:warnings -k keeps_the_grid`
Expected: FAIL，`AttributeError: ... has no attribute 'archive_rows'`

- [ ] **Step 3: 实现**，把 `_practised` 换成：

```python
def _rounds(connection, runs) -> dict[tuple[str, str], int]:
    """每天每句练了几轮。没录音的一轮不算——那一轮什么也没留下。"""
    tally: dict[tuple[str, str], int] = defaultdict(int)
    for run in runs:
        if not db.run_metrics(connection, run["id"]):
            continue
        when = _local_day(run["finished_at"] or run["started_at"])
        if when is None:
            continue
        tally[(when, run["unit_text"] or f'{run["segment_id"]}-{run["unit_index"]}')] += 1
    return tally


def _practised(connection) -> tuple[dict[str, set[str]], dict[str, int]]:
    """每天练过哪些句子、一共几轮。删掉的素材只剩归档，照样算进来。"""
    tally = _rounds(connection, db.list_runs(connection))
    for row in db.list_archive(connection):
        tally[(row["day"], row["sentence"])] += row["rounds"]
    by_day: dict[str, set[str]] = defaultdict(set)
    counts: dict[str, int] = defaultdict(int)
    for (day, sentence), rounds in tally.items():
        by_day[day].add(sentence)
        counts[day] += rounds
    return by_day, counts


def archive_rows(connection, source_id: int) -> list[tuple[str, str, int]]:
    """删素材前要留下的打卡：哪天、哪句、几轮。"""
    tally = _rounds(connection, db.source_runs(connection, source_id))
    return [(day, sentence, rounds) for (day, sentence), rounds in sorted(tally.items())]
```

- [ ] **Step 4: 跑 `tests/test_progress.py` 全部，确认通过**
- [ ] **Step 5: 提交** `feat: 打卡统计并入已删除素材的归档`

---

### Task 3: 素材库模块

**Files:**
- Create: `src/shadow/library.py`
- Test: `tests/test_library.py`

- [ ] **Step 1: 写失败的测试**

```python
"""素材库：当前练哪份、每份的概况、彻底删除。"""

import pytest

from shadow import config, db, library, progress
from shadow.models import Segment, Word


@pytest.fixture()
def conn(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path / "data"))
    connection = db.connect()
    db.init_db(connection)
    yield connection
    connection.close()


def _ready(conn, title, *, practised=False):
    """一份能练的素材：两句话，原音和第 1 句的缓存都真写到磁盘上。"""
    source_id = db.create_source(conn, url=f"https://x/{title}", title=title,
                                 duration_sec=120.0)
    audio = config.source_audio_dir() / f"{source_id}.wav"
    audio.write_bytes(b"RIFF")
    db.finish_source(conn, source_id, audio_path=str(audio))
    words = (Word("One", 0.0, 0.4), Word("two.", 0.5, 0.9),
             Word("Three", 1.0, 1.4), Word("four.", 1.5, 1.9))
    db.insert_segments(conn, source_id, (Segment(idx=0, start=0.0, end=2.0, words=words),))
    segment_id = db.list_segments(conn, source_id)[0]["id"]
    (config.segment_audio_dir() / f"{segment_id}-u1.wav").write_bytes(b"RIFF")
    if practised:
        run_id = db.start_run(conn, segment_id=segment_id, unit_index=1, unit_text="One two.")
        take = config.attempt_audio_dir() / f"{segment_id}-u1-take-1.wav"
        take.write_bytes(b"RIFF")
        db.add_attempt(conn, run_id=run_id, audio_path=str(take), asr_text="One two.",
                       metrics={"issues": []})
        db.finish_run(conn, run_id)
    return source_id


def test_current_is_the_one_you_opened_last(conn):
    first = _ready(conn, "A")
    _ready(conn, "B")
    library.select(conn, first)
    assert library.current(conn) == first


def test_without_a_choice_current_is_the_last_practised_then_the_newest(conn):
    practised = _ready(conn, "A", practised=True)
    newest = _ready(conn, "B")
    assert library.current(conn) == practised
    db.delete_source(conn, practised)
    assert library.current(conn) == newest


def test_a_source_still_importing_is_never_current(conn):
    ready = _ready(conn, "A")
    busy = db.create_source(conn, url="https://x/b", title="B", duration_sec=0.0)
    library.select(conn, busy)
    assert library.current(conn) == ready


def test_nothing_ready_means_no_current(conn):
    assert library.current(conn) is None


def test_cards_show_progress_and_import_steps(conn):
    source_id = _ready(conn, "A", practised=True)
    busy = db.create_source(conn, url="https://x/b", title="https://x/b", duration_sec=0.0)
    db.set_source_status(conn, busy, db.STATUS_TRANSCRIBING)

    cards = {card.id: card for card in library.cards(conn)}

    ready = cards[source_id]
    assert (ready.sentences, ready.practised, ready.rounds, ready.takes) == (2, 1, 1, 1)
    assert ready.minutes == pytest.approx(2.0)
    assert ready.step is None and ready.last_practised is not None
    assert cards[busy].step == "转写"
    assert [card.id for card in library.cards(conn)][0] == busy   # 新导入的在前


def test_remove_deletes_rows_and_files_but_keeps_the_streak(conn):
    doomed = _ready(conn, "A", practised=True)
    kept = _ready(conn, "B")
    library.select(conn, doomed)
    before = progress.calendar(conn, weeks=2)

    after = library.remove(conn, doomed)

    assert after == kept
    assert db.get_source(conn, doomed) is None
    assert list(config.attempt_audio_dir().iterdir()) == []
    assert not (config.source_audio_dir() / f"{doomed}.wav").exists()
    kept_segment = db.list_segments(conn, kept)[0]["id"]
    assert [p.name for p in config.segment_audio_dir().iterdir()] == [f"{kept_segment}-u1.wav"]
    assert progress.calendar(conn, weeks=2) == before


def test_remove_refuses_while_importing(conn):
    busy = db.create_source(conn, url="https://x/b", title="B", duration_sec=0.0)
    with pytest.raises(library.LibraryError, match="导入"):
        library.remove(conn, busy)


def test_remove_never_touches_files_outside_the_data_folder(conn, tmp_path_factory):
    """库里记的路径不能拿来随便删。"""
    outside = tmp_path_factory.mktemp("elsewhere") / "keep.wav"
    outside.write_bytes(b"RIFF")
    source_id = db.create_source(conn, url="https://x/y", title="T", duration_sec=1.0)
    db.finish_source(conn, source_id, audio_path=str(outside))

    library.remove(conn, source_id)

    assert outside.exists()
```

- [ ] **Step 2: 跑测试，确认失败**（`ImportError: cannot import name 'library'`）

- [ ] **Step 3: 实现 `src/shadow/library.py`**

```python
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
    last_practised: str | None  # 本地日期，如 09-12
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


def _sentence_count(conn, source_id: int) -> int:
    return sum(len(split_into_units(db.get_segment(conn, row["id"])["words"]))
               for row in db.list_segments(conn, source_id))


def _local_day(stamp: str | None) -> str | None:
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp).astimezone().strftime("%m-%d")
    except ValueError:
        return None


def cards(conn) -> list[Card]:
    """每份素材一张卡片，新导入的在前。"""
    chosen = current(conn)
    out = []
    for row in reversed(db.list_sources(conn)):
        runs = db.source_runs(conn, row["id"])
        out.append(Card(
            id=row["id"], title=row["title"], status=row["status"],
            step=STEPS.get(row["status"]), error=row["error"],
            minutes=row["duration_sec"] / 60,
            sentences=(_sentence_count(conn, row["id"])
                       if row["status"] == db.STATUS_READY else 0),
            practised=len({run["unit_text"] for run in runs if run["unit_text"]}),
            rounds=len(runs), takes=db.count_takes(conn, row["id"]),
            last_practised=_local_day(_last_practised(runs)),
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
```

- [ ] **Step 4: 跑 `tests/test_library.py`，确认通过**
- [ ] **Step 5: 提交** `feat: 素材库模块——当前素材、卡片概况、彻底删除`

---

### Task 4: 导入拆成两步

**Files:**
- Modify: `src/shadow/ingest/pipeline.py:48-80`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: 改测试**

把 `test_import_rejects_overlong_source` 换成：

```python
def test_import_rejects_overlong_source(conn, monkeypatch):
    monkeypatch.setattr(pipeline, "probe", lambda url: ("Long", 3601.0))
    with pytest.raises(pipeline.ImportError_, match="60"):
        pipeline.import_source("https://x/y", conn=conn)
    row = db.list_sources(conn)[0]
    assert row["status"] == db.STATUS_FAILED
    assert "60" in row["error"]
```

追加：

```python
def test_begin_import_returns_at_once_with_the_link_as_title(conn, monkeypatch):
    monkeypatch.setattr(pipeline, "probe", lambda url: pytest.fail("这一步不该联网"))
    source_id = pipeline.begin_import("https://x/y", conn=conn)
    row = db.get_source(conn, source_id)
    assert (row["status"], row["title"]) == (db.STATUS_PENDING, "https://x/y")


def test_begin_import_rejects_a_non_http_link(conn):
    with pytest.raises(DownloadError):
        pipeline.begin_import("ftp://x/y", conn=conn)
    assert db.list_sources(conn) == []


def test_run_import_walks_through_every_status(conn, stub_externals, monkeypatch):
    seen = []
    real = db.set_source_status
    monkeypatch.setattr(pipeline.db, "set_source_status",
                        lambda c, i, s: (seen.append(s), real(c, i, s)))
    source_id = pipeline.begin_import("https://x/y", conn=conn)

    pipeline.run_import(source_id, conn=conn)

    assert seen == [db.STATUS_PROBING, db.STATUS_DOWNLOADING,
                    db.STATUS_TRANSCRIBING, db.STATUS_SEGMENTING]
    row = db.get_source(conn, source_id)
    assert (row["status"], row["title"], row["duration_sec"]) == (db.STATUS_READY, "Talk", 100.0)
```

- [ ] **Step 2: 跑测试，确认失败**
- [ ] **Step 3: 实现**，把 `import_source` 换成：

```python
def begin_import(url: str, *, conn: sqlite3.Connection) -> int:
    """建一条导入记录，马上返回。标题和时长要查过才知道，先用链接占位。"""
    clean_url = validate_url(url)
    return db.create_source(conn, url=clean_url, title=clean_url, duration_sec=0.0)


def run_import(source_id: int, *, conn: sqlite3.Connection) -> None:
    """把一条导入记录跑完。任何一步出错都记下原始错误并原样抛出。"""
    url = db.get_source(conn, source_id)["url"]
    try:
        db.set_source_status(conn, source_id, db.STATUS_PROBING)
        title, duration = probe(url)
        limit_sec = config.MAX_SOURCE_MINUTES * 60
        if duration > limit_sec:
            raise ImportError_(
                f"素材时长 {duration / 60:.1f} 分钟，超过上限 "
                f"{config.MAX_SOURCE_MINUTES:.0f} 分钟。请改用更短的素材或先自行裁剪。"
            )
        db.update_source_meta(conn, source_id, title=title, duration_sec=duration)

        db.set_source_status(conn, source_id, db.STATUS_DOWNLOADING)
        wav_path = config.source_audio_dir() / f"{source_id}.wav"
        with tempfile.TemporaryDirectory() as workdir:
            download_audio(url, wav_path, workdir=Path(workdir))

        db.set_source_status(conn, source_id, db.STATUS_TRANSCRIBING)
        words = transcribe_words(wav_path)

        db.set_source_status(conn, source_id, db.STATUS_SEGMENTING)
        words = _realign(wav_path, words)
        segments = _apply_blanks(split_into_segments(words))
        db.insert_segments(conn, source_id, segments)

        db.finish_source(conn, source_id, audio_path=str(wav_path))
    except Exception as exc:
        db.fail_source(conn, source_id, str(exc))
        raise


def import_source(url: str, *, conn: sqlite3.Connection) -> int:
    """命令行用：建记录并跑完。"""
    source_id = begin_import(url, conn=conn)
    run_import(source_id, conn=conn)
    return source_id
```

- [ ] **Step 4: 跑 `tests/test_pipeline.py` 和 `tests/test_cli.py`，确认通过**
- [ ] **Step 5: 提交** `refactor: 导入拆成建记录和跑完两步，查信息也记状态`

---

### Task 5: 后台导入

**Files:**
- Create: `src/shadow/web/importer.py`
- Test: `tests/test_importer.py`

- [ ] **Step 1: 写失败的测试**

```python
"""网页导入：记录马上建好，下载转写交给后台。"""

import pytest

from shadow import db
from shadow.ingest.downloader import DownloadError
from shadow.web import importer


@pytest.fixture(autouse=True)
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path))
    connection = db.connect()
    db.init_db(connection)
    connection.close()


def _rows():
    connection = db.connect()
    try:
        return [dict(row) for row in db.list_sources(connection)]
    finally:
        connection.close()


def test_start_creates_the_record_and_hands_it_to_the_background():
    launched = []
    source_id = importer.start("https://x/y", launch=launched.append)
    assert launched == [source_id]
    assert _rows()[0]["status"] == db.STATUS_PENDING


def test_only_one_import_at_a_time():
    importer.start("https://x/a", launch=lambda source_id: None)
    with pytest.raises(importer.Busy):
        importer.start("https://x/b", launch=lambda source_id: None)
    assert len(_rows()) == 1


def test_a_bad_link_creates_nothing():
    with pytest.raises(DownloadError):
        importer.start("not a link", launch=lambda source_id: None)
    assert _rows() == []


def test_retry_replaces_the_failed_record():
    connection = db.connect()
    failed = db.create_source(connection, url="https://x/y", title="T", duration_sec=0.0)
    db.fail_source(connection, failed, "ERROR: Video unavailable")
    connection.close()
    launched = []

    fresh = importer.retry(failed, launch=launched.append)

    assert [row["id"] for row in _rows()] == [fresh]
    assert launched == [fresh]


def test_only_a_failed_import_can_be_retried():
    connection = db.connect()
    ready = db.create_source(connection, url="https://x/y", title="T", duration_sec=1.0)
    db.finish_source(connection, ready, audio_path="a.wav")
    connection.close()
    with pytest.raises(importer.NotRetryable):
        importer.retry(ready, launch=lambda source_id: None)


def test_the_background_run_never_raises(monkeypatch):
    """线程里的异常没人接；错误已经由 run_import 记进库里。"""
    def boom(source_id, conn):
        raise RuntimeError("ERROR: Video unavailable")

    monkeypatch.setattr(importer.pipeline, "run_import", boom)
    importer._run(1)
```

- [ ] **Step 2: 跑测试，确认失败**
- [ ] **Step 3: 实现 `src/shadow/web/importer.py`**

```python
"""网页导入：记录马上建好，下载、转写、切句在后台线程里跑。同一时间只导入一份。

跑在服务进程里：关掉终端或改代码触发自动重载，线程就没了。
服务再启动时会把卡在半路的记录标成「导入被中断」，点重试即可。
"""

from __future__ import annotations

import logging
import threading

from .. import db, library
from ..ingest import pipeline

log = logging.getLogger(__name__)
_lock = threading.Lock()


class Busy(RuntimeError):
    """上一份还在导入。"""


class NotRetryable(RuntimeError):
    """只有导入失败的素材能重试。"""


def _run(source_id: int) -> None:
    connection = db.connect()
    try:
        pipeline.run_import(source_id, conn=connection)
    except Exception:
        log.exception("素材 %s 导入失败", source_id)
    finally:
        connection.close()


def _in_background(source_id: int) -> None:
    threading.Thread(target=_run, args=(source_id,), daemon=True,
                     name=f"import-{source_id}").start()


def start(url: str, *, launch=None) -> int:
    """建记录、交给后台，立刻返回素材号。链接格式不对抛 DownloadError。"""
    # 默认值在运行时解析：测试要能换掉 _in_background
    launch = launch or _in_background
    with _lock:
        connection = db.connect()
        try:
            if db.importing_source(connection) is not None:
                raise Busy("上一份还在导入，等它完成再导入下一份。")
            source_id = pipeline.begin_import(url, conn=connection)
        finally:
            connection.close()
    launch(source_id)
    return source_id


def retry(source_id: int, *, launch=None) -> int:
    """用原链接重新导入，删掉失败的那条。"""
    connection = db.connect()
    try:
        row = db.get_source(connection, source_id)
        if row is None or row["status"] != db.STATUS_FAILED:
            raise NotRetryable("只有导入失败的素材能重试。")
        url = row["url"]
        library.remove(connection, source_id)
    finally:
        connection.close()
    return start(url, launch=launch)
```

- [ ] **Step 4: 跑 `tests/test_importer.py`，确认通过**
- [ ] **Step 5: 提交** `feat: 网页导入在后台线程里跑，同一时间只导一份`

---

### Task 6: 句子按素材分开

**Files:**
- Modify: `src/shadow/web/app.py`（`_place`、`_sentences`、`index`、`practice`）
- Modify: `src/shadow/web/templates/index.html`、`practice.html`、`unusable.html`
- Test: `tests/test_web.py`

- [ ] **Step 1: 写失败的测试**

在 `tests/test_web.py` 里加两个工具函数（放在 `_seed_without_blanks` 后面）：

```python
def _source_of(segment_id):
    connection = db.connect()
    try:
        return db.get_segment(connection, segment_id)["source_id"]
    finally:
        connection.close()


def _seed_second_segment():
    """在 _seed 那份素材里再加一个片段。"""
    connection = db.connect()
    source_id = next(row["id"] for row in db.list_sources(connection) if row["title"] == "T")
    words = tuple(Word(text=t_, start=a, end=a + 0.4)
                  for t_, a in (("Thank", 3.0), ("you", 3.5), ("all.", 4.0)))
    db.insert_segments(connection, source_id,
                       (Segment(idx=1, start=3.0, end=4.4, words=words),))
    segment_id = db.list_segments(connection, source_id)[-1]["id"]
    connection.close()
    return segment_id
```

把 `test_the_pager_walks_across_segment_boundaries` 换成：

```python
def test_the_pager_walks_across_segment_boundaries(client, tmp_path):
    """句子是连着编号的，走到一段的末尾该接着进下一段，不是没路了。"""
    first = _seed(tmp_path)
    second = _seed_second_segment()

    body = client.get(f"/practice/{first}/2").text
    assert f'href="/practice/{second}/1"' in body

    body = client.get(f"/practice/{second}/1").text
    assert f'href="/practice/{first}/2"' in body


def test_another_source_is_not_mixed_in(client, tmp_path):
    """新导入一份素材，它的句子不该接在上一份后面。"""
    first = _seed(tmp_path)
    other = _seed_without_blanks(tmp_path)

    body = client.get(f"/practice/{first}/2").text
    assert f"/practice/{other}/1" not in body
    assert "共 2 句" in body

    page = client.get(f"/sources/{_source_of(other)}").text
    assert f"/practice/{other}/1" in page
    assert f"/practice/{first}/1" not in page
    assert "Z" in page


def test_the_practice_page_links_back_to_its_source(client, tmp_path):
    segment_id = _seed(tmp_path)
    body = client.get(f"/practice/{segment_id}/1").text
    assert f'href="/sources/{_source_of(segment_id)}"' in body


def test_home_goes_to_the_source_you_opened_last(client, tmp_path):
    first = _seed(tmp_path)
    _seed_without_blanks(tmp_path)
    client.get(f"/sources/{_source_of(first)}")

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == f"/sources/{_source_of(first)}"


def test_home_without_sources_goes_to_the_library(client):
    response = client.get("/", follow_redirects=False)
    assert response.headers["location"] == "/sources"
```

- [ ] **Step 2: 跑测试，确认失败**
- [ ] **Step 3: 实现**

`app.py` 顶部 import 加 `from .. import library`。

`_place` 换成：

```python
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
```

`_sentences` 换成按素材取：

```python
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
```

`index` 路由换成两个：

```python
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
```

`index.html` 的 `<div class="head">` 换成：

```html
<div class="head">
  <div class="source-head">
    <h1>{{ source.title }}</h1>
    <p class="source-meta">练过 {{ practised }} / {{ catalogue|length }} 句 · {{ '%.0f'|format(source.duration_sec / 60) }} 分钟</p>
  </div>
  {% if next_unit %}
    <a class="cta" href="/practice/{{ next_unit.segment }}/{{ next_unit.unit }}">
      开始下一句 →</a>
  {% endif %}
</div>
```

空列表的提示换成 `<p class="empty">这份素材没有切出能练的句子。</p>`。

`practice.html` 和 `unusable.html` 第 2 行换成：

```html
{% block subtitle %}<span class="crumb"><a href="/sources/{{ source_id }}">{{ source }}</a> · 第 {{ number }} 句 / 共 {{ total_units }} 句</span>{% endblock %}
```

- [ ] **Step 4: 跑 `tests/test_web.py` 全部，确认通过**（`test_index_is_helpful_when_empty` 要到 Task 7 才过，这一步先确认其余全过）
- [ ] **Step 5: 提交** `feat: 句子按素材分开，首页是当前素材`

---

### Task 7: 素材库页面和接口

**Files:**
- Modify: `src/shadow/web/app.py`
- Modify: `src/shadow/web/templates/base.html`
- Create: `src/shadow/web/templates/library.html`
- Create: `src/shadow/web/static/library.js`
- Modify: `src/shadow/web/static/app.css`
- Test: `tests/test_web.py`

- [ ] **Step 1: 写失败的测试**（追加）

```python
def test_every_page_links_to_the_library(client, tmp_path):
    segment_id = _seed(tmp_path)
    for url in ("/sources", f"/sources/{_source_of(segment_id)}", f"/practice/{segment_id}/1"):
        assert 'href="/sources"' in client.get(url).text


def test_the_library_shows_every_state(client, tmp_path):
    segment_id = _seed(tmp_path)
    connection = db.connect()
    busy = db.create_source(connection, url="https://x/b", title="https://x/b", duration_sec=0.0)
    db.set_source_status(connection, busy, db.STATUS_DOWNLOADING)
    failed = db.create_source(connection, url="https://x/c", title="https://x/c", duration_sec=0.0)
    db.fail_source(connection, failed, "ERROR: Video unavailable")
    connection.close()

    body = client.get("/sources").text

    assert "T" in body and "练过 0 / 2 句" in body
    assert "下载" in body
    assert "ERROR: Video unavailable" in body and 'data-action="retry"' in body
    assert client.get("/api/sources").json()["sources"][0]["id"] == failed


def test_import_api(client, monkeypatch):
    from shadow.web import importer

    launched = []
    monkeypatch.setattr(importer, "_in_background", launched.append)

    assert client.post("/api/sources", data={"url": "not a link"}).status_code == 400
    response = client.post("/api/sources", data={"url": "https://x/y"})
    assert response.status_code == 201
    assert launched == [response.json()["id"]]
    assert client.post("/api/sources", data={"url": "https://x/z"}).status_code == 409


def test_delete_api(client, tmp_path):
    segment_id = _seed(tmp_path)
    source_id = _source_of(segment_id)
    connection = db.connect()
    busy = db.create_source(connection, url="https://x/b", title="B", duration_sec=0.0)
    db.set_source_status(connection, busy, db.STATUS_PROBING)
    connection.close()

    assert client.delete(f"/api/sources/{busy}").status_code == 409
    response = client.delete(f"/api/sources/{source_id}")
    assert response.status_code == 200
    assert response.json() == {"next": "/sources"}
    assert client.delete(f"/api/sources/{source_id}").status_code == 404


def test_starting_the_service_marks_interrupted_imports(tmp_path, monkeypatch):
    """导入跑在服务的线程里，服务一重启线程就没了。"""
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path))
    from shadow.web.app import app

    connection = db.connect()
    db.init_db(connection)
    stuck = db.create_source(connection, url="https://x/y", title="T", duration_sec=0.0)
    db.set_source_status(connection, stuck, db.STATUS_TRANSCRIBING)
    connection.close()

    with TestClient(app):
        pass

    connection = db.connect()
    assert db.get_source(connection, stuck)["status"] == db.STATUS_FAILED
    connection.close()
```

- [ ] **Step 2: 跑测试，确认失败**
- [ ] **Step 3: 实现**

`app.py`：import 加 `from contextlib import asynccontextmanager`、`from dataclasses import asdict`、`from ..ingest.downloader import DownloadError`、`from . import importer`。`app = FastAPI(...)` 换成：

```python
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
```

（`_db` 定义在 `app` 之后，`_lifespan` 只在启动时调用，届时已定义。）

路由：

```python
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
```

`base.html`：`<a href="/" class="home">Shadow</a>` 后面加 `<a href="/sources" class="nav">素材库</a>`；`app.js` 那行后面加 `<script src="/static/library.js?v={{ assets() }}"></script>`。

`library.html`：

```html
{% extends "base.html" %}
{% block subtitle %}<span class="crumb">素材库</span>{% endblock %}
{% block content %}
<div class="head"><h1>素材库</h1></div>
<form id="import-form" class="import-form">
  <input type="url" name="url" required aria-label="素材链接"
         placeholder="https://www.youtube.com/watch?v=…">
  <button class="primary" type="submit">导入</button>
</form>
<p class="hint" id="import-note">{% if importing %}上一份还在导入，等它完成再导入下一份。{% else %}YouTube、播客都行，60 分钟以内。下载、转写、切句要几分钟，期间可以照常练别的。{% endif %}</p>

{% if not cards %}
  <p class="empty">还没有导入素材。在上面贴一个链接开始。</p>
{% endif %}
<ul class="cards" id="cards">
  {% for card in cards %}
  <li class="card{{ ' current' if card.current }}" data-id="{{ card.id }}" data-status="{{ card.status }}"
      data-sentences="{{ card.sentences }}" data-rounds="{{ card.rounds }}" data-takes="{{ card.takes }}">
    <div class="card-main">
      <p class="card-title">{{ card.title }}</p>
      {% if card.status == 'ready' %}
        <p class="card-meta">{{ '%.0f'|format(card.minutes) }} 分钟 · 练过 {{ card.practised }} / {{ card.sentences }} 句{% if card.last_practised %} · 上次 {{ card.last_practised }}{% endif %}</p>
      {% elif card.status == 'failed' %}
        <p class="card-meta card-error">{{ card.error }}</p>
      {% else %}
        <p class="card-meta">正在导入：<span class="card-step">{{ card.step }}</span></p>
      {% endif %}
    </div>
    <div class="card-actions">
      {% if card.status == 'ready' %}
        {% if card.current %}<span class="badge">正在练</span>
        {% else %}<a class="button" href="/sources/{{ card.id }}">{{ '切到这份' if card.practised else '开始练' }}</a>{% endif %}
        <button type="button" data-action="delete">删除</button>
      {% elif card.status == 'failed' %}
        <button type="button" data-action="retry">重试</button>
        <button type="button" data-action="delete">删除</button>
      {% endif %}
    </div>
  </li>
  {% endfor %}
</ul>
{% endblock %}
```

`library.js`：

```js
// 素材库：导入、看进度、重试、删除。
(() => {
  const form = document.getElementById("import-form");
  const list = document.getElementById("cards");
  if (!form || !list) return;
  const note = document.getElementById("import-note");
  const POLL_MS = 2000;
  const busy = (status) => status !== "ready" && status !== "failed";
  const cards = () => [...list.querySelectorAll(".card")];

  async function send(url, options) {
    const response = await fetch(url, options);
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `没做成（${response.status}）`);
    return body;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button");
    button.disabled = true;
    try {
      await send("/api/sources", { method: "POST", body: new FormData(form) });
      window.location.reload();
    } catch (err) {
      note.textContent = err.message;
      note.classList.add("error");
      button.disabled = false;
    }
  });

  list.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const card = button.closest(".card");
    try {
      if (button.dataset.action === "retry") {
        await send(`/api/sources/${card.dataset.id}/retry`, { method: "POST" });
      } else {
        const title = card.querySelector(".card-title").textContent.trim();
        const { sentences, rounds, takes } = card.dataset;
        const sure = window.confirm(
          `删除「${title}」？\n\n${sentences} 个句子、${rounds} 轮练习记录、${takes} 遍录音会全部删掉，不能恢复。`
          + "\n打卡格子和连续天数会保留。");
        if (!sure) return;
        await send(`/api/sources/${card.dataset.id}`, { method: "DELETE" });
      }
      window.location.reload();
    } catch (err) {
      window.alert(err.message);
    }
  });

  // 导入中的卡片每两秒看一眼：还在导入就只换步骤名，导完或失败了整页重画
  async function poll() {
    try {
      const { sources } = await send("/api/sources", { cache: "no-store" });
      const changed = sources.length !== cards().length || sources.some((source) => {
        const card = list.querySelector(`.card[data-id="${source.id}"]`);
        if (!card) return true;
        if (busy(card.dataset.status) && busy(source.status)) {
          card.dataset.status = source.status;
          card.querySelector(".card-step").textContent = source.step;
          return false;
        }
        return card.dataset.status !== source.status;
      });
      if (changed) {
        window.location.reload();
        return;
      }
    } catch (err) {
      // 服务断了由顶上的指示灯提示，这里接着等
    }
    if (cards().some((card) => busy(card.dataset.status))) setTimeout(poll, POLL_MS);
  }
  if (cards().some((card) => busy(card.dataset.status))) setTimeout(poll, POLL_MS);
})();
```

`app.css` 末尾加：

```css
/* 素材库 */
.nav { color: var(--muted); text-decoration: none; font-size: 13px;
  border: 1px solid var(--line); border-radius: 7px; padding: 1px 10px; }
.nav:hover { color: var(--accent); border-color: var(--accent); }
.crumb a { color: inherit; text-decoration: underline dotted; text-underline-offset: 3px; }
.source-head { display: grid; gap: 2px; min-width: 0; }
.source-head h1 { margin: 0; overflow-wrap: anywhere; }
.source-meta { margin: 0; color: var(--muted); font-size: 13px; }
.import-form { display: flex; gap: 8px; margin-bottom: 6px; }
.import-form input { flex: 1; min-width: 0; font: inherit; padding: 7px 10px;
  border: 1px solid var(--line); border-radius: 7px; background: var(--card); color: var(--fg); }
.hint.error { color: var(--warn); }
.cards { list-style: none; padding: 0; margin: 20px 0 0; display: grid; gap: 10px; }
.card { display: flex; gap: 16px; align-items: center; justify-content: space-between;
  background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; }
.card.current { border-color: var(--accent); }
.card-main { min-width: 0; display: grid; gap: 2px; }
.card-title { margin: 0; font-weight: 600; overflow-wrap: anywhere; }
.card-meta { margin: 0; color: var(--muted); font-size: 13px; }
.card-error { color: var(--warn); white-space: pre-wrap; max-height: 7em; overflow: auto; }
.card-actions { display: flex; gap: 8px; align-items: center; flex: none; }
a.button { font: inherit; font-size: 14px; padding: 7px 14px; border: 1px solid var(--line);
  border-radius: 7px; color: var(--fg); text-decoration: none; }
a.button:hover { border-color: var(--accent); }
.badge { font-size: 13px; color: var(--accent); }
@media (max-width: 640px) {
  .card { flex-direction: column; align-items: stretch; }
}
```

- [ ] **Step 4: 跑全部测试，确认通过**

Run: `uv run pytest -q -p no:warnings`
Expected: 全部 PASS

- [ ] **Step 5: 提交** `feat: 素材库页面——网页导入、看进度、重试、删除`

---

### Task 8: 真机验证

- [ ] **Step 1:** 用独立数据目录起一个预览服务（不碰真实练习数据）：`SHADOW_DATA_DIR=<scratchpad>/lib-check uv run shadow serve --port 8765 --no-reload`
- [ ] **Step 2:** 浏览器打开 `/`，应跳到素材库并显示空状态；贴 `https://example.com/not-a-video`，卡片应出现「正在导入」，几秒后变成失败并显示 yt-dlp 的原始错误，「重试」「删除」可用
- [ ] **Step 3:** 用 Python 往这个数据目录塞两份可练的素材，打开各自列表页，确认句子、编号、「开始下一句」互不串；顶栏入口、练习页素材名链接可用；删除一份后打卡格子不变
- [ ] **Step 4:** 手机宽度（375px）下看一眼素材库卡片不溢出
- [ ] **Step 5:** 停掉预览服务；汇报
