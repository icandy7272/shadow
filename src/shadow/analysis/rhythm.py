"""节奏分析：发声时长、停顿分布、累积落后。纯函数，无 IO。

关键在于把「发声」和「停顿」分开算。两者的偏差方向常常相反，在总时长上
互相抵消——实测中用户发声慢 16%、停顿少 40%，总时长只差 8%，
一个「整体语速」数字会把真正的问题完全藏住。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..models import Word

MIN_PAUSE_SEC = 0.15


@dataclass(frozen=True, slots=True)
class PauseGap:
    ref_index: int
    usr_index: int | None
    text: str
    ref_gap: float
    usr_gap: float | None

    @property
    def overdone(self) -> bool:
        """停得比原声明显久，或者原声根本没停的地方你停了。

        停过头和不停一样是毛病——句子会被拉散，听起来一顿一顿的。
        """
        if self.usr_gap is None:
            return False
        excess = self.usr_gap - self.ref_gap
        return excess >= MIN_PAUSE_SEC and self.usr_gap > self.ref_gap * 1.5

    @property
    def missed(self) -> bool:
        """原声有停顿而用户几乎没停。"""
        return (
            self.ref_gap >= MIN_PAUSE_SEC
            and self.usr_gap is not None
            and self.usr_gap < self.ref_gap * 0.5
        )


@dataclass(frozen=True, slots=True)
class Rhythm:
    ref_span: float
    usr_span: float
    ref_speech: float
    usr_speech: float
    gaps: tuple[PauseGap, ...]
    lags: tuple[tuple[int, float], ...]

    @property
    def ref_pause(self) -> float:
        return self.ref_span - self.ref_speech

    @property
    def usr_pause(self) -> float:
        return self.usr_span - self.usr_speech

    @property
    def speech_ratio(self) -> float:
        return self.usr_speech / self.ref_speech if self.ref_speech > 0 else 1.0

    @property
    def pause_ratio(self) -> float | None:
        return self.usr_pause / self.ref_pause if self.ref_pause > 0 else None

    @property
    def span_ratio(self) -> float:
        return self.usr_span / self.ref_span if self.ref_span > 0 else 1.0


def span(words: Sequence[Word]) -> float:
    """首词起点到末词终点。不用文件时长——录音尾部的静音会把它撑大。"""
    return words[-1].end - words[0].start if words else 0.0


def speech_time(words: Sequence[Word]) -> float:
    return sum(word.duration for word in words)


def analyse_rhythm(
    ref_words: Sequence[Word],
    usr_words: Sequence[Word],
    pairs: Sequence[tuple[int, int]],
) -> Rhythm:
    matched = dict(pairs)
    gaps: list[PauseGap] = []
    for index in range(len(ref_words) - 1):
        ref_gap = ref_words[index + 1].start - ref_words[index].end
        usr_index = matched.get(index)
        usr_gap = None
        if usr_index is not None and usr_index + 1 < len(usr_words):
            usr_gap = usr_words[usr_index + 1].start - usr_words[usr_index].end
        gaps.append(
            PauseGap(
                ref_index=index,
                usr_index=usr_index,
                text=ref_words[index].text,
                ref_gap=ref_gap,
                usr_gap=usr_gap,
            )
        )

    lags: list[tuple[int, float]] = []
    if ref_words and usr_words:
        ref_origin, usr_origin = ref_words[0].start, usr_words[0].start
        for ref_index, usr_index in pairs:
            lag = (usr_words[usr_index].start - usr_origin) - (
                ref_words[ref_index].start - ref_origin
            )
            lags.append((ref_index, lag))

    return Rhythm(
        ref_span=span(ref_words),
        usr_span=span(usr_words),
        ref_speech=speech_time(ref_words),
        usr_speech=speech_time(usr_words),
        gaps=tuple(gaps),
        lags=tuple(sorted(lags)),
    )
