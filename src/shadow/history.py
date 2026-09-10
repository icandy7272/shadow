"""上一次练某一句留下的东西。

只给「跟读」那一步用：里面必然含句子原文的片段，提前显示会毁掉盲听和填空。
也刻意不带指标数字——开口前看见「上次 91%」，人会去够那个数，
而这个工具的前提是模仿声音，不是刷指标。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from . import db
from .report.takes import recurrence_threshold


@dataclass(frozen=True, slots=True)
class Practice:
    times: int                  # 这句一共练过几轮（录了音的）
    when: str                   # 上一轮的日期，YYYY-MM-DD
    issues: tuple[str, ...]     # 上一轮反复出现的问题


def _local_date(stamp: str) -> str:
    try:
        return datetime.fromisoformat(stamp).astimezone().strftime("%Y-%m-%d")
    except ValueError:
        return stamp[:10]


def last_practice(connection, segment_id: int, unit_index: int) -> Practice | None:
    """没练过、或练了但没录音，都返回 None。"""
    rounds = [
        (row, metrics)
        for row in db.list_runs(connection, segment_id=segment_id,
                                unit_index=unit_index)
        if (metrics := db.run_metrics(connection, row["id"]))
    ]
    if not rounds:
        return None

    row, metrics = rounds[-1]
    counted = Counter(
        issue["title"] for take in metrics for issue in take.get("issues", ())
    )
    threshold = recurrence_threshold(len(metrics))
    issues = tuple(
        title for title, hits in counted.most_common() if hits >= threshold
    )
    return Practice(
        times=len(rounds),
        when=_local_date(row["finished_at"] or row["started_at"]),
        issues=issues,
    )
