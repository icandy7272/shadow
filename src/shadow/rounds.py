"""认出被拆成好几行的同一轮练习。纯函数，不碰数据库。

网页原来没把这一轮的编号在三步之间传下去：打分一行、默写一行、跟读一行。
「练过 N 次」因此被放大成三倍，今天新练的句子还被当成复习过的，占掉当天的名额。
页面已经改好；这里认出旧记录里的同一轮，交给 db.merge_runs 并回去。

怎么算同一轮：同一句，步骤按「盲听打分 → 默写 → 跟读」往后走，没有哪一步做了
两次，前后两行相隔不超过 ROUND_GAP。打了分又打分、跟读完了再打分，都是下一轮。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

LISTEN, DRILL, RECORD = "listen", "drill", "record"
_ORDER = {LISTEN: 0, DRILL: 1, RECORD: 2}
ROUND_GAP = timedelta(minutes=30)     # 三步通常几分钟内做完；再久就是另找时间练的了


@dataclass(frozen=True, slots=True)
class Row:
    id: int
    unit: tuple[int, int, str]        # (片段, 单元, 原文)：同一句才可能是同一轮
    started: datetime
    steps: frozenset[str]             # 这一行里做了哪几步；空的是中途取消留下的


def merges(rows: Sequence[Row], *, gap: timedelta = ROUND_GAP) -> list[list[int]]:
    """该并成一行的那几组编号，每组按时间先后。只有一行的组不用并，不列出来。"""
    groups: list[list[int]] = []
    current: list[Row] = []

    def close() -> None:
        if len(current) > 1:
            groups.append([row.id for row in current])

    for row in sorted(rows, key=lambda r: (r.unit[0], r.unit[1], r.unit[2] or "",
                                           r.started, r.id)):
        if not row.steps:
            continue                  # 空行本来就不算练过，不碰它，也不打断前后
        if current and _joins(current, row, gap):
            current.append(row)
            continue
        close()
        current = [row]
    close()
    return groups


def _joins(group: list[Row], row: Row, gap: timedelta) -> bool:
    last = group[-1]
    if row.unit != last.unit or row.started - last.started > gap:
        return False
    done = frozenset().union(*(member.steps for member in group))
    if done & row.steps:
        return False                  # 这一步做过了，是下一轮
    return min(_ORDER[step] for step in row.steps) > max(_ORDER[step] for step in done)
