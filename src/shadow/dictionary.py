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
    # 默认值在运行时解析：测试要能换掉下载
    fetch = fetch or download
    if installed() and not force:
        return None
    with tempfile.TemporaryDirectory() as folder:
        csv_path = Path(folder) / "ecdict.csv"
        fetch(SOURCE_URL, csv_path, report=report)
        return build(csv_path, path())


def _read(connection: sqlite3.Connection, word: str):
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
