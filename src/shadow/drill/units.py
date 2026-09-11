"""把片段再切成可跟读的练习单元。纯函数，无 IO。

素材单元（30-90s）是为了保住完整语义块；练习单元（3-8s）是为了能真的跟下来。
两者是不同粒度，不要混。

切法：优先在句末标点处断开，太短的往后并，单句超长的在语言接缝处再断
（逗号 > 连词 > 最大停顿），切点只在中间那一带找，免得切出碎片。
"""

from __future__ import annotations

import re
from typing import Sequence

from .. import config
from ..models import Word

_SENTENCE_END = re.compile(r"[.!?]['\"]?$")
_CLAUSE_END = re.compile(r"[,;:—–]['\"]?$")

# 长句子的接缝：这些词前面断开，两半各自还成话。
# 只有这几个最稳；再多就会在 "a lawyer and his wife" 这种并列短语里乱切。
_SEAM_WORDS = frozenset({
    "and", "but", "so", "or", "because", "that", "which", "who", "when",
    "while", "if", "though", "although", "after", "before", "until", "since",
})
SEAM_BAND = 0.35        # 切点只在中间这一带里找，免得切出碎片。
                        # 太窄会把真正的接缝挡在外面——0.22 时
                        # "…replaced by the | lightness…" 就是这么来的

# 正常说话 2-4 词/秒，实测本仓库 221 个单元中位 3.4、最高 5.8。
# 超过 8 的一定是 Whisper 词级时间戳崩了——见过 13 个词挤在 0.56 秒里，
# 这种单元音频半秒、文本十几个词，完全没法练。
MAX_WORDS_PER_SEC = 8.0


# 断在这些词上，说明切点落在词组中间——两半都不成话
_DANGLING = frozenset({
    "of", "to", "the", "a", "an", "in", "on", "at", "for", "from", "with",
    "and", "or", "but", "my", "his", "her", "their", "your", "its", "that",
})


def ends_mid_phrase(unit: Sequence[Word]) -> bool:
    """切点落在词组中间了吗。

    单元以句末标点收尾就没问题；以功能词收尾说明这一刀切坏了。
    用来事后扫全库——只靠合成数据的单测，发现不了真素材里的切坏。
    """
    if not unit:
        return False
    last = unit[-1].text
    if _SENTENCE_END.search(last):
        return False
    return last.strip("\"'.,!?;:").lower() in _DANGLING


def words_per_second(unit: Sequence[Word]) -> float:
    duration = unit[-1].end - unit[0].start if unit else 0.0
    return len(unit) / duration if duration > 0 else float("inf")


def is_usable(unit: Sequence[Word]) -> bool:
    """时间戳崩掉的单元没法练，得先认出来。"""
    return bool(unit) and words_per_second(unit) <= MAX_WORDS_PER_SEC


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
    """单句超过上限时在内部断开，递归到不超限为止。"""
    if _span(group) <= max_sec or len(group) < 2 * config.UNIT_MIN_WORDS:
        return [group]

    low = config.UNIT_MIN_WORDS
    high = len(group) - config.UNIT_MIN_WORDS
    middle = len(group) / 2
    # 只在中间那一带找切点：逗号可能出现在第二个词后面，照切会留下两词碎片
    band = max(1, round(len(group) * SEAM_BAND))
    inner = [i for i in range(low, high + 1) if abs(i - middle) <= band]
    candidates = inner or list(range(low, high + 1))

    # 先看语言上的接缝，再看停顿。切在 "graduated / from college" 中间，
    # 两半都不成话；切在 "and" 前面才是这句真正的缝。
    # 间隔相同时切在中间，别切在最靠前的位置。词级时间戳崩掉时所有间隔
    # 都是 0（见过 13 个词挤在同一毫秒），只按间隔取最大会切出两词碎片。
    def score(i: int):
        after = group[i - 1].text
        before = group[i].text.strip("\"'").lower()
        return (
            1 if _CLAUSE_END.search(after) else 0,
            1 if before in _SEAM_WORDS else 0,
            group[i].start - group[i - 1].end,
            -abs(i - middle),
        )

    best_index = max(candidates, key=score)
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
