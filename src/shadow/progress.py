"""每日练习格子。

鼓励的是「今天练了没有」，不是总量——所以格子只铺最近几周，不铺一整年。
刚开始练的时候，一整年的空格子是劝退，不是激励。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from . import db

LEVELS = 4          # 颜色深浅的档数


@dataclass(frozen=True, slots=True)
class Day:
    date: str            # YYYY-MM-DD，本地时区
    sentences: int       # 练了几句（同一句练多轮只算一句）
    rounds: int          # 一共几轮
    level: int           # 0 到 LEVELS，按当期最忙的一天分档
    future: bool         # 本周还没到的日子，占位用


@dataclass(frozen=True, slots=True)
class Calendar:
    days: tuple[Day, ...]     # 从早到晚，整周整周地排；本周未到的日子占位
    today: int
    streak: int
    week: int                 # 最近七天练了几句


def _local_day(stamp: str) -> str | None:
    try:
        return datetime.fromisoformat(stamp).astimezone().strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return None


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


def calendar(connection, *, weeks: int = 10) -> Calendar:
    by_day, rounds = _practised(connection)
    today = datetime.now().astimezone().date()
    # 补到整周：最后一列是本周，第一格落在周一
    start = today - timedelta(days=weeks * 7 - 1)
    start -= timedelta(days=start.weekday())          # 第一格落在周一
    end = today + timedelta(days=6 - today.weekday())  # 补到本周日

    spans = [start + timedelta(days=offset)
             for offset in range((end - start).days + 1)]
    busiest = max((len(by_day.get(day.isoformat(), ())) for day in spans), default=0)

    days = []
    for day in spans:
        key = day.isoformat()
        sentences = len(by_day.get(key, ()))
        days.append(Day(
            date=key, sentences=sentences, rounds=rounds.get(key, 0),
            level=0 if not sentences else _level(sentences, busiest),
            future=day > today,
        ))

    return Calendar(
        days=tuple(days),
        today=len(by_day.get(today.isoformat(), ())),
        streak=_streak(by_day, today),
        week=sum(len(by_day.get((today - timedelta(days=n)).isoformat(), ()))
                 for n in range(7)),
    )


def _level(sentences: int, busiest: int) -> int:
    if busiest <= 1:
        return LEVELS
    share = (sentences - 1) / (busiest - 1)
    return 1 + min(LEVELS - 1, int(share * LEVELS))


def _streak(by_day: dict[str, set[str]], today: date) -> int:
    """今天还没练不算断。早上一打开就显示 0，会劝退。"""
    cursor = today if by_day.get(today.isoformat()) else today - timedelta(days=1)
    count = 0
    while by_day.get(cursor.isoformat()):
        count += 1
        cursor -= timedelta(days=1)
    return count
