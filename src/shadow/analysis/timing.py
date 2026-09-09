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
