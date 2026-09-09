# Shadow 命令行内核（M1 + M2）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个命令行工具，能从 URL 导入英语素材并自动切成 30-90 秒训练片段（M1），并能对比原声与用户跟读录音、生成三面板韵律反馈图（M2）。

**Architecture:** Python 可安装包 `src/shadow`。纯函数模块（`segmenter` / `blanks` / `diff` / `align` / `timing` / `prosody`）与外部依赖封装（`downloader` / `transcriber` / `media`）严格分离，前者可脱离环境单测。SQLite 存元数据，音频存 `~/.shadow/audio`。反馈链路不使用帧级 DTW：词级 diff 的匹配结果即词对齐，据此做分段线性时间弯折。

**Tech Stack:** Python 3.13 / uv / mlx-whisper (`large-v3-turbo`) / praat-parselmouth / numpy / soundfile / matplotlib / cmudict / pytest；外部 CLI：`yt-dlp`、`ffmpeg`。

**参考设计文档:** `docs/superpowers/specs/2026-09-09-english-shadowing-design.md`

**本计划不覆盖:** M3（FastAPI）、M4（React 前端）、M5（打磨）。M2 是核心假设验证点，其结论可能推翻反馈方案，故后续里程碑待 M2 验证后再规划。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `pyproject.toml` | 依赖、`shadow` 命令入口、pytest 配置 |
| `src/shadow/config.py` | 全部路径与常量。路径以函数暴露并读 `SHADOW_DATA_DIR`，使测试可隔离 |
| `src/shadow/models.py` | `Word` / `Segment` 不可变数据类 + JSON 序列化 |
| `src/shadow/db.py` | SQLite schema 与全部读写函数 |
| `src/shadow/media.py` | ffmpeg 封装：片段裁剪、格式统一 |
| `src/shadow/ingest/downloader.py` | yt-dlp 封装：URL 校验、元信息探测、音频下载 |
| `src/shadow/ingest/transcriber.py` | mlx-whisper 封装：wav → 词级时间戳 |
| `src/shadow/ingest/segmenter.py` | **纯函数**：词序列 → 片段（停顿处切） |
| `src/shadow/ingest/pipeline.py` | 导入流程编排 + 状态机 |
| `src/shadow/drill/blanks.py` | **纯函数**：挖空选词 |
| `src/shadow/analysis/prosody.py` | 音频 → 半音归一化音高 + 归一化能量 |
| `src/shadow/analysis/diff.py` | **纯函数**：词级 diff + 匹配对 |
| `src/shadow/analysis/align.py` | **纯函数**：词锚点分段线性时间弯折 |
| `src/shadow/analysis/timing.py` | **纯函数**：每词时长比值 |
| `src/shadow/report/plot.py` | 三面板 matplotlib 图 |
| `src/shadow/cli.py` | `import` / `list` / `export` / `compare` 四个子命令 |

---

### Task 0: 项目骨架与依赖

**Files:**
- Create: `pyproject.toml`
- Create: `src/shadow/__init__.py`, `src/shadow/ingest/__init__.py`, `src/shadow/drill/__init__.py`, `src/shadow/analysis/__init__.py`, `src/shadow/report/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: 安装外部 CLI 依赖**

```bash
brew install ffmpeg yt-dlp
```

验证：`ffmpeg -version | head -1` 与 `yt-dlp --version` 均有输出。

- [ ] **Step 2: 创建 `pyproject.toml`**

```toml
[project]
name = "shadow"
version = "0.1.0"
description = "English shadowing trainer - CLI core"
requires-python = ">=3.12"
dependencies = [
    "mlx-whisper>=0.4.0",
    "praat-parselmouth>=0.4.5",
    "numpy>=1.26",
    "soundfile>=0.12",
    "matplotlib>=3.8",
    "cmudict>=1.0",
]

[project.scripts]
shadow = "shadow.cli:main"

[dependency-groups]
dev = ["pytest>=8.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/shadow"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 3: 创建包目录与空 `__init__.py`**

```bash
mkdir -p src/shadow/ingest src/shadow/drill src/shadow/analysis src/shadow/report tests
touch src/shadow/__init__.py src/shadow/ingest/__init__.py src/shadow/drill/__init__.py \
      src/shadow/analysis/__init__.py src/shadow/report/__init__.py tests/__init__.py
```

- [ ] **Step 4: 安装并验证**

Run: `uv sync && uv run python -c "import parselmouth, numpy, soundfile, matplotlib, cmudict; print('ok')"`
Expected: 打印 `ok`。

若 `mlx-whisper` 安装失败，先确认在 Apple Silicon 上；本任务其余部分不依赖它。

Run: `uv run pytest`
Expected: `no tests ran`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock src tests
git commit -m "chore: 项目骨架与依赖"
```

---

### Task 1: config.py — 路径与常量

**Files:**
- Create: `src/shadow/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_config.py
from shadow import config


def test_data_dir_honours_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path))
    assert config.data_dir() == tmp_path
    assert config.db_path() == tmp_path / "shadow.db"
    assert config.source_audio_dir() == tmp_path / "audio" / "sources"


def test_ensure_dirs_creates_whole_tree(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path))
    config.ensure_dirs()
    assert config.source_audio_dir().is_dir()
    assert config.attempt_audio_dir().is_dir()
    assert config.segment_audio_dir().is_dir()


def test_segment_bounds_are_sane():
    assert config.SEGMENT_MIN_SEC < config.SEGMENT_MAX_SEC
    assert 0 < config.PAUSE_GAP_SEC < 2.0
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/test_config.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'shadow.config'`

- [ ] **Step 3: 实现**

```python
# src/shadow/config.py
"""集中管理路径与常量。

路径以函数形式暴露而非模块级常量，这样测试可以通过 monkeypatch 环境变量隔离数据目录，
不会污染用户真实的 ~/.shadow。
"""

from __future__ import annotations

import os
from pathlib import Path

# --- 转写 ---
WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
WHISPER_LANGUAGE = "en"
SAMPLE_RATE = 16_000

# --- 导入约束 ---
MAX_SOURCE_MINUTES = 60.0

# --- 切片 ---
SEGMENT_MIN_SEC = 30.0
SEGMENT_MAX_SEC = 90.0
PAUSE_GAP_SEC = 0.4

# --- 挖空 ---
BLANK_RATIO_MAX = 0.15
BLANK_MIN = 3
BLANK_MAX = 12
WEAK_RATIO_STRICT = 0.6
WEAK_RATIO_RELAXED = 0.8

# --- 韵律分析 ---
FRAME_STEP_SEC = 0.01
ENERGY_WINDOW_SEC = 0.025
PITCH_FLOOR_HZ = 75.0
PITCH_CEILING_HZ = 500.0

# --- 录音校验 ---
MIN_ATTEMPT_SEC = 1.0
MIN_ATTEMPT_RMS_DB = -50.0


def data_dir() -> Path:
    return Path(os.environ.get("SHADOW_DATA_DIR", Path.home() / ".shadow"))


def db_path() -> Path:
    return data_dir() / "shadow.db"


def source_audio_dir() -> Path:
    return data_dir() / "audio" / "sources"


def segment_audio_dir() -> Path:
    return data_dir() / "audio" / "segments"


def attempt_audio_dir() -> Path:
    return data_dir() / "audio" / "attempts"


def ensure_dirs() -> None:
    for directory in (
        data_dir(),
        source_audio_dir(),
        segment_audio_dir(),
        attempt_audio_dir(),
    ):
        directory.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/test_config.py`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/shadow/config.py tests/test_config.py
git commit -m "feat: 路径与常量配置"
```

---

### Task 2: models.py — 不可变数据类

**Files:**
- Create: `src/shadow/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_models.py
import dataclasses

import pytest

from shadow.models import Segment, Word, with_blanks, words_from_json, words_to_json


def test_word_is_immutable():
    word = Word(text="the", start=1.0, end=1.1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        word.text = "a"


def test_word_duration():
    assert Word(text="the", start=1.0, end=1.25).duration == pytest.approx(0.25)


def test_segment_text_joins_words():
    words = (Word("I", 0.0, 0.1), Word("am", 0.1, 0.3), Word("here", 0.3, 0.6))
    segment = Segment(idx=0, start=0.0, end=0.6, words=words)
    assert segment.text == "I am here"
    assert segment.duration == pytest.approx(0.6)


def test_words_json_roundtrip():
    words = (Word("I", 0.0, 0.1), Word("am", 0.1, 0.3, is_blank=True))
    assert words_from_json(words_to_json(words)) == words


def test_with_blanks_returns_new_tuple_and_leaves_original_untouched():
    words = (Word("I", 0.0, 0.1), Word("am", 0.1, 0.3), Word("here", 0.3, 0.6))
    marked = with_blanks(words, (1,))
    assert [w.is_blank for w in marked] == [False, True, False]
    assert [w.is_blank for w in words] == [False, False, False]
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/test_models.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'shadow.models'`

- [ ] **Step 3: 实现**

```python
# src/shadow/models.py
"""核心数据类型。全部 frozen——记录只追加不修改，练习历史天然可回溯。"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Iterable, Sequence


@dataclass(frozen=True, slots=True)
class Word:
    text: str
    start: float
    end: float
    is_blank: bool = False

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True, slots=True)
class Segment:
    idx: int
    start: float
    end: float
    words: tuple[Word, ...]

    @property
    def text(self) -> str:
        return " ".join(word.text for word in self.words)

    @property
    def duration(self) -> float:
        return self.end - self.start


def words_to_json(words: Sequence[Word]) -> str:
    payload = [
        {"text": w.text, "start": w.start, "end": w.end, "is_blank": w.is_blank}
        for w in words
    ]
    return json.dumps(payload, ensure_ascii=False)


def words_from_json(raw: str) -> tuple[Word, ...]:
    return tuple(
        Word(
            text=item["text"],
            start=float(item["start"]),
            end=float(item["end"]),
            is_blank=bool(item.get("is_blank", False)),
        )
        for item in json.loads(raw)
    )


def with_blanks(words: Sequence[Word], indices: Iterable[int]) -> tuple[Word, ...]:
    """返回标记了挖空位的新词序列，不修改入参。"""
    marked = frozenset(indices)
    return tuple(
        replace(word, is_blank=index in marked) for index, word in enumerate(words)
    )
```

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/test_models.py`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/shadow/models.py tests/test_models.py
git commit -m "feat: 不可变数据类 Word / Segment"
```

---

### Task 3: db.py — SQLite schema 与读写

**Files:**
- Create: `src/shadow/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_db.py
import pytest

from shadow import db
from shadow.models import Segment, Word


@pytest.fixture()
def conn(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path))
    connection = db.connect()
    db.init_db(connection)
    yield connection
    connection.close()


def test_create_and_read_source(conn):
    source_id = db.create_source(conn, url="https://x/y", title="T", duration_sec=120.0)
    row = db.get_source(conn, source_id)
    assert row["title"] == "T"
    assert row["status"] == db.STATUS_PENDING
    assert row["error"] is None


def test_status_transitions_and_failure(conn):
    source_id = db.create_source(conn, url="https://x/y", title="T", duration_sec=1.0)
    db.set_source_status(conn, source_id, db.STATUS_TRANSCRIBING)
    assert db.get_source(conn, source_id)["status"] == db.STATUS_TRANSCRIBING
    db.fail_source(conn, source_id, "boom")
    row = db.get_source(conn, source_id)
    assert row["status"] == db.STATUS_FAILED
    assert row["error"] == "boom"


def test_insert_and_list_segments(conn):
    source_id = db.create_source(conn, url="https://x/y", title="T", duration_sec=60.0)
    segments = (
        Segment(idx=0, start=0.0, end=1.0, words=(Word("hi", 0.0, 1.0, is_blank=True),)),
    )
    db.insert_segments(conn, source_id, segments)
    listed = db.list_segments(conn, source_id)
    assert len(listed) == 1
    assert listed[0]["text"] == "hi"
    stored = db.get_segment(conn, listed[0]["id"])
    assert stored["words"][0].is_blank is True


def test_reset_stale_sources_marks_non_terminal_as_failed(conn):
    stuck = db.create_source(conn, url="https://x/1", title="A", duration_sec=1.0)
    db.set_source_status(conn, stuck, db.STATUS_DOWNLOADING)
    done = db.create_source(conn, url="https://x/2", title="B", duration_sec=1.0)
    db.finish_source(conn, done, audio_path="/tmp/a.wav")

    db.reset_stale_sources(conn)

    assert db.get_source(conn, stuck)["status"] == db.STATUS_FAILED
    assert db.get_source(conn, done)["status"] == db.STATUS_READY
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/test_db.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'shadow.db'`

- [ ] **Step 3: 实现**

```python
# src/shadow/db.py
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
```

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/test_db.py`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/shadow/db.py tests/test_db.py
git commit -m "feat: SQLite 存储层"
```

---

### Task 4: ingest/segmenter.py — 词序列切成片段（纯函数）

**Files:**
- Create: `src/shadow/ingest/segmenter.py`
- Test: `tests/test_segmenter.py`

切片规则：在**停顿处**切。累积时长达到 `min_sec` 后，遇到的第一个 >= `pause_gap` 的词间间隔即为切点；若一路无停顿导致时长达到 `max_sec`，则硬切。末段不足 `min_sec` 时并入前一段。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_segmenter.py
import pytest

from shadow.ingest.segmenter import split_into_segments
from shadow.models import Word

MIN, MAX, GAP = 30.0, 90.0, 0.4


def make_words(count, *, dur=0.5, gaps=None):
    """构造等长词序列；gaps 形如 {index: 该词之后的停顿秒数}。"""
    gaps = gaps or {}
    words, t = [], 0.0
    for i in range(count):
        words.append(Word(text=f"w{i}", start=t, end=t + dur))
        t += dur + gaps.get(i, 0.0)
    return tuple(words)


def split(words):
    return split_into_segments(words, min_sec=MIN, max_sec=MAX, pause_gap=GAP)


def test_empty_input_returns_empty():
    assert split(()) == ()


def test_short_input_yields_one_segment_even_below_min():
    segments = split(make_words(10))
    assert len(segments) == 1
    assert segments[0].idx == 0
    assert len(segments[0].words) == 10


def test_hard_cut_at_max_when_no_pause_exists():
    # 300 词 x 0.5s = 150s，全程无停顿
    segments = split(make_words(300))
    assert len(segments) == 2
    assert segments[0].duration == pytest.approx(90.0)
    assert segments[1].duration == pytest.approx(60.0)


def test_cuts_at_pause_rather_than_running_to_max():
    # 160 词 x 0.5s，第 79 词后有 0.5s 停顿 -> 应在 40s 处切，而不是拖到 90s
    segments = split(make_words(160, gaps={79: 0.5}))
    assert len(segments) == 2
    assert segments[0].duration == pytest.approx(40.0)
    assert segments[0].words[-1].text == "w79"


def test_short_tail_is_merged_into_previous_segment():
    # 停顿后只剩 10s，不足 min，应并回前段
    segments = split(make_words(100, gaps={79: 0.5}))
    assert len(segments) == 1
    assert segments[0].duration == pytest.approx(50.5)


def test_segment_indices_are_sequential_and_bounds_match_words():
    segments = split(make_words(300))
    assert [s.idx for s in segments] == [0, 1]
    for segment in segments:
        assert segment.start == segment.words[0].start
        assert segment.end == segment.words[-1].end
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/test_segmenter.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'shadow.ingest.segmenter'`

- [ ] **Step 3: 实现**

```python
# src/shadow/ingest/segmenter.py
"""把词级时间戳切成训练片段。纯函数，无 IO。"""

from __future__ import annotations

from typing import Sequence

from .. import config
from ..models import Segment, Word


def split_into_segments(
    words: Sequence[Word],
    *,
    min_sec: float = config.SEGMENT_MIN_SEC,
    max_sec: float = config.SEGMENT_MAX_SEC,
    pause_gap: float = config.PAUSE_GAP_SEC,
) -> tuple[Segment, ...]:
    if not words:
        return ()

    spans: list[tuple[int, int]] = []
    start = 0
    total = len(words)

    for i in range(total):
        duration = words[i].end - words[start].start
        gap_after = (
            words[i + 1].start - words[i].end if i + 1 < total else float("inf")
        )
        reached_pause = duration >= min_sec and gap_after >= pause_gap
        overflowed = duration >= max_sec
        if reached_pause or overflowed:
            spans.append((start, i))
            start = i + 1

    if start < total:
        spans.append((start, total - 1))

    if len(spans) >= 2:
        tail_start, tail_end = spans[-1]
        if words[tail_end].end - words[tail_start].start < min_sec:
            prev_start, _ = spans[-2]
            spans = spans[:-2] + [(prev_start, tail_end)]

    return tuple(
        Segment(
            idx=index,
            start=words[begin].start,
            end=words[end].end,
            words=tuple(words[begin : end + 1]),
        )
        for index, (begin, end) in enumerate(spans)
    )
```

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/test_segmenter.py`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/shadow/ingest/segmenter.py tests/test_segmenter.py
git commit -m "feat: 按停顿切分训练片段"
```

---

### Task 5: drill/blanks.py — 挖空选词（纯函数）

**Files:**
- Create: `src/shadow/drill/blanks.py`
- Test: `tests/test_blanks.py`

选词规则：`功能词表` ∩ `弱读比值 < 阈值`。弱读比值 = `词时长 / (音节数 x 片段平均每音节时长)`，越小说明被吞得越狠。按比值升序取，数量受 `15%` 比例与 `[3, 12]` 上下限约束；候选不足 3 个时把阈值从 0.6 放宽到 0.8。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_blanks.py
from shadow.drill.blanks import count_syllables, select_blanks, weak_ratios
from shadow.models import Word

FUNC = {"i", "would", "have", "to", "the", "but", "it", "was", "and", "had", "no",
        "for", "that"}

TEXTS = ["I", "would", "have", "gone", "to", "the", "market", "but", "it", "was",
         "closed", "and", "I", "had", "no", "time", "for", "that", "today", "anyway"]


def build_words(texts=TEXTS, *, func_dur=0.06, content_dur=0.45):
    words, t = [], 0.0
    for text in texts:
        duration = func_dur if text.lower() in FUNC else content_dur
        words.append(Word(text=text, start=t, end=t + duration))
        t += duration
    return tuple(words)


def test_count_syllables_uses_cmudict():
    assert count_syllables("the") == 1
    assert count_syllables("banana") == 3
    assert count_syllables("beautiful") == 3


def test_count_syllables_falls_back_for_unknown_words():
    assert count_syllables("zblorptrix") >= 1
    assert count_syllables("") == 1


def test_weak_ratios_are_lower_for_swallowed_words():
    words = build_words()
    ratios = weak_ratios(words)
    assert ratios[TEXTS.index("have")] < 0.6
    assert ratios[TEXTS.index("market")] > 1.0


def test_select_blanks_picks_only_swallowed_function_words():
    picked = select_blanks(build_words())
    assert len(picked) >= 3
    assert all(TEXTS[i].lower() in FUNC for i in picked)
    assert list(picked) == sorted(picked)


def test_select_blanks_respects_ratio_cap():
    # 20 词 -> int(20 * 0.15) = 3，下限也是 3
    assert len(select_blanks(build_words())) == 3


def test_select_blanks_caps_at_twelve_for_long_segments():
    words = build_words(TEXTS * 10)  # 200 词
    assert len(select_blanks(words)) == 12


def test_select_blanks_handles_empty_input():
    assert select_blanks(()) == ()
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/test_blanks.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'shadow.drill.blanks'`

- [ ] **Step 3: 实现**

```python
# src/shadow/drill/blanks.py
"""挖空选词。纯函数，无 IO。

不挖生词，专挖被弱读的功能词——用户听不懂的从来不是大词，而是
"should have been" 被读成 "shoulda bin"。
"""

from __future__ import annotations

import functools
import re
from typing import Sequence

from .. import config
from ..models import Word

FUNCTION_WORDS = frozenset(
    """
    a an the of to in for on at by with from as into onto over under about
    and or but nor so yet if then than when while because though although
    is are was were be been being am do does did done have has had having
    can could shall should will would may might must ought
    i you he she it we they me him her us them
    my your his its our their mine yours hers ours theirs
    this that these those there here what which who whom whose
    not no none nor up out off down just very too also only even still
    """.split()
)

_VOWEL_GROUPS = re.compile(r"[aeiouy]+")
_NON_WORD = re.compile(r"[^a-z']")


@functools.lru_cache(maxsize=1)
def _cmu() -> dict[str, list[list[str]]]:
    import cmudict

    return cmudict.dict()


def normalise(text: str) -> str:
    return _NON_WORD.sub("", text.lower())


def count_syllables(word: str) -> int:
    key = normalise(word)
    if not key:
        return 1
    entries = _cmu().get(key)
    if entries:
        counted = sum(1 for phone in entries[0] if phone[-1].isdigit())
        if counted:
            return counted
    groups = len(_VOWEL_GROUPS.findall(key))
    if key.endswith("e") and groups > 1:
        groups -= 1
    return max(1, groups)


def weak_ratios(words: Sequence[Word]) -> tuple[float, ...]:
    """每个词的弱读比值：实际时长相对于「该词音节数 x 平均每音节时长」的倍数。"""
    if not words:
        return ()
    syllables = [count_syllables(word.text) for word in words]
    total_duration = sum(word.duration for word in words)
    total_syllables = sum(syllables) or 1
    baseline = total_duration / total_syllables
    if baseline <= 0:
        return tuple(1.0 for _ in words)
    return tuple(
        word.duration / (count * baseline)
        for word, count in zip(words, syllables)
    )


def select_blanks(
    words: Sequence[Word],
    *,
    ratio_max: float = config.BLANK_RATIO_MAX,
    min_blanks: int = config.BLANK_MIN,
    max_blanks: int = config.BLANK_MAX,
    strict: float = config.WEAK_RATIO_STRICT,
    relaxed: float = config.WEAK_RATIO_RELAXED,
) -> tuple[int, ...]:
    if not words:
        return ()

    ratios = weak_ratios(words)
    cap = max(min_blanks, min(max_blanks, int(len(words) * ratio_max)))
    cap = min(cap, len(words))

    def candidates(threshold: float) -> list[int]:
        picked = [
            index
            for index, word in enumerate(words)
            if normalise(word.text) in FUNCTION_WORDS and ratios[index] < threshold
        ]
        picked.sort(key=lambda index: ratios[index])
        return picked

    chosen = candidates(strict)
    if len(chosen) < min_blanks:
        chosen = candidates(relaxed)

    return tuple(sorted(chosen[:cap]))
```

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/test_blanks.py`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/shadow/drill/blanks.py tests/test_blanks.py
git commit -m "feat: 挖空选词（功能词 x 弱读比值）"
```

---

### Task 6: ingest/downloader.py — yt-dlp 封装

**Files:**
- Create: `src/shadow/ingest/downloader.py`
- Test: `tests/test_downloader.py`

**关键约束：** yt-dlp 失败时把原始 stderr 原样带出。包装成通用「导入失败」等于扔掉唯一有用的诊断信息。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_downloader.py
import subprocess

import pytest

from shadow.ingest import downloader
from shadow.ingest.downloader import DownloadError


class FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_validate_url_accepts_https():
    assert downloader.validate_url("  https://example.com/v?id=1 ") == (
        "https://example.com/v?id=1"
    )


@pytest.mark.parametrize("bad", ["file:///etc/passwd", "javascript:alert(1)",
                                 "ftp://x/y", "not a url", ""])
def test_validate_url_rejects_non_http(bad):
    with pytest.raises(DownloadError):
        downloader.validate_url(bad)


def test_probe_returns_title_and_duration(monkeypatch):
    monkeypatch.setattr(
        downloader.subprocess, "run",
        lambda *a, **k: FakeProc(stdout="Some Talk\n742.5\n"),
    )
    assert downloader.probe("https://x/y") == ("Some Talk", 742.5)


def test_probe_surfaces_raw_stderr(monkeypatch):
    monkeypatch.setattr(
        downloader.subprocess, "run",
        lambda *a, **k: FakeProc(returncode=1, stderr="ERROR: Video unavailable"),
    )
    with pytest.raises(DownloadError, match="Video unavailable"):
        downloader.probe("https://x/y")


def test_probe_rejects_unparseable_duration(monkeypatch):
    monkeypatch.setattr(
        downloader.subprocess, "run",
        lambda *a, **k: FakeProc(stdout="Live Stream\nNA\n"),
    )
    with pytest.raises(DownloadError, match="时长"):
        downloader.probe("https://x/y")


def test_download_audio_invokes_ytdlp_then_ffmpeg(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "yt-dlp":
            raw = tmp_path / "raw.m4a"
            raw.write_bytes(b"x")
            return FakeProc(stdout=f"{raw}\n")
        return FakeProc()

    monkeypatch.setattr(downloader.subprocess, "run", fake_run)
    dest = tmp_path / "out.wav"
    downloader.download_audio("https://x/y", dest, workdir=tmp_path)

    assert calls[0][0] == "yt-dlp"
    assert calls[1][0] == "ffmpeg"
    assert str(dest) in calls[1]
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/test_downloader.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'shadow.ingest.downloader'`

- [ ] **Step 3: 实现**

```python
# src/shadow/ingest/downloader.py
"""yt-dlp / ffmpeg 封装。失败时原样保留外部工具的 stderr。"""

from __future__ import annotations

import subprocess
from pathlib import Path
from urllib.parse import urlparse

from .. import config

ALLOWED_SCHEMES = ("http", "https")


class DownloadError(RuntimeError):
    """下载或探测素材失败。消息中应包含外部工具的原始输出。"""


def validate_url(url: str) -> str:
    cleaned = (url or "").strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in ALLOWED_SCHEMES or not parsed.netloc:
        raise DownloadError(f"只接受 http/https 链接，收到：{url!r}")
    return cleaned


def probe(url: str) -> tuple[str, float]:
    """返回 (标题, 时长秒)。不下载媒体。"""
    proc = subprocess.run(
        [
            "yt-dlp", "--no-playlist", "--skip-download",
            "--print", "%(title)s", "--print", "%(duration)s", url,
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise DownloadError(f"yt-dlp 查询失败：\n{proc.stderr.strip()}")

    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if len(lines) < 2:
        raise DownloadError(f"yt-dlp 未返回完整元信息：\n{proc.stdout.strip()}")

    title = lines[0].strip()
    try:
        duration = float(lines[1].strip())
    except ValueError as exc:
        raise DownloadError(
            f"无法解析素材时长（直播或无时长信息？）：{lines[1]!r}"
        ) from exc
    return title, duration


def download_audio(url: str, dest_wav: Path, *, workdir: Path) -> Path:
    """下载最佳音轨并转成 16k 单声道 wav。"""
    dest_wav.parent.mkdir(parents=True, exist_ok=True)
    workdir.mkdir(parents=True, exist_ok=True)

    fetch = subprocess.run(
        [
            "yt-dlp", "--no-playlist", "-f", "bestaudio",
            "-o", str(workdir / "raw.%(ext)s"),
            "--print", "after_move:filepath", url,
        ],
        capture_output=True,
        text=True,
    )
    if fetch.returncode != 0:
        raise DownloadError(f"yt-dlp 下载失败：\n{fetch.stderr.strip()}")

    raw_lines = [line for line in fetch.stdout.splitlines() if line.strip()]
    if not raw_lines:
        raise DownloadError("yt-dlp 未报告下载后的文件路径")
    raw_path = Path(raw_lines[-1].strip())

    convert = subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(raw_path),
            "-ar", str(config.SAMPLE_RATE), "-ac", "1",
            "-c:a", "pcm_s16le", str(dest_wav),
        ],
        capture_output=True,
        text=True,
    )
    if convert.returncode != 0:
        raise DownloadError(f"ffmpeg 转码失败：\n{convert.stderr.strip()}")
    return dest_wav
```

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/test_downloader.py`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/shadow/ingest/downloader.py tests/test_downloader.py
git commit -m "feat: yt-dlp 音频下载与元信息探测"
```

---

### Task 7: ingest/transcriber.py — mlx-whisper 封装

**Files:**
- Create: `src/shadow/ingest/transcriber.py`
- Test: `tests/test_transcriber.py`

**关键约束：** 回测用户录音必须与转写素材使用**同一个模型**，否则模型自身的识别缺陷会被算到用户头上。因此模型名统一由 `config.WHISPER_MODEL` 提供，调用方不得各自指定。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_transcriber.py
import sys
import types

import pytest

from shadow import config


@pytest.fixture()
def fake_whisper(monkeypatch):
    calls = {}
    module = types.ModuleType("mlx_whisper")

    def transcribe(path, **kwargs):
        calls["path"] = path
        calls["kwargs"] = kwargs
        return {
            "segments": [
                {"words": [
                    {"word": " Should", "start": 0.00, "end": 0.28},
                    {"word": " have", "start": 0.28, "end": 0.34},
                ]},
                {"words": [
                    {"word": " been", "start": 0.34, "end": 0.60},
                    {"word": "   ", "start": 0.60, "end": 0.61},
                ]},
            ]
        }

    module.transcribe = transcribe
    monkeypatch.setitem(sys.modules, "mlx_whisper", module)
    return calls


def test_transcribe_flattens_words_and_drops_blanks(fake_whisper, tmp_path):
    from shadow.ingest.transcriber import transcribe_words

    words = transcribe_words(tmp_path / "a.wav")
    assert [w.text for w in words] == ["Should", "have", "been"]
    assert words[1].start == 0.28


def test_transcribe_pins_model_and_language(fake_whisper, tmp_path):
    from shadow.ingest.transcriber import transcribe_words

    transcribe_words(tmp_path / "a.wav")
    assert fake_whisper["kwargs"]["path_or_hf_repo"] == config.WHISPER_MODEL
    assert fake_whisper["kwargs"]["language"] == config.WHISPER_LANGUAGE
    assert fake_whisper["kwargs"]["word_timestamps"] is True
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/test_transcriber.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'shadow.ingest.transcriber'`

- [ ] **Step 3: 实现**

```python
# src/shadow/ingest/transcriber.py
"""mlx-whisper 封装：音频 -> 词级时间戳。"""

from __future__ import annotations

from pathlib import Path

from .. import config
from ..models import Word


class TranscribeError(RuntimeError):
    pass


def transcribe_words(wav_path: Path) -> tuple[Word, ...]:
    """转写音频，返回扁平的词序列。

    模型固定为 config.WHISPER_MODEL——素材与用户录音必须用同一个模型，
    否则 diff 会把模型缺陷算成用户的发音问题。
    """
    import mlx_whisper

    try:
        result = mlx_whisper.transcribe(
            str(wav_path),
            path_or_hf_repo=config.WHISPER_MODEL,
            language=config.WHISPER_LANGUAGE,
            word_timestamps=True,
        )
    except Exception as exc:  # 模型下载失败、音频损坏等
        raise TranscribeError(f"转写失败（{wav_path}）：{exc}") from exc

    words: list[Word] = []
    for segment in result.get("segments", ()):
        for item in segment.get("words", ()):
            text = str(item.get("word", "")).strip()
            if not text:
                continue
            words.append(
                Word(text=text, start=float(item["start"]), end=float(item["end"]))
            )
    return tuple(words)
```

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/test_transcriber.py`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/shadow/ingest/transcriber.py tests/test_transcriber.py
git commit -m "feat: mlx-whisper 词级转写封装"
```

---

### Task 8: media.py — 片段裁剪与录音校验

**Files:**
- Create: `src/shadow/media.py`
- Test: `tests/test_media.py`

本任务的测试**真实调用 ffmpeg 和 soundfile**（都是本地依赖，无网络），因为裁剪时间点算错是典型的静默 bug，打桩测不出来。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_media.py
import numpy as np
import pytest
import soundfile as sf

from shadow import media
from shadow.media import AudioError


def write_tone(path, *, seconds=3.0, freq=220.0, sr=16000, amplitude=0.5):
    t = np.arange(int(seconds * sr)) / sr
    sf.write(path, (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32), sr)
    return path


def test_cut_segment_produces_expected_duration(tmp_path):
    source = write_tone(tmp_path / "src.wav", seconds=3.0)
    dest = tmp_path / "cut.wav"
    media.cut_segment(source, dest, start=1.0, end=2.0)
    info = sf.info(dest)
    assert info.duration == pytest.approx(1.0, abs=0.05)
    assert info.samplerate == 16000
    assert info.channels == 1


def test_probe_duration_matches(tmp_path):
    source = write_tone(tmp_path / "src.wav", seconds=2.5)
    assert media.probe_duration(source) == pytest.approx(2.5, abs=0.01)


def test_validate_attempt_rejects_too_short(tmp_path):
    source = write_tone(tmp_path / "s.wav", seconds=0.3)
    with pytest.raises(AudioError, match="过短"):
        media.validate_attempt(source)


def test_validate_attempt_rejects_silence(tmp_path):
    source = write_tone(tmp_path / "s.wav", seconds=2.0, amplitude=0.0)
    with pytest.raises(AudioError, match="静音"):
        media.validate_attempt(source)


def test_validate_attempt_accepts_normal_recording(tmp_path):
    source = write_tone(tmp_path / "s.wav", seconds=2.0, amplitude=0.3)
    media.validate_attempt(source)  # 不抛异常即通过
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/test_media.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'shadow.media'`

- [ ] **Step 3: 实现**

```python
# src/shadow/media.py
"""音频文件操作：裁剪、格式统一、录音有效性校验。"""

from __future__ import annotations

import math
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from . import config


class AudioError(RuntimeError):
    pass


def probe_duration(path: Path) -> float:
    return float(sf.info(str(path)).duration)


def cut_segment(source: Path, dest: Path, *, start: float, end: float) -> Path:
    """从 source 裁出 [start, end) 并统一为 16k 单声道 wav。"""
    if end <= start:
        raise AudioError(f"无效的裁剪区间：start={start} end={end}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(source),
            "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
            "-ar", str(config.SAMPLE_RATE), "-ac", "1",
            "-c:a", "pcm_s16le", str(dest),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise AudioError(f"ffmpeg 裁剪失败：\n{proc.stderr.strip()}")
    return dest


def validate_attempt(path: Path) -> None:
    """录音提交前的守门：太短或全静音就地拦下，不浪费一次转写。"""
    duration = probe_duration(path)
    if duration < config.MIN_ATTEMPT_SEC:
        raise AudioError(
            f"录音过短（{duration:.2f}s，至少需要 {config.MIN_ATTEMPT_SEC}s）"
        )
    samples, _ = sf.read(str(path), dtype="float32", always_2d=False)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    rms = float(np.sqrt(np.mean(np.square(samples)))) if samples.size else 0.0
    rms_db = 20.0 * math.log10(rms + 1e-10)
    if rms_db < config.MIN_ATTEMPT_RMS_DB:
        raise AudioError(
            f"录音接近静音（{rms_db:.1f} dB）。检查麦克风是否被静音或选错设备。"
        )
```

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/test_media.py`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/shadow/media.py tests/test_media.py
git commit -m "feat: 音频裁剪与录音有效性校验"
```

---

### Task 9: ingest/pipeline.py — 导入流程编排

**Files:**
- Create: `src/shadow/ingest/pipeline.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_pipeline.py
import pytest

from shadow import db
from shadow.ingest import pipeline
from shadow.ingest.downloader import DownloadError
from shadow.models import Word


@pytest.fixture()
def conn(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path))
    connection = db.connect()
    db.init_db(connection)
    yield connection
    connection.close()


def fake_words():
    """160 词 x 0.5s，第 79 词后有停顿 -> 应切成 2 段。"""
    words, t = [], 0.0
    for i in range(160):
        words.append(Word(text="the" if i % 2 else "market", start=t, end=t + 0.5))
        t += 0.5 + (0.5 if i == 79 else 0.0)
    return tuple(words)


@pytest.fixture()
def stub_externals(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "probe", lambda url: ("Talk", 100.0))
    monkeypatch.setattr(
        pipeline, "download_audio",
        lambda url, dest, workdir: (dest.write_bytes(b"RIFF"), dest)[1],
    )
    monkeypatch.setattr(pipeline, "transcribe_words", lambda path: fake_words())


def test_import_creates_ready_source_with_segments(conn, stub_externals):
    source_id = pipeline.import_source("https://x/y", conn=conn)
    row = db.get_source(conn, source_id)
    assert row["status"] == db.STATUS_READY
    assert row["audio_path"].endswith(f"{source_id}.wav")
    assert len(db.list_segments(conn, source_id)) == 2


def test_import_marks_blanks_on_segments(conn, stub_externals):
    source_id = pipeline.import_source("https://x/y", conn=conn)
    first = db.get_segment(conn, db.list_segments(conn, source_id)[0]["id"])
    assert any(word.is_blank for word in first["words"])


def test_import_rejects_overlong_source(conn, monkeypatch):
    monkeypatch.setattr(pipeline, "probe", lambda url: ("Long", 3601.0))
    with pytest.raises(pipeline.ImportError_, match="60"):
        pipeline.import_source("https://x/y", conn=conn)
    assert db.list_sources(conn) == []


def test_import_records_failure_and_reraises(conn, monkeypatch):
    monkeypatch.setattr(pipeline, "probe", lambda url: ("Talk", 100.0))

    def boom(url, dest, workdir):
        raise DownloadError("ERROR: Video unavailable")

    monkeypatch.setattr(pipeline, "download_audio", boom)

    with pytest.raises(DownloadError):
        pipeline.import_source("https://x/y", conn=conn)

    row = db.list_sources(conn)[0]
    assert row["status"] == db.STATUS_FAILED
    assert "Video unavailable" in row["error"]


def test_import_rejects_bad_url_before_touching_db(conn):
    with pytest.raises(Exception):
        pipeline.import_source("file:///etc/passwd", conn=conn)
    assert db.list_sources(conn) == []
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/test_pipeline.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'shadow.ingest.pipeline'`

- [ ] **Step 3: 实现**

```python
# src/shadow/ingest/pipeline.py
"""导入流程编排：URL -> 音频 -> 转写 -> 切片 -> 挖空 -> 入库。

时长上限在下载之前检查，避免用户等十分钟才发现失败。
任何一步失败都把原始错误写进 sources.error 并原样抛出。
"""

from __future__ import annotations

import sqlite3
import tempfile
from dataclasses import replace
from pathlib import Path

from .. import config, db
from ..drill.blanks import select_blanks
from ..models import Segment, with_blanks
from .downloader import download_audio, probe, validate_url
from .segmenter import split_into_segments
from .transcriber import transcribe_words


class ImportError_(RuntimeError):
    """导入前置校验失败（命名避开内置 ImportError）。"""


def _apply_blanks(segments: tuple[Segment, ...]) -> tuple[Segment, ...]:
    return tuple(
        replace(segment, words=with_blanks(segment.words, select_blanks(segment.words)))
        for segment in segments
    )


def import_source(url: str, *, conn: sqlite3.Connection) -> int:
    clean_url = validate_url(url)
    title, duration = probe(clean_url)

    limit_sec = config.MAX_SOURCE_MINUTES * 60
    if duration > limit_sec:
        raise ImportError_(
            f"素材时长 {duration / 60:.1f} 分钟，超过上限 "
            f"{config.MAX_SOURCE_MINUTES:.0f} 分钟。请改用更短的素材或先自行裁剪。"
        )

    source_id = db.create_source(
        conn, url=clean_url, title=title, duration_sec=duration
    )
    try:
        db.set_source_status(conn, source_id, db.STATUS_DOWNLOADING)
        wav_path = config.source_audio_dir() / f"{source_id}.wav"
        with tempfile.TemporaryDirectory() as workdir:
            download_audio(clean_url, wav_path, workdir=Path(workdir))

        db.set_source_status(conn, source_id, db.STATUS_TRANSCRIBING)
        words = transcribe_words(wav_path)

        db.set_source_status(conn, source_id, db.STATUS_SEGMENTING)
        segments = _apply_blanks(split_into_segments(words))
        db.insert_segments(conn, source_id, segments)

        db.finish_source(conn, source_id, audio_path=str(wav_path))
    except Exception as exc:
        db.fail_source(conn, source_id, str(exc))
        raise
    return source_id
```

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/test_pipeline.py`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/shadow/ingest/pipeline.py tests/test_pipeline.py
git commit -m "feat: 导入流程编排与状态机"
```

---
---

## M2：韵律反馈（核心假设验证点）

以下任务全部为纯函数 + 一个出图入口。**完成后即可在命令行验证「音高对比图是否真有信息量」，此结论决定 M3-M5 是否按原方案进行。**

---

### Task 10: analysis/diff.py — 词级 diff 与匹配对

**Files:**
- Create: `src/shadow/text.py`
- Modify: `src/shadow/drill/blanks.py`（改为从 `text.py` 导入 `normalise`）
- Create: `src/shadow/analysis/diff.py`
- Test: `tests/test_diff.py`

diff 的匹配结果**同时承担两个职责**：既是可懂度反馈，也是后续时间对齐的锚点来源。

- [ ] **Step 1: 抽出共享的文本归一化**

`normalise` 目前在 `drill/blanks.py` 里，而 `analysis/` 不应反向依赖 `drill/`。抽到独立模块：

```python
# src/shadow/text.py
"""文本归一化。比较词是否相同时统一忽略大小写与标点。"""

from __future__ import annotations

import re

_NON_WORD = re.compile(r"[^a-z']")


def normalise(text: str) -> str:
    return _NON_WORD.sub("", text.lower())
```

修改 `src/shadow/drill/blanks.py`：删除其中的 `_NON_WORD` 与 `normalise` 定义，改为在文件顶部导入：

```python
from ..text import normalise
```

Run: `uv run pytest tests/test_blanks.py`
Expected: 7 passed（重构不改行为）

- [ ] **Step 2: 写失败测试**

```python
# tests/test_diff.py
import pytest

from shadow.analysis.diff import accuracy, diff_words, matched_pairs

REF = ["Should", "have", "been", "there", "earlier"]


def kinds(tokens):
    return [token.kind for token in tokens]


def test_identical_sequences_are_all_equal():
    tokens = diff_words(REF, list(REF))
    assert kinds(tokens) == ["equal"] * 5
    assert accuracy(tokens) == pytest.approx(1.0)


def test_case_and_punctuation_are_ignored():
    tokens = diff_words(["Should,", "have."], ["should", "HAVE"])
    assert kinds(tokens) == ["equal", "equal"]


def test_dropped_word_is_reported_missing():
    tokens = diff_words(REF, ["Should", "been", "there", "earlier"])
    assert "missing" in kinds(tokens)
    missing = [t for t in tokens if t.kind == "missing"]
    assert missing[0].ref_text == "have"
    assert missing[0].usr_index is None


def test_substituted_word_is_reported_wrong():
    tokens = diff_words(REF, ["Should", "half", "been", "there", "earlier"])
    wrong = [t for t in tokens if t.kind == "wrong"]
    assert wrong and wrong[0].ref_text == "have" and wrong[0].usr_text == "half"


def test_inserted_word_is_reported_extra():
    tokens = diff_words(REF, ["Should", "have", "uh", "been", "there", "earlier"])
    extra = [t for t in tokens if t.kind == "extra"]
    assert extra and extra[0].usr_text == "uh"
    assert extra[0].ref_index is None


def test_matched_pairs_are_index_pairs_of_equal_tokens():
    tokens = diff_words(REF, ["Should", "half", "been", "there", "earlier"])
    pairs = matched_pairs(tokens)
    assert (0, 0) in pairs and (2, 2) in pairs
    assert all(isinstance(r, int) and isinstance(u, int) for r, u in pairs)


def test_accuracy_counts_reference_words_only():
    tokens = diff_words(REF, ["Should", "been", "there", "earlier"])
    assert accuracy(tokens) == pytest.approx(4 / 5)


def test_empty_user_transcript_yields_zero_accuracy():
    tokens = diff_words(REF, [])
    assert kinds(tokens) == ["missing"] * 5
    assert accuracy(tokens) == pytest.approx(0.0)
```

- [ ] **Step 3: 运行，确认失败**

Run: `uv run pytest tests/test_diff.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'shadow.analysis.diff'`

- [ ] **Step 4: 实现**

```python
# src/shadow/analysis/diff.py
"""原文与用户转写的词级 diff。纯函数，无 IO。

equal 类型的 token 同时是时间对齐的锚点来源——这就是本设计不需要帧级 DTW 的原因。
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Sequence

from ..text import normalise

KIND_EQUAL = "equal"
KIND_WRONG = "wrong"
KIND_MISSING = "missing"
KIND_EXTRA = "extra"


@dataclass(frozen=True, slots=True)
class DiffToken:
    kind: str
    ref_index: int | None
    usr_index: int | None
    ref_text: str
    usr_text: str


def diff_words(
    ref_texts: Sequence[str], usr_texts: Sequence[str]
) -> tuple[DiffToken, ...]:
    ref_norm = [normalise(text) for text in ref_texts]
    usr_norm = [normalise(text) for text in usr_texts]
    matcher = SequenceMatcher(a=ref_norm, b=usr_norm, autojunk=False)

    tokens: list[DiffToken] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                ref_i, usr_j = i1 + offset, j1 + offset
                tokens.append(
                    DiffToken(KIND_EQUAL, ref_i, usr_j,
                              ref_texts[ref_i], usr_texts[usr_j])
                )
        elif tag == "replace":
            for offset in range(max(i2 - i1, j2 - j1)):
                ref_i = i1 + offset if i1 + offset < i2 else None
                usr_j = j1 + offset if j1 + offset < j2 else None
                if ref_i is None:
                    tokens.append(
                        DiffToken(KIND_EXTRA, None, usr_j, "", usr_texts[usr_j])
                    )
                elif usr_j is None:
                    tokens.append(
                        DiffToken(KIND_MISSING, ref_i, None, ref_texts[ref_i], "")
                    )
                else:
                    tokens.append(
                        DiffToken(KIND_WRONG, ref_i, usr_j,
                                  ref_texts[ref_i], usr_texts[usr_j])
                    )
        elif tag == "delete":
            for ref_i in range(i1, i2):
                tokens.append(
                    DiffToken(KIND_MISSING, ref_i, None, ref_texts[ref_i], "")
                )
        elif tag == "insert":
            for usr_j in range(j1, j2):
                tokens.append(
                    DiffToken(KIND_EXTRA, None, usr_j, "", usr_texts[usr_j])
                )
    return tuple(tokens)


def matched_pairs(tokens: Sequence[DiffToken]) -> tuple[tuple[int, int], ...]:
    """时间对齐锚点：(原文词下标, 用户词下标)。"""
    return tuple(
        (token.ref_index, token.usr_index)
        for token in tokens
        if token.kind == KIND_EQUAL
        and token.ref_index is not None
        and token.usr_index is not None
    )


def accuracy(tokens: Sequence[DiffToken]) -> float:
    """可懂度：原文里有多少词被机器正确听出来。分母只算原文词。"""
    reference_total = sum(1 for token in tokens if token.ref_index is not None)
    if not reference_total:
        return 0.0
    correct = sum(1 for token in tokens if token.kind == KIND_EQUAL)
    return correct / reference_total
```

- [ ] **Step 5: 运行，确认通过**

Run: `uv run pytest tests/test_diff.py tests/test_blanks.py`
Expected: 15 passed

- [ ] **Step 6: Commit**

```bash
git add src/shadow/text.py src/shadow/drill/blanks.py src/shadow/analysis/diff.py tests/test_diff.py
git commit -m "feat: 词级 diff 与对齐锚点"
```

---

### Task 11: analysis/prosody.py — 半音归一化音高与能量包络

**Files:**
- Create: `src/shadow/analysis/prosody.py`
- Test: `tests/test_prosody.py`

**关键约束：音高必须归一化为半音。** 用户与原声说话人基频可能相差一倍，直接叠加 Hz 曲线两条线离得老远。转成相对各自浊音段中位数的半音数后，比较的才是**相对起伏**。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_prosody.py
import numpy as np
import pytest
import soundfile as sf

from shadow.analysis.prosody import analyse

SR = 16000


def write_tone(path, *, seconds=2.0, freq=220.0, amplitude=0.5):
    t = np.arange(int(seconds * SR)) / SR
    sf.write(path, (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32), SR)
    return path


def write_two_tones(path, *, first=220.0, second=440.0, seconds=1.0, amplitude=0.5):
    t = np.arange(int(seconds * SR)) / SR
    head = amplitude * np.sin(2 * np.pi * first * t)
    tail = amplitude * np.sin(2 * np.pi * second * t)
    sf.write(path, np.concatenate([head, tail]).astype(np.float32), SR)
    return path


def write_two_levels(path, *, seconds=1.0, loud=0.5, quiet=0.25, freq=220.0):
    t = np.arange(int(seconds * SR)) / SR
    head = loud * np.sin(2 * np.pi * freq * t)
    tail = quiet * np.sin(2 * np.pi * freq * t)
    sf.write(path, np.concatenate([head, tail]).astype(np.float32), SR)
    return path


def test_detects_fundamental_frequency(tmp_path):
    result = analyse(write_tone(tmp_path / "a.wav", freq=220.0))
    assert np.nanmedian(result.f0_hz) == pytest.approx(220.0, abs=5.0)


def test_steady_tone_has_flat_semitone_contour(tmp_path):
    result = analyse(write_tone(tmp_path / "a.wav", freq=220.0))
    assert np.nanmax(np.abs(result.semitones)) < 1.0


def test_octave_jump_spans_about_twelve_semitones(tmp_path):
    result = analyse(write_two_tones(tmp_path / "a.wav"))
    span = np.nanmax(result.semitones) - np.nanmin(result.semitones)
    assert span == pytest.approx(12.0, abs=1.5)


def test_semitones_are_speaker_independent(tmp_path):
    """低音与高音说话人唱同样的八度跳跃，归一化后轮廓跨度应一致。"""
    low = analyse(write_two_tones(tmp_path / "low.wav", first=110.0, second=220.0))
    high = analyse(write_two_tones(tmp_path / "high.wav", first=220.0, second=440.0))
    low_span = np.nanmax(low.semitones) - np.nanmin(low.semitones)
    high_span = np.nanmax(high.semitones) - np.nanmin(high.semitones)
    assert low_span == pytest.approx(high_span, abs=1.5)


def test_energy_drop_is_about_six_db(tmp_path):
    result = analyse(write_two_levels(tmp_path / "a.wav"))
    half = len(result.energy_db) // 2
    loud = np.median(result.energy_db[100:half - 100])
    quiet = np.median(result.energy_db[half + 100:-100])
    assert loud - quiet == pytest.approx(6.0, abs=1.5)


def test_all_arrays_share_one_time_grid(tmp_path):
    result = analyse(write_tone(tmp_path / "a.wav", seconds=1.5))
    assert result.times.shape == result.f0_hz.shape == result.semitones.shape
    assert result.times.shape == result.energy_db.shape
    assert result.duration == pytest.approx(1.5, abs=0.05)


def test_silence_yields_no_pitch_but_still_returns_grid(tmp_path):
    result = analyse(write_tone(tmp_path / "a.wav", amplitude=0.0))
    assert np.all(np.isnan(result.semitones))
    assert result.times.size > 0
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/test_prosody.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'shadow.analysis.prosody'`

- [ ] **Step 3: 实现**

```python
# src/shadow/analysis/prosody.py
"""音频 -> 韵律曲线：半音归一化音高 + 归一化能量包络。

归一化是本模块存在的理由。绝对 Hz 无法跨说话人比较（男声约 100 Hz vs 女声约 220 Hz），
转成相对各自浊音段中位数的半音数后，比较的是语调轮廓而非嗓音音高。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import parselmouth

from .. import config


@dataclass(frozen=True, slots=True)
class Prosody:
    times: np.ndarray       # 秒，等间距
    f0_hz: np.ndarray       # 基频，清音处为 nan
    semitones: np.ndarray   # 相对自身中位数的半音数，清音处为 nan
    energy_db: np.ndarray   # 相对自身 95 分位的 dB
    duration: float


def _rms_db(
    samples: np.ndarray, sample_rate: float, times: np.ndarray, window: float
) -> np.ndarray:
    """滑窗 RMS，用平方前缀和做到 O(n)。"""
    squared_prefix = np.concatenate(([0.0], np.cumsum(np.square(samples))))
    half = max(1, int(window * sample_rate / 2))
    centres = np.clip((times * sample_rate).astype(int), 0, max(samples.size - 1, 0))
    lower = np.clip(centres - half, 0, samples.size)
    upper = np.clip(centres + half, 0, samples.size)
    counts = np.maximum(upper - lower, 1)
    rms = np.sqrt((squared_prefix[upper] - squared_prefix[lower]) / counts)
    return 20.0 * np.log10(rms + 1e-10)


def analyse(
    wav_path,
    *,
    step: float = config.FRAME_STEP_SEC,
    pitch_floor: float = config.PITCH_FLOOR_HZ,
    pitch_ceiling: float = config.PITCH_CEILING_HZ,
    energy_window: float = config.ENERGY_WINDOW_SEC,
) -> Prosody:
    sound = parselmouth.Sound(str(wav_path))
    duration = float(sound.get_total_duration())

    times = np.arange(0.0, duration, step)
    if times.size == 0:
        times = np.array([0.0])

    pitch = sound.to_pitch(
        time_step=step, pitch_floor=pitch_floor, pitch_ceiling=pitch_ceiling
    )
    pitch_times = np.asarray(pitch.xs(), dtype=float)
    pitch_values = np.asarray(pitch.selected_array["frequency"], dtype=float)

    if pitch_times.size:
        indices = np.clip(
            np.searchsorted(pitch_times, times), 0, pitch_times.size - 1
        )
        f0 = pitch_values[indices].copy()
    else:
        f0 = np.full(times.shape, np.nan)
    f0[f0 <= 0.0] = np.nan

    voiced = f0[~np.isnan(f0)]
    if voiced.size:
        semitones = 12.0 * np.log2(f0 / float(np.median(voiced)))
    else:
        semitones = np.full(times.shape, np.nan)

    values = np.asarray(sound.values, dtype=float)
    samples = values.mean(axis=0) if values.ndim > 1 else values
    energy = _rms_db(samples, float(sound.sampling_frequency), times, energy_window)
    energy = energy - float(np.percentile(energy, 95))

    return Prosody(
        times=times,
        f0_hz=f0,
        semitones=semitones,
        energy_db=energy,
        duration=duration,
    )
```

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/test_prosody.py`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/shadow/analysis/prosody.py tests/test_prosody.py
git commit -m "feat: 半音归一化音高与能量包络提取"
```

---

### Task 12: analysis/align.py — 词锚点分段线性时间弯折

**Files:**
- Create: `src/shadow/analysis/align.py`
- Test: `tests/test_align.py`

把用户的时间轴映射到原声时间轴上，使两条曲线可以叠加。锚点是 diff 中匹配上的词的中点。匹配锚点少于 3 个时退化为整体线性缩放。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_align.py
import numpy as np
import pytest

from shadow.analysis.align import build_anchors, warp_user_times
from shadow.models import Word


def words_at(starts, *, dur=0.4):
    return tuple(Word(text=f"w{i}", start=s, end=s + dur) for i, s in enumerate(starts))


REF = words_at([0.0, 1.0, 2.0, 3.0, 4.0])
ALL_PAIRS = tuple((i, i) for i in range(5))


def test_identical_timings_warp_to_identity():
    times = np.linspace(0.0, 4.4, 50)
    warped = warp_user_times(
        times, ref_words=REF, usr_words=REF, pairs=ALL_PAIRS,
        ref_duration=4.4, usr_duration=4.4,
    )
    assert np.allclose(warped, times, atol=1e-6)


def test_uniformly_slower_user_is_compressed():
    usr = words_at([0.0, 2.0, 4.0, 6.0, 8.0], dur=0.8)
    warped = warp_user_times(
        np.array([0.0, 4.4, 8.8]), ref_words=REF, usr_words=usr, pairs=ALL_PAIRS,
        ref_duration=4.4, usr_duration=8.8,
    )
    assert warped[0] == pytest.approx(0.0)
    assert warped[1] == pytest.approx(2.2, abs=0.1)
    assert warped[2] == pytest.approx(4.4, abs=0.1)


def test_falls_back_to_linear_scale_when_too_few_anchors():
    usr = words_at([0.0, 2.0, 4.0, 6.0, 8.0], dur=0.8)
    warped = warp_user_times(
        np.array([0.0, 4.4, 8.8]), ref_words=REF, usr_words=usr, pairs=((0, 0),),
        ref_duration=4.4, usr_duration=8.8,
    )
    assert np.allclose(warped, np.array([0.0, 2.2, 4.4]), atol=1e-6)


def test_output_is_monotonic_non_decreasing():
    usr = words_at([0.0, 0.9, 2.6, 3.1, 5.0], dur=0.5)
    times = np.linspace(0.0, 5.5, 200)
    warped = warp_user_times(
        times, ref_words=REF, usr_words=usr, pairs=ALL_PAIRS,
        ref_duration=4.4, usr_duration=5.5,
    )
    assert np.all(np.diff(warped) >= -1e-9)


def test_build_anchors_includes_endpoints_and_is_strictly_increasing():
    usr = words_at([0.0, 1.5, 3.0, 4.5, 6.0])
    xs, ys = build_anchors(
        ref_words=REF, usr_words=usr, pairs=ALL_PAIRS,
        ref_duration=4.4, usr_duration=6.4,
    )
    assert xs[0] == 0.0 and ys[0] == 0.0
    assert xs[-1] == pytest.approx(6.4) and ys[-1] == pytest.approx(4.4)
    assert np.all(np.diff(xs) > 0) and np.all(np.diff(ys) > 0)
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/test_align.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'shadow.analysis.align'`

- [ ] **Step 3: 实现**

```python
# src/shadow/analysis/align.py
"""词锚点分段线性时间弯折。纯函数，无 IO。

不用帧级 DTW：90 秒片段是 9000x9000 的 DP，纯 Python 跑不动。而 diff 已经给出了
词级对应关系，用匹配词的中点作锚点做分段线性插值即可，O(n) 且锚点带语言学意义。
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

from ..models import Word

MIN_ANCHORS = 3


def _centre(word: Word) -> float:
    return 0.5 * (word.start + word.end)


def build_anchors(
    *,
    ref_words: Sequence[Word],
    usr_words: Sequence[Word],
    pairs: Sequence[tuple[int, int]],
    ref_duration: float,
    usr_duration: float,
) -> tuple[np.ndarray, np.ndarray]:
    """返回 (用户时间锚点, 原声时间锚点)，含首尾端点，严格递增。"""
    candidates = [(0.0, 0.0)]
    for ref_index, usr_index in pairs:
        candidates.append((_centre(usr_words[usr_index]), _centre(ref_words[ref_index])))
    candidates.append((usr_duration, ref_duration))

    xs: list[float] = []
    ys: list[float] = []
    for x, y in candidates:
        if xs and (x <= xs[-1] or y <= ys[-1]):
            continue
        xs.append(float(x))
        ys.append(float(y))
    return np.asarray(xs), np.asarray(ys)


def warp_user_times(
    usr_times,
    *,
    ref_words: Sequence[Word],
    usr_words: Sequence[Word],
    pairs: Sequence[tuple[int, int]],
    ref_duration: float,
    usr_duration: float,
) -> np.ndarray:
    """把用户时间轴映射到原声时间轴。"""
    times = np.asarray(usr_times, dtype=float)

    if len(pairs) < MIN_ANCHORS:
        scale = ref_duration / usr_duration if usr_duration > 0 else 1.0
        return times * scale

    xs, ys = build_anchors(
        ref_words=ref_words,
        usr_words=usr_words,
        pairs=pairs,
        ref_duration=ref_duration,
        usr_duration=usr_duration,
    )
    if xs.size < 2:
        scale = ref_duration / usr_duration if usr_duration > 0 else 1.0
        return times * scale
    return np.interp(times, xs, ys)
```

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/test_align.py`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/shadow/analysis/align.py tests/test_align.py
git commit -m "feat: 词锚点分段线性时间弯折"
```

---

### Task 13: analysis/timing.py — 每词时长比值

**Files:**
- Create: `src/shadow/analysis/timing.py`
- Test: `tests/test_timing.py`

这是**节奏诊断的数据来源**：比值 > 1 说明该词被拖长，< 1 说明被赶过去或吞掉。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_timing.py
import pytest

from shadow.analysis.diff import diff_words
from shadow.analysis.timing import word_timings
from shadow.models import Word

REF_TEXTS = ["should", "have", "been", "there"]


def make(texts, durations):
    words, t = [], 0.0
    for text, duration in zip(texts, durations):
        words.append(Word(text=text, start=t, end=t + duration))
        t += duration
    return tuple(words)


def test_ratio_is_user_duration_over_reference():
    ref = make(REF_TEXTS, [0.30, 0.08, 0.25, 0.30])
    usr = make(REF_TEXTS, [0.30, 0.24, 0.25, 0.30])
    timings = word_timings(ref, usr, diff_words(REF_TEXTS, REF_TEXTS))
    by_text = {t.text: t for t in timings}
    assert by_text["have"].ratio == pytest.approx(3.0)
    assert by_text["should"].ratio == pytest.approx(1.0)


def test_missing_word_has_no_ratio():
    ref = make(REF_TEXTS, [0.3, 0.1, 0.3, 0.3])
    spoken = ["should", "been", "there"]
    usr = make(spoken, [0.3, 0.3, 0.3])
    timings = word_timings(ref, usr, diff_words(REF_TEXTS, spoken))
    have = next(t for t in timings if t.text == "have")
    assert have.ratio is None
    assert have.usr_duration is None
    assert have.kind == "missing"


def test_one_entry_per_reference_word_in_order():
    ref = make(REF_TEXTS, [0.3, 0.1, 0.3, 0.3])
    usr = make(REF_TEXTS, [0.3, 0.1, 0.3, 0.3])
    timings = word_timings(ref, usr, diff_words(REF_TEXTS, REF_TEXTS))
    assert [t.ref_index for t in timings] == [0, 1, 2, 3]
    assert [t.text for t in timings] == REF_TEXTS


def test_zero_length_reference_word_is_skipped_safely():
    ref = make(REF_TEXTS, [0.3, 0.0, 0.3, 0.3])
    usr = make(REF_TEXTS, [0.3, 0.1, 0.3, 0.3])
    timings = word_timings(ref, usr, diff_words(REF_TEXTS, REF_TEXTS))
    assert next(t for t in timings if t.text == "have").ratio is None
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/test_timing.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'shadow.analysis.timing'`

- [ ] **Step 3: 实现**

```python
# src/shadow/analysis/timing.py
"""每个原文词的时长比值。纯函数，无 IO。

比值 > 1：该词被拖长（典型的逐词等重音）；< 1：被赶过去或吞掉。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..models import Word
from .diff import KIND_EQUAL, DiffToken


@dataclass(frozen=True, slots=True)
class WordTiming:
    ref_index: int
    text: str
    kind: str
    ref_duration: float
    usr_duration: float | None
    ratio: float | None


def word_timings(
    ref_words: Sequence[Word],
    usr_words: Sequence[Word],
    tokens: Sequence[DiffToken],
) -> tuple[WordTiming, ...]:
    results: list[WordTiming] = []
    for token in tokens:
        if token.ref_index is None:
            continue
        ref_word = ref_words[token.ref_index]
        usr_duration: float | None = None
        ratio: float | None = None
        if token.kind == KIND_EQUAL and token.usr_index is not None:
            usr_duration = usr_words[token.usr_index].duration
            if ref_word.duration > 0:
                ratio = usr_duration / ref_word.duration
        results.append(
            WordTiming(
                ref_index=token.ref_index,
                text=ref_word.text,
                kind=token.kind,
                ref_duration=ref_word.duration,
                usr_duration=usr_duration,
                ratio=ratio,
            )
        )
    results.sort(key=lambda item: item.ref_index)
    return tuple(results)
```

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/test_timing.py`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/shadow/analysis/timing.py tests/test_timing.py
git commit -m "feat: 每词时长比值计算"
```

---

### Task 14: report/plot.py — 三面板对比图

**Files:**
- Create: `src/shadow/report/plot.py`
- Test: `tests/test_plot.py`

三个面板：音高轮廓、能量包络、每词时长比值。**Panel 3 是节奏诊断的主图。**

- [ ] **Step 1: 写失败测试**

```python
# tests/test_plot.py
import numpy as np

from shadow.analysis.prosody import Prosody
from shadow.analysis.timing import WordTiming
from shadow.report.plot import render_comparison


def fake_prosody(duration=2.0, offset=0.0):
    times = np.arange(0.0, duration, 0.01)
    return Prosody(
        times=times,
        f0_hz=np.full(times.shape, 200.0),
        semitones=np.sin(times * 3.0) + offset,
        energy_db=-np.abs(np.cos(times * 3.0)) * 10.0,
        duration=duration,
    )


TIMINGS = (
    WordTiming(0, "should", "equal", 0.30, 0.32, 1.07),
    WordTiming(1, "have", "equal", 0.08, 0.26, 3.25),
    WordTiming(2, "been", "missing", 0.25, None, None),
    WordTiming(3, "there", "equal", 0.30, 0.21, 0.70),
)


def test_render_writes_a_png(tmp_path):
    out = tmp_path / "cmp.png"
    reference = fake_prosody()
    user = fake_prosody(offset=0.5)
    render_comparison(
        ref_prosody=reference,
        usr_prosody=user,
        usr_times_warped=user.times,
        timings=TIMINGS,
        out_path=out,
        title="test",
        accuracy=0.75,
    )
    assert out.exists()
    assert out.stat().st_size > 10_000


def test_labels_fall_back_to_english_without_cjk_font(monkeypatch):
    from shadow.report import plot

    monkeypatch.setattr(plot, "_pick_cjk_font", lambda: None)
    assert plot.configure_labels() is plot.LABELS_EN


def test_labels_use_chinese_when_font_available(monkeypatch):
    from shadow.report import plot

    monkeypatch.setattr(plot, "_pick_cjk_font", lambda: "PingFang SC")
    assert plot.configure_labels() is plot.LABELS_ZH


def test_render_handles_all_missing_timings(tmp_path):
    out = tmp_path / "cmp2.png"
    reference = fake_prosody()
    timings = tuple(
        WordTiming(i, f"w{i}", "missing", 0.2, None, None) for i in range(4)
    )
    render_comparison(
        ref_prosody=reference,
        usr_prosody=reference,
        usr_times_warped=reference.times,
        timings=timings,
        out_path=out,
        title="empty",
        accuracy=0.0,
    )
    assert out.exists()
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/test_plot.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'shadow.report.plot'`

- [ ] **Step 3: 实现**

```python
# src/shadow/report/plot.py
"""三面板对比图。

Panel 1 语调轮廓、Panel 2 轻重分布、Panel 3 每词时长比值——
Panel 3 是治「逐词等重音」的主图。
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402  (必须在 use("Agg") 之后)
import numpy as np  # noqa: E402
from matplotlib import font_manager  # noqa: E402

from ..analysis.prosody import Prosody  # noqa: E402
from ..analysis.timing import WordTiming  # noqa: E402

REF_COLOUR = "#1f77b4"
USR_COLOUR = "#d62728"
FLAG_COLOUR = "#999999"

# matplotlib 内置字体不含 CJK 字形，直接写中文会渲染成一排方框。
CJK_FONT_CANDIDATES = (
    "PingFang SC", "Hiragino Sans GB", "Heiti SC", "Songti SC",
    "STHeiti", "Arial Unicode MS", "Noto Sans CJK SC",
)

LABELS_ZH = {
    "ref": "原声",
    "usr": "你",
    "accuracy": "可懂度",
    "p1_title": "Panel 1 · 语调轮廓：起伏形状和重音落点是否一致",
    "p1_y": "音高（半音，相对各自中位数）",
    "p2_title": "Panel 2 · 轻重分布",
    "p2_y": "能量（dB）",
    "p2_x": "时间（秒，已对齐到原声轴）",
    "p3_title": "Panel 3 · 节奏：柱子高于 1.0 = 拖长了（该弱读却发满），红柱 = 机器没听出这个词",
    "p3_y": "你的时长 / 原声时长",
}

LABELS_EN = {
    "ref": "reference",
    "usr": "you",
    "accuracy": "intelligibility",
    "p1_title": "Panel 1 - Intonation contour: same shape and stress placement?",
    "p1_y": "pitch (semitones, relative to own median)",
    "p2_title": "Panel 2 - Loudness distribution",
    "p2_y": "energy (dB)",
    "p2_x": "time (s, warped onto reference axis)",
    "p3_title": "Panel 3 - Rhythm: bar above 1.0 = stretched (should be reduced); red = not recognised",
    "p3_y": "your duration / reference duration",
}


def _pick_cjk_font() -> str | None:
    available = {font.name for font in font_manager.fontManager.ttflist}
    for candidate in CJK_FONT_CANDIDATES:
        if candidate in available:
            return candidate
    return None


def configure_labels() -> dict[str, str]:
    """装得上中文字体就用中文标注，装不上就整体退回英文——绝不渲染方框。"""
    plt.rcParams["axes.unicode_minus"] = False
    font = _pick_cjk_font()
    if font is None:
        return LABELS_EN
    plt.rcParams["font.sans-serif"] = [font, *plt.rcParams["font.sans-serif"]]
    return LABELS_ZH


def render_comparison(
    *,
    ref_prosody: Prosody,
    usr_prosody: Prosody,
    usr_times_warped: np.ndarray,
    timings: Sequence[WordTiming],
    out_path: Path,
    title: str,
    accuracy: float,
) -> Path:
    labels = configure_labels()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    figure, (ax_pitch, ax_energy, ax_timing) = plt.subplots(
        3, 1, figsize=(14, 10), gridspec_kw={"height_ratios": [2, 1, 2]}
    )
    figure.suptitle(
        f"{title}    {labels['accuracy']} {accuracy * 100:.0f}%", fontsize=13
    )

    ax_pitch.plot(ref_prosody.times, ref_prosody.semitones,
                  color=REF_COLOUR, linewidth=2.0, label=labels["ref"])
    ax_pitch.plot(usr_times_warped, usr_prosody.semitones,
                  color=USR_COLOUR, linewidth=1.6, linestyle="--", label=labels["usr"])
    ax_pitch.axhline(0.0, color=FLAG_COLOUR, linewidth=0.6)
    ax_pitch.set_ylabel(labels["p1_y"])
    ax_pitch.set_title(labels["p1_title"], loc="left")
    ax_pitch.legend(loc="upper right")
    ax_pitch.grid(alpha=0.2)

    ax_energy.plot(ref_prosody.times, ref_prosody.energy_db,
                   color=REF_COLOUR, linewidth=1.6, label=labels["ref"])
    ax_energy.plot(usr_times_warped, usr_prosody.energy_db,
                   color=USR_COLOUR, linewidth=1.4, linestyle="--", label=labels["usr"])
    ax_energy.set_ylabel(labels["p2_y"])
    ax_energy.set_xlabel(labels["p2_x"])
    ax_energy.set_title(labels["p2_title"], loc="left")
    ax_energy.grid(alpha=0.2)

    positions = np.arange(len(timings))
    ratios = [t.ratio if t.ratio is not None else 0.0 for t in timings]
    colours = [USR_COLOUR if t.ratio is None else REF_COLOUR for t in timings]
    ax_timing.bar(positions, ratios, color=colours)
    ax_timing.axhline(1.0, color="#333333", linewidth=1.2)
    ax_timing.set_xticks(positions)
    ax_timing.set_xticklabels(
        [t.text for t in timings], rotation=60, ha="right", fontsize=8
    )
    ax_timing.set_ylabel(labels["p3_y"])
    ax_timing.set_title(labels["p3_title"], loc="left")
    ax_timing.grid(alpha=0.2, axis="y")

    figure.tight_layout(rect=(0, 0, 1, 0.97))
    figure.savefig(out_path, dpi=120)
    plt.close(figure)
    return out_path
```

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/test_plot.py`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/shadow/report/plot.py tests/test_plot.py
git commit -m "feat: 三面板韵律对比图"
```

---

### Task 15: cli.py — 四个子命令

**Files:**
- Create: `src/shadow/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_cli.py
import numpy as np
import pytest
import soundfile as sf

from shadow import cli, db
from shadow.models import Word


@pytest.fixture(autouse=True)
def isolated_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path / "data"))


def write_tone(path, *, seconds=2.0, freq=220.0):
    sr = 16000
    t = np.arange(int(seconds * sr)) / sr
    sf.write(path, (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32), sr)
    return path


def test_list_on_empty_db_exits_zero(capsys):
    assert cli.main(["list"]) == 0
    assert "还没有导入" in capsys.readouterr().out


def test_import_reports_failure_without_traceback(monkeypatch, capsys):
    monkeypatch.setattr(cli, "import_source", lambda url, conn: (_ for _ in ()).throw(
        RuntimeError("ERROR: Video unavailable")
    ))
    assert cli.main(["import", "https://x/y"]) == 1
    assert "Video unavailable" in capsys.readouterr().err


def test_compare_writes_png(monkeypatch, tmp_path, capsys):
    reference = write_tone(tmp_path / "ref.wav")
    user = write_tone(tmp_path / "usr.wav")
    out = tmp_path / "out.png"

    def fake_transcribe(path):
        return tuple(
            Word(text=text, start=start, end=start + 0.4)
            for text, start in zip(
                ["should", "have", "been", "there"], [0.0, 0.5, 1.0, 1.5]
            )
        )

    monkeypatch.setattr(cli, "transcribe_words", fake_transcribe)
    exit_code = cli.main(
        ["compare", "--ref", str(reference), "--user", str(user), "-o", str(out)]
    )
    assert exit_code == 0
    assert out.exists()
    assert "可懂度" in capsys.readouterr().out


def test_compare_rejects_silent_recording(monkeypatch, tmp_path, capsys):
    reference = write_tone(tmp_path / "ref.wav")
    sr = 16000
    sf.write(tmp_path / "silent.wav", np.zeros(sr * 2, dtype=np.float32), sr)
    exit_code = cli.main(
        ["compare", "--ref", str(reference), "--user", str(tmp_path / "silent.wav")]
    )
    assert exit_code == 1
    assert "静音" in capsys.readouterr().err
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/test_cli.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'shadow.cli'`

- [ ] **Step 3: 实现**

```python
# src/shadow/cli.py
"""shadow 命令行入口：import / list / export / compare。"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from . import config, db, media
from .analysis.align import warp_user_times
from .analysis.diff import accuracy as diff_accuracy
from .analysis.diff import diff_words, matched_pairs
from .analysis.prosody import analyse
from .analysis.timing import word_timings
from .ingest.pipeline import import_source
from .ingest.transcriber import transcribe_words
from .models import Word
from .report.plot import render_comparison


def _open_db():
    connection = db.connect()
    db.init_db(connection)
    db.reset_stale_sources(connection)
    return connection


def cmd_import(args: argparse.Namespace) -> int:
    connection = _open_db()
    try:
        source_id = import_source(args.url, conn=connection)
    except Exception as exc:
        print(f"导入失败：{exc}", file=sys.stderr)
        return 1
    segments = db.list_segments(connection, source_id)
    row = db.get_source(connection, source_id)
    print(f"[{source_id}] {row['title']}")
    print(f"  时长 {row['duration_sec'] / 60:.1f} 分钟，切出 {len(segments)} 个片段")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    connection = _open_db()
    sources = db.list_sources(connection)
    if not sources:
        print("还没有导入任何素材。试试：shadow import <url>")
        return 0
    for row in sources:
        segments = db.list_segments(connection, row["id"])
        print(f"[{row['id']}] {row['title']}  ({row['status']}, {len(segments)} 片段)")
        if row["error"]:
            print(f"      错误：{row['error']}")
        if args.segments:
            for segment in segments:
                preview = segment["text"][:60]
                print(
                    f"      #{segment['id']} "
                    f"{segment['start_sec']:7.1f}-{segment['end_sec']:7.1f}s  {preview}…"
                )
    return 0


def _segment_reference(connection, segment_id: int, dest: Path):
    """导出片段音频，并把词时间戳平移到以片段起点为 0。"""
    segment = db.get_segment(connection, segment_id)
    if segment is None:
        raise SystemExit(f"片段 {segment_id} 不存在")
    source = db.get_source(connection, segment["source_id"])
    if source is None or not source["audio_path"]:
        raise SystemExit(f"片段 {segment_id} 的素材音频缺失")
    media.cut_segment(
        Path(source["audio_path"]), dest,
        start=segment["start_sec"], end=segment["end_sec"],
    )
    offset = segment["start_sec"]
    words = tuple(
        replace(word, start=word.start - offset, end=word.end - offset)
        for word in segment["words"]
    )
    return dest, words, segment["text"]


def cmd_export(args: argparse.Namespace) -> int:
    connection = _open_db()
    dest = Path(args.out or config.segment_audio_dir() / f"{args.segment}.wav")
    try:
        path, _, text = _segment_reference(connection, args.segment, dest)
    except Exception as exc:
        print(f"导出失败：{exc}", file=sys.stderr)
        return 1
    print(f"已导出 {path}")
    print(text)
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    try:
        media.validate_attempt(Path(args.user))
    except Exception as exc:
        print(f"录音不可用：{exc}", file=sys.stderr)
        return 1

    connection = _open_db()
    try:
        if args.segment is not None:
            ref_path, ref_words, _ = _segment_reference(
                connection, args.segment,
                config.segment_audio_dir() / f"{args.segment}.wav",
            )
        else:
            ref_path = Path(args.ref)
            ref_words = transcribe_words(ref_path)
        usr_words: tuple[Word, ...] = transcribe_words(Path(args.user))
    except Exception as exc:
        print(f"转写失败：{exc}", file=sys.stderr)
        return 1

    if not ref_words:
        print("原声转写为空，无法比较。", file=sys.stderr)
        return 1

    tokens = diff_words([w.text for w in ref_words], [w.text for w in usr_words])
    score = diff_accuracy(tokens)

    ref_prosody = analyse(ref_path)
    usr_prosody = analyse(Path(args.user))
    warped = warp_user_times(
        usr_prosody.times,
        ref_words=ref_words,
        usr_words=usr_words,
        pairs=matched_pairs(tokens),
        ref_duration=ref_prosody.duration,
        usr_duration=usr_prosody.duration,
    )
    timings = word_timings(ref_words, usr_words, tokens)

    out_path = Path(args.out or "comparison.png")
    render_comparison(
        ref_prosody=ref_prosody,
        usr_prosody=usr_prosody,
        usr_times_warped=warped,
        timings=timings,
        out_path=out_path,
        title=ref_path.name,
        accuracy=score,
    )

    print(f"可懂度 {score * 100:.0f}%（{len(ref_words)} 个词）")
    problems = [t for t in tokens if t.kind != "equal"]
    if problems:
        print("机器没听对的词：")
        for token in problems[:20]:
            if token.kind == "missing":
                print(f"  漏  {token.ref_text}")
            elif token.kind == "wrong":
                print(f"  错  {token.ref_text}  ->  听成 {token.usr_text}")
            else:
                print(f"  多  {token.usr_text}")
    print(f"对比图已写入 {out_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="shadow", description="英语影子跟读训练工具")
    sub = parser.add_subparsers(dest="command", required=True)

    p_import = sub.add_parser("import", help="从 URL 导入素材")
    p_import.add_argument("url")
    p_import.set_defaults(func=cmd_import)

    p_list = sub.add_parser("list", help="列出已导入素材")
    p_list.add_argument("-s", "--segments", action="store_true", help="同时列出片段")
    p_list.set_defaults(func=cmd_list)

    p_export = sub.add_parser("export", help="导出片段音频用于跟读")
    p_export.add_argument("segment", type=int)
    p_export.add_argument("-o", "--out")
    p_export.set_defaults(func=cmd_export)

    p_compare = sub.add_parser("compare", help="对比原声与你的录音")
    group = p_compare.add_mutually_exclusive_group(required=True)
    group.add_argument("--ref", help="原声 wav 路径")
    group.add_argument("--segment", type=int, help="已导入的片段 id")
    p_compare.add_argument("--user", required=True, help="你的录音 wav 路径")
    p_compare.add_argument("-o", "--out", help="输出 png 路径")
    p_compare.set_defaults(func=cmd_compare)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/test_cli.py`
Expected: 4 passed

- [ ] **Step 5: 全量测试**

Run: `uv run pytest`
Expected: 全部通过，无失败

- [ ] **Step 6: Commit**

```bash
git add src/shadow/cli.py tests/test_cli.py
git commit -m "feat: 命令行入口 import/list/export/compare"
```

---

### Task 16: README 与人工验证

**Files:**
- Create: `README.md`
- Create: `docs/superpowers/plans/2026-09-09-m2-verdict.md`

**这一步不是走过场——它产出的结论决定 M3-M5 是否按原方案进行。**

- [ ] **Step 1: 写 README**

```markdown
# Shadow

英语影子跟读训练工具（命令行内核，M1 + M2）。

## 安装

    brew install ffmpeg yt-dlp
    uv sync

首次运行 `compare` 或 `import` 会自动下载 Whisper 模型 `large-v3-turbo`（约 1.5 GB）。

## 用法

    shadow import <url>          # 导入素材，自动转写并切成 30-90s 片段
    shadow list -s               # 列出素材与片段
    shadow export <segment_id>   # 导出片段音频用于跟读
    shadow compare --segment <id> --user my.wav -o out.png

也可以完全脱离素材库直接比较两个 wav：

    shadow compare --ref ref.wav --user my.wav -o out.png

## 反馈图怎么看

- **Panel 1 语调轮廓**：蓝实线是原声，红虚线是你。看**形状**是否一致，不看高低——
  纵轴已按各自基频中位数归一化成半音，跨性别也可比。
- **Panel 2 轻重分布**：能量包络。
- **Panel 3 节奏**：每个词「你的时长 ÷ 原声时长」。高于 1.0 的柱子 = 你把该弱读的词发满了，
  这是中文母语者最典型的问题。红柱 = 机器没听出这个词。

## 数据位置

默认 `~/.shadow`（可用环境变量 `SHADOW_DATA_DIR` 覆盖）。
```

- [ ] **Step 2: 端到端手动跑一遍**

```bash
uv run shadow import "https://www.youtube.com/watch?v=<一个 5-10 分钟的英语视频>"
uv run shadow list -s
uv run shadow export <第一个片段 id> -o /tmp/ref.wav
```

用任意录音工具跟读 `/tmp/ref.wav`，存成 `/tmp/me.wav`（16k 单声道最佳），然后：

```bash
uv run shadow compare --segment <同一个 id> --user /tmp/me.wav -o /tmp/out.png
open /tmp/out.png
```

- [ ] **Step 3: 记录 M2 结论**

创建 `docs/superpowers/plans/2026-09-09-m2-verdict.md`，逐条回答：

```markdown
# M2 结论：韵律反馈是否有信息量

日期：____
素材：____
跟读次数：____

## 1. Panel 3（每词时长比值）
- 我能否指出至少 3 个「我拖长了、原声是弱读」的词？ 是 / 否
- 举例：____
- 依据它调整后重读一次，柱子是否变平？ 是 / 否

## 2. Panel 1（语调轮廓）
- 两条线的形状差异是否肉眼可辨？ 是 / 否
- 差异是否指向可执行的动作（而非「感觉不太像」）？ 是 / 否

## 3. Panel 2（能量包络）
- 是否提供了 Panel 1/3 之外的信息？ 是 / 否
- 若否，M4 可考虑删掉此面板。

## 4. ASR 可懂度 diff
- 漏词/错词列表是否命中我真实的发音弱点？ 是 / 否

## 结论（三选一）
- [ ] 有信息量 -> 按原方案进入 M3
- [ ] 部分有用 -> 保留 ____，去掉 ____，调整后进入 M3
- [ ] 没有信息量 -> 回到设计阶段重新设计反馈方式
```

- [ ] **Step 4: Commit**

```bash
git add README.md docs/superpowers/plans/2026-09-09-m2-verdict.md
git commit -m "docs: README 与 M2 验证结论模板"
```

---

## 完成标准

- [ ] `uv run pytest` 全绿
- [ ] `shadow import` 能把一个真实 URL 导成若干片段
- [ ] `shadow compare` 能产出三面板 PNG
- [ ] `2026-09-09-m2-verdict.md` 已填写，M3 的走向已确定
