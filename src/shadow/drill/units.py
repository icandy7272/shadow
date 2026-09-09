"""把片段再切成可跟读的练习单元。纯函数，无 IO。

素材单元（30-90s）是为了保住完整语义块；练习单元（3-8s）是为了能真的跟下来。
两者是不同粒度，不要混。

切法：优先在句末标点处断开，太短的往后并，单句超长的在内部最大停顿处再断。
"""

from __future__ import annotations

import re
from typing import Sequence

from .. import config
from ..models import Word

_SENTENCE_END = re.compile(r"[.!?]['\"]?$")


def _sentence_groups(words: Sequence[Word]) -> list[list[Word]]:
    groups: list[list[Word]] = []
    current: list[Word] = []
    for word in words:
        current.append(word)
        if _SENTENCE_END.search(word.text):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def _span(group: Sequence[Word]) -> float:
    return group[-1].end - group[0].start


def _split_overlong(group: list[Word], max_sec: float) -> list[list[Word]]:
    """单句超过上限时，在内部最大的词间停顿处对半断开，递归到不超限为止。"""
    if _span(group) <= max_sec or len(group) < 2 * config.UNIT_MIN_WORDS:
        return [group]

    low = config.UNIT_MIN_WORDS
    high = len(group) - config.UNIT_MIN_WORDS
    best_index = max(
        range(low, high + 1),
        key=lambda i: group[i].start - group[i - 1].end,
    )
    head, tail = group[:best_index], group[best_index:]
    return _split_overlong(head, max_sec) + _split_overlong(tail, max_sec)


def split_into_units(
    words: Sequence[Word],
    *,
    min_sec: float = config.UNIT_MIN_SEC,
    max_sec: float = config.UNIT_MAX_SEC,
    min_words: int = config.UNIT_MIN_WORDS,
) -> tuple[tuple[Word, ...], ...]:
    if not words:
        return ()

    merged: list[list[Word]] = []
    for group in _sentence_groups(list(words)):
        if merged and (
            _span(merged[-1]) < min_sec or len(merged[-1]) < min_words
        ):
            merged[-1].extend(group)
        else:
            merged.append(list(group))

    # 末尾单元可能仍然过短，并回前一个
    if len(merged) >= 2 and (
        _span(merged[-1]) < min_sec or len(merged[-1]) < min_words
    ):
        tail = merged.pop()
        merged[-1].extend(tail)

    units: list[list[Word]] = []
    for group in merged:
        units.extend(_split_overlong(group, max_sec))
    return tuple(tuple(unit) for unit in units)
