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
