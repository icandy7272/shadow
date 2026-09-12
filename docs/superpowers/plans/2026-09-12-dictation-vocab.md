# 默写和生词本 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 练习页第二步改成整句默写；不会和写错的词用离线 ECDICT 显示释义；不会的词记进生词本。

**Architecture:** 纯函数 `drill/dictation.py` 负责拆标点和判对；`dictionary.py` 把 ECDICT CSV 转成本地 SQLite 并查词；`db.py` 加生词本两张表和默写记分；网页换掉第二步并新增生词本页面；命令行加 `dict install / lookup`；最后删掉不再使用的挖空选词机制。

**Tech Stack:** Python 3.14、FastAPI、SQLite、Jinja2、原生 JS、pytest。

设计文档：`docs/superpowers/specs/2026-09-12-dictation-vocab-design.md`
测试命令一律 `uv run pytest ... -q -p no:warnings`。

---

## 文件结构

| 文件 | 动作 | 职责 |
|---|---|---|
| `src/shadow/drill/dictation.py` | 新建 | 拆出词前后的标点、判对、统计、查词键 |
| `src/shadow/dictionary.py` | 新建 | 下载 ECDICT、建本地词库、查词（带原形） |
| `src/shadow/db.py` | 改 | `vocab`、`vocab_sources` 表；`gapfill_unknown` 列；`set_dictation`；生词增删查 |
| `src/shadow/web/app.py` | 改 | 练习页传 `tokens`；`/api/dictation`；生词本页面和接口；删 `/api/gapfill` |
| `src/shadow/web/templates/practice.html` | 改 | 第二步换成默写，跟读固定第 3 步 |
| `src/shadow/web/templates/vocab.html` | 新建 | 生词本 |
| `src/shadow/web/templates/base.html` | 改 | 顶栏「生词本」入口、加载 `vocab.js` |
| `src/shadow/web/static/app.js` | 改 | 默写交互和结果 |
| `src/shadow/web/static/vocab.js` | 新建 | 「记住了」 |
| `src/shadow/web/static/app.css` | 改 | 默写框、结果、生词本样式 |
| `src/shadow/cli.py` | 改 | `dict install / lookup`；`progress` 显示默写统计 |
| 清理 | 删/改 | `drill/gapfill.py`、`drill/blanks.py`、`_apply_blanks`、`Word.is_blank`、`with_blanks`、「空」列、`units` 空数、`db.set_gapfill` |

---

### Task 1: 默写判对（纯函数）

**Files:** Create `src/shadow/drill/dictation.py`；Test `tests/test_dictation.py`

- [ ] **Step 1: 写失败的测试** —— `tests/test_dictation.py`：拆标点（`there.`、`“Stay`、`don't,`、`—`）；判对忽略大小写/标点/撇号（`im` 对 `I'm`）；逐词判、纯标点不判、没交算写错；勾了「不会」即使填了也算不会；查词键。
- [ ] **Step 2: 跑测试确认失败**（`ImportError`）
- [ ] **Step 3: 实现**

```python
"""整句默写。纯函数，无 IO。

每个词都要写；不会的可以勾「不会」。判对忽略大小写、标点和撇号——
手机上打撇号很麻烦，I'm 写成 im 不该算错。录音比对共用的 text.normalise
保留撇号，这里单独比较，不去动它。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Sequence

from ..models import Word

OK = "ok"
WRONG = "wrong"
UNKNOWN = "unknown"

_EDGES = re.compile(r"^([^\w']*)(.*?)([^\w']*)$")
_IGNORED = re.compile(r"[^a-z0-9]")


@dataclass(frozen=True, slots=True)
class Token:
    """页面上的一个词：框前的标点、要写的部分、框后的标点。"""

    lead: str
    core: str
    trail: str


@dataclass(frozen=True, slots=True)
class Answer:
    guess: str = ""
    unknown: bool = False


@dataclass(frozen=True, slots=True)
class Mark:
    index: int
    answer: str       # 要写的部分，不带首尾标点
    guess: str
    status: str       # OK / WRONG / UNKNOWN


def split(text: str) -> Token:
    lead, core, trail = _EDGES.match(text).groups()
    return Token(lead=lead, core=core, trail=trail)


def _bare(text: str) -> str:
    return _IGNORED.sub("", text.lower())


def needs_box(text: str) -> bool:
    """纯标点的词不出框。"""
    return bool(_bare(split(text).core))


def key(text: str) -> str:
    """查词、记生词用的键：小写，去掉首尾标点。"""
    return split(text).core.lower()


def matches(guess: str, answer: str) -> bool:
    wanted = _bare(answer)
    return bool(wanted) and _bare(guess) == wanted


def grade(words: Sequence[Word], answers: Mapping[int, Answer]) -> tuple[Mark, ...]:
    """逐词判。纯标点不判；没交上来的词算写错。"""
    marks = []
    for index, word in enumerate(words):
        if not needs_box(word.text):
            continue
        core = split(word.text).core
        answer = answers.get(index, Answer())
        if answer.unknown:
            status = UNKNOWN
        elif matches(answer.guess, core):
            status = OK
        else:
            status = WRONG
        marks.append(Mark(index=index, answer=core, guess=answer.guess.strip(), status=status))
    return tuple(marks)


def tally(marks: Sequence[Mark]) -> tuple[int, int, int]:
    """(写对, 写错, 不会)。"""
    return tuple(sum(1 for mark in marks if mark.status == status)
                 for status in (OK, WRONG, UNKNOWN))
```

- [ ] **Step 4: 跑测试确认通过**
- [ ] **Step 5: 提交** `feat: 默写判对——拆出标点，忽略大小写、标点和撇号`

---

### Task 2: 离线词典

**Files:** Create `src/shadow/dictionary.py`；Test `tests/test_dictionary.py`

- [ ] **Step 1: 写失败的测试** —— `tests/test_dictionary.py`：五行 CSV 夹具（graduate / graduated / Jobs / jobs / job，释义含字面 `\n`）；没装时查不到；`install` 建库返回 4、第二次返回 None、`force` 重装；音标和逐行义项；变形词带原形；小写那条胜出；查不到为 None；`lookup_many`。
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**

```python
"""离线英汉词典（ECDICT，MIT 协议，https://github.com/skywind3000/ECDICT）。

第一次用时下载 CSV，转成本地 SQLite，只留查词要用的几列；之后查词不联网。
"""

from __future__ import annotations

import csv
import sqlite3
import tempfile
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

from . import config

SOURCE_URL = "https://raw.githubusercontent.com/skywind3000/ECDICT/master/ecdict.csv"
MAX_MEANINGS = 4          # 义项太多，反而找不到要的那个
CHUNK_BYTES = 1 << 16
FIELD_LIMIT = 2**31 - 1   # detail 列很长，超过 csv 模块的默认上限


@dataclass(frozen=True, slots=True)
class Entry:
    word: str
    phonetic: str
    meanings: tuple[str, ...]
    lemma: "Entry | None" = None     # 变形词的原形


def path() -> Path:
    return config.data_dir() / "dict.sqlite"


def installed() -> bool:
    return path().exists()


def _lemma_of(exchange: str | None) -> str | None:
    """词形变化字段里的「0:原形」。比如 perceived 的是 0:perceive/1:pd。"""
    for item in (exchange or "").split("/"):
        kind, _, value = item.partition(":")
        if kind == "0" and value:
            return value.lower()
    return None


def build(csv_path: Path, dest: Path) -> int:
    """把 ECDICT 的 CSV 转成查词用的 SQLite，返回词条数。先写临时文件，成功才换上。"""
    csv.field_size_limit(FIELD_LIMIT)
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_name(dest.name + ".building")
    temp.unlink(missing_ok=True)
    connection = sqlite3.connect(temp)
    try:
        connection.execute(
            "CREATE TABLE entries (word TEXT PRIMARY KEY, original TEXT NOT NULL,"
            " phonetic TEXT, translation TEXT, exchange TEXT)")
        with open(csv_path, newline="", encoding="utf-8") as handle:
            rows = ((row["word"].lower(), row["word"], row["phonetic"],
                     # 释义里的换行在 CSV 里存成字面的 \n
                     row["translation"].replace("\\n", "\n"), row["exchange"])
                    for row in csv.DictReader(handle) if row.get("word"))
            # 大小写不同的同一个词（Jobs / jobs）：保留原文本身就是小写的那条
            connection.executemany(
                "INSERT INTO entries VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(word) DO UPDATE SET original = excluded.original,"
                " phonetic = excluded.phonetic, translation = excluded.translation,"
                " exchange = excluded.exchange WHERE excluded.original = excluded.word",
                rows)
        connection.commit()
        count = connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    finally:
        connection.close()
    temp.replace(dest)
    return count


def download(url: str, dest: Path, report=None) -> None:
    """流式下载到 dest；report(已下载字节, 总字节) 用来显示进度。"""
    with urllib.request.urlopen(url, timeout=60) as response, open(dest, "wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while chunk := response.read(CHUNK_BYTES):
            out.write(chunk)
            done += len(chunk)
            if report is not None:
                report(done, total)


def install(*, fetch=None, force: bool = False, report=None) -> int | None:
    """下载并建好词库，返回词条数。已经装过又没要求重装，返回 None。"""
    fetch = fetch or download
    if installed() and not force:
        return None
    with tempfile.TemporaryDirectory() as folder:
        csv_path = Path(folder) / "ecdict.csv"
        fetch(SOURCE_URL, csv_path, report=report)
        return build(csv_path, path())


def _read(connection, word: str):
    row = connection.execute("SELECT * FROM entries WHERE word = ?", (word,)).fetchone()
    if row is None:
        return None
    meanings = tuple(line.strip() for line in (row["translation"] or "").splitlines()
                     if line.strip())
    return row, Entry(word=row["original"], phonetic=row["phonetic"] or "",
                      meanings=meanings[:MAX_MEANINGS])


def lookup_many(words: Iterable[str]) -> dict[str, Entry | None]:
    """查一批词（按查词键）。没装词典时全是 None。变形词带上原形的释义。"""
    keys = list(dict.fromkeys(word.lower() for word in words))
    if not installed():
        return {key: None for key in keys}
    connection = sqlite3.connect(f"file:{path()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        found: dict[str, Entry | None] = {}
        for key in keys:
            hit = _read(connection, key)
            if hit is None:
                found[key] = None
                continue
            row, entry = hit
            base = _lemma_of(row["exchange"])
            if base and base != key:
                lemma = _read(connection, base)
                if lemma is not None:
                    entry = replace(entry, lemma=lemma[1])
            found[key] = entry
        return found
    finally:
        connection.close()


def lookup(word: str) -> Entry | None:
    return lookup_many([word])[word.lower()]
```

- [ ] **Step 4: 跑测试确认通过**
- [ ] **Step 5: 提交** `feat: 离线英汉词典——ECDICT 转本地词库，查词带原形`

---

### Task 3: 生词本和默写记分（数据层）

**Files:** Modify `src/shadow/db.py`；Test `tests/test_db.py`

- [ ] **Step 1: 写失败的测试**：`set_dictation` 写入 correct/total/unknown/replays；`add_vocab` 次数累加、同句出处不重复、不同句出处都保留；`list_vocab` 最近记下的在前并带出处；`remove_vocab` 返回是否存在；删素材后生词本还在。
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**
  - `MIGRATIONS` 追加 `("practice_runs", "gapfill_unknown", "INTEGER")`
  - `SCHEMA` 加：

```sql
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
```

  - 函数：

```python
def set_dictation(conn, run_id: int, *, correct: int, total: int, unknown: int,
                  replays: int) -> None:
    """整句默写的记分。沿用填空时代的列名，gapfill_heard 不再写。"""
    conn.execute(
        "UPDATE practice_runs SET gapfill_correct = ?, gapfill_total = ?,"
        " gapfill_unknown = ?, gapfill_replays = ? WHERE id = ?",
        (correct, total, unknown, replays, run_id))
    conn.commit()


def add_vocab(conn, word: str, *, sentence: str, segment_id: int | None = None,
              unit_index: int | None = None) -> int:
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


def vocab_words(conn) -> set[str]:
    return {row["word"] for row in conn.execute("SELECT word FROM vocab")}


def list_vocab(conn) -> list[dict[str, Any]]:
    """生词本，最近记下的在前；每个词带上全部出处。"""
    items = [dict(row) for row in conn.execute(
        "SELECT * FROM vocab ORDER BY last_added DESC, word")]
    sources: dict[str, list[dict[str, Any]]] = {}
    for row in conn.execute("SELECT * FROM vocab_sources ORDER BY added_at, rowid"):
        sources.setdefault(row["word"], []).append(dict(row))
    for item in items:
        item["sources"] = sources.get(item["word"], [])
    return items


def remove_vocab(conn, word: str) -> bool:
    with conn:
        conn.execute("DELETE FROM vocab_sources WHERE word = ?", (word,))
        cursor = conn.execute("DELETE FROM vocab WHERE word = ?", (word,))
    return cursor.rowcount > 0
```

- [ ] **Step 4: 跑测试确认通过**
- [ ] **Step 5: 提交** `feat: 数据层支持生词本和默写记分`

---

### Task 4: 练习页第二步换成默写

**Files:** Modify `app.py`、`practice.html`、`app.js`、`app.css`；Test `tests/test_web.py`

- [ ] **Step 1: 写失败的测试**：删掉 `test_gapfill_separates_heard_from_guessed`、`test_gapfill_reports_the_swallowed_duration_on_a_miss`、`test_step_two_is_omitted_when_there_is_nothing_to_fill`、`test_step_two_is_present_when_there_are_blanks`，换成：
  - `test_every_sentence_gets_a_dictation_step_with_a_box_per_word`：`Thank you all.` 三个框、有「不会」、跟读是第 3 步
  - `test_dictation_marks_every_word_and_records_unknown_words`：`It was a start.` 交 it / is / 不会 / start → (2, 1, 1, 4)，状态顺序，`in_vocab`，没装词典 `entry` 为 None、`dictionary` 为 false；库里 `gapfill_*` 四个数；生词本只有 `a`
  - `test_the_old_gapfill_endpoint_is_gone`：`POST /api/gapfill` 返回 404
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**
  - `app.py`：`from ..drill.gapfill import blanks_of` 换成 `from ..drill import dictation`；`from .. import ...` 加 `dictionary`；练习页上下文去掉 `"blanks"`，加 `"tokens": [_token(w.text) for w in words]`：

```python
def _token(text: str) -> dict:
    token = dictation.split(text)
    return {"lead": token.lead, "core": token.core, "trail": token.trail,
            "box": dictation.needs_box(text)}


def _entry_json(entry) -> dict | None:
    if entry is None:
        return None
    return {"word": entry.word, "phonetic": entry.phonetic, "meanings": list(entry.meanings),
            "lemma": None if entry.lemma is None else
            {"word": entry.lemma.word, "meanings": list(entry.lemma.meanings)}}
```

  - `/api/gapfill` 整个换成：

```python
@app.post("/api/dictation")
def save_dictation(payload: dict = Body(...)):
    connection = _db()
    segment, unit = int(payload["segment"]), int(payload["unit"])
    _, words = _unit_words(connection, segment, unit)
    answers = {int(item["index"]): dictation.Answer(
                   guess=str(item.get("guess") or ""), unknown=bool(item.get("unknown")))
               for item in payload.get("answers", [])}
    marks = dictation.grade(words, answers)
    correct, wrong, unknown = dictation.tally(marks)
    replays = int(payload.get("replays") or 0)
    sentence = " ".join(w.text for w in words)
    run_id = _run_for(connection, segment, unit, payload.get("run_id"), words)
    db.set_dictation(connection, run_id, correct=correct, total=len(marks),
                     unknown=unknown, replays=replays)
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
```

  - `practice.html` 第二步换成默写（去掉 `{% if blanks %}`），跟读标题固定 `<span class="n">3</span>`：

```html
  <section class="step locked" id="step-drill">
    <h2><span class="n">2</span> 默写</h2>
    <p class="hint">每个词写进一个框，回车跳到下一个。不会的勾「不会」，对完答案会给出释义，并记进生词本。</p>
    <div class="row">…播放行照旧…</div>
    <p class="sentence dictation">
      {%- for t in tokens -%}
        {%- if t.box -%}
          <span class="slot"><span class="box">{{ t.lead }}<input type="text" autocomplete="off"
            autocapitalize="off" spellcheck="false" data-index="{{ loop.index0 }}">{{ t.trail }}</span><label><input type="checkbox"> 不会</label></span>
        {%- else -%}
          <span class="w">{{ t.lead }}{{ t.core }}{{ t.trail }}</span>
        {%- endif -%}
        {{ ' ' }}
      {%- endfor -%}
    </p>
    <button class="primary" id="submit-drill">对答案</button>
    <div class="result" hidden></div>
  </section>
```

  - `app.js` 第二步：勾「不会」禁用并清空框；回车跳下一个可写的框，最后一个等于对答案；提交 `{segment, unit, answers: [{index, guess, unknown}], replays}` 到 `/api/dictation`；用 `el()` 拼结果（不插 HTML 字符串）：统计行、整句逐词着色、写错/不会的词逐个列出答案与释义；写错的「加入生词本」→ `POST /api/vocab`，成功后按钮变「已在生词本」；没装词典提示安装命令；照旧解锁跟读、收起这一步
  - `app.css`：`.dictation .box`（行内对齐）、等宽输入框、结果里的 `.mark.ok/.wrong/.unknown`、`.meaning`
- [ ] **Step 4: 跑 `tests/test_web.py`，确认通过**
- [ ] **Step 5: 提交** `feat: 练习页第二步改成整句默写，不会的词记进生词本`

---

### Task 5: 生词本页面和接口

**Files:** Modify `app.py`、`base.html`、`app.css`；Create `vocab.html`、`static/vocab.js`；Test `tests/test_web_vocab.py`

- [ ] **Step 1: 写失败的测试**（新文件）：每页有 `href="/vocab"`；空状态文案；手动加入两次 `times == 2`、页面显示「记过 2 次」和出处链接、移出后 404；删素材后原句还在但不再有链接；装了词典（用 `tests.test_dictionary._fetch`）时页面显示释义和原形
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**
  - 路由：

```python
@app.get("/vocab", response_class=HTMLResponse)
def vocab_page(request: Request):
    connection = _db()
    items = db.list_vocab(connection)
    entries = dictionary.lookup_many(item["word"] for item in items)
    for item in items:
        item["entry"] = entries.get(item["word"])
        item["first_day"] = datetime.fromisoformat(item["first_added"]).astimezone().strftime("%m-%d")
        for source in item["sources"]:
            alive = source["segment_id"] and db.get_segment(connection, source["segment_id"])
            source["link"] = (f"/practice/{source['segment_id']}/{source['unit_index']}"
                              if alive else None)
    return templates.TemplateResponse(
        request, "vocab.html", {"items": items, "dictionary": dictionary.installed()})


@app.post("/api/vocab")
def add_vocab_api(payload: dict = Body(...)):
    word = dictation.key(str(payload.get("word") or ""))
    if not word:
        raise HTTPException(400, "没有要记的词。")
    times = db.add_vocab(_db(), word, sentence=str(payload.get("sentence") or ""),
                         segment_id=payload.get("segment"), unit_index=payload.get("unit"))
    return {"word": word, "times": times}


@app.delete("/api/vocab/{word}")
def remove_vocab_api(word: str):
    if not db.remove_vocab(_db(), word):
        raise HTTPException(404, "生词本里没有这个词。")
    return {"removed": True}
```

  - `base.html` 顶栏素材库后面加 `<a href="/vocab" class="nav">生词本</a>`，脚本加 `vocab.js`
  - `vocab.html`：标题「生词本」+ 词数；没装词典的提示；空状态；每个词：单词、音标、「记过 N 次 · MM-DD 起」、「记住了」按钮、释义列表、原形行、出处列表（有链接就是链接）
  - `vocab.js`：点「记住了」→ `DELETE /api/vocab/{word}` → 移除这一条，列表空了就刷新
- [ ] **Step 4: 跑全部测试确认通过**
- [ ] **Step 5: 提交** `feat: 生词本页面——释义、出处、记住了`

---

### Task 6: 命令行

**Files:** Modify `src/shadow/cli.py`；Test `tests/test_cli.py`

- [ ] **Step 1: 写失败的测试**：`dict install` 打印词条数；已装时提示「已经装好」；`dict lookup graduated` 打印释义和「原形 graduate」；没装词典时 `lookup` 返回 1 并提示安装；`progress` 里默写那一行显示「默写 2/4」和「不会 1」
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现** `cmd_dict`（install 带下载进度，失败打印原因返回 1；lookup 打印音标、义项、原形），解析器加 `dict` 子命令（`action` ∈ install/lookup、可选 `word`、`--force`）；`cmd_progress` 里填空那段改成「默写 correct/total · 不会 N · 重听」
- [ ] **Step 4: 跑测试确认通过**
- [ ] **Step 5: 提交** `feat: 命令行安装、查词；progress 显示默写统计`

---

### Task 7: 删掉挖空选词

**Files:** Delete `drill/gapfill.py`、`drill/blanks.py`、`tests/test_gapfill.py`、`tests/test_blanks.py`；Modify `models.py`、`ingest/pipeline.py`、`web/app.py`（`_sentences` 的 `blanks`）、`templates/index.html`（「空」列）、`cli.py`（`units` 空数）、`db.py`（`set_gapfill`）；Tests `test_models.py`、`test_pipeline.py`、`test_db.py`、`test_web.py`

- [ ] **Step 1:** 删文件；`Word` 去掉 `is_blank`，`words_to_json` 不再写、`words_from_json` 忽略旧字段，删 `with_blanks`；`pipeline` 删 `_apply_blanks` 和相关 import；`_sentences` 去掉 `blanks`，`index.html` 去掉「空」表头和单元格；`cmd_units` 输出去掉空数；删 `db.set_gapfill`
- [ ] **Step 2:** 测试随之调整：`test_models` 删 `with_blanks` 测试、往返测试不再带 `is_blank`，另加「旧数据里的 is_blank 读的时候忽略」；`test_pipeline` 删 `test_import_marks_blanks_on_segments` 并改掉夹具说明；`test_db` 去掉 `is_blank`、`set_gapfill` 换成 `set_dictation`；`test_web` 的 `_seed` 去掉 `is_blank`，`_seed_without_blanks` 改名 `_seed_other_source`
- [ ] **Step 3:** 全部测试通过；`grep -rn "is_blank\|blanks_of\|select_blanks\|gapfill\.py" src tests` 只剩数据库列名
- [ ] **Step 4:** 提交 `refactor: 删掉挖空选词——改成整句默写后用不上了`

---

### Task 8: 装词典和真机验证

- [ ] **Step 1:** `uv run shadow dict install`（用户已同意下载 ecdict.csv，约 66 MB）；`uv run shadow dict lookup graduated` 核对原形、`lookup Jobs` 核对大小写
- [ ] **Step 2:** 用独立数据目录（软链接真实词库）起测试服务，浏览器里做一句默写：勾「不会」、写错一个、对答案；看释义、「加入生词本」、生词本页面、「记住了」
- [ ] **Step 3:** 手机宽度看默写框换行和结果
- [ ] **Step 4:** 检查真实服务首页和练习页正常；停掉测试服务；汇报
