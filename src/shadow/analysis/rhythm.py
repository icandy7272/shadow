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


def _runs(flags) -> list[tuple[int, int]]:
    """连续为真的区段，返回 [(起, 止)]，止是闭区间。"""
    spans: list[tuple[int, int]] = []
    start = None
    for index, flag in enumerate(flags):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            spans.append((start, index - 1))
            start = None
    if start is not None:
        spans.append((start, len(flags) - 1))
    return spans


def speech_region(prosody, *, floor_db: float = None) -> tuple[float, float] | None:
    """从波形能量找出实际发声的起止，与转写时间戳无关。

    两端那种「又短又跟主体隔着一段」的小块会被扔掉：开口前的咂嘴、呼吸、
    椅子响都长这样。不扔的话它就成了发声起点，整段测量跟着前移，
    说话时长凭空变长——实测有一遍录音，真正开口在 0.64 秒，
    而 0.06 秒处的一声杂音把起点拽到了那里。
    """
    import numpy as np

    from .. import config

    threshold = config.SPEECH_FLOOR_DB if floor_db is None else floor_db
    spans = _runs(prosody.energy_db > threshold)
    if not spans:
        return None

    step = (float(prosody.times[1] - prosody.times[0])
            if prosody.times.size > 1 else 0.01)
    short = config.SPEECH_EDGE_MIN_SEC
    gap = config.SPEECH_EDGE_GAP_SEC

    def trim(items):
        while len(items) > 1:
            low, high = items[0]
            after = items[1][0] - high - 1
            if (high - low + 1) * step >= short or after * step < gap:
                break
            items = items[1:]
        return items

    spans = trim(spans)
    spans = trim(spans[::-1])[::-1]
    return float(prosody.times[spans[0][0]]), float(prosody.times[spans[-1][1]])


def snap_first_word(words, prosody, *, tolerance: float = 0.05):
    """把首词起点对到真正的发声点，返回新序列。

    Whisper 常把第一个词的起点一直铺到片段开头：词块因此被撑长、位置偏早，
    同时播放两条音轨也对不齐，词内音高还会取到一段静音。
    只往后挪：发声早于首词起点意味着可能漏了词，那是另一回事。

    要在 alignment_drift 判过之后再用——先挪了，那道防线就永远查不出错位。
    """
    from dataclasses import replace

    if not words:
        return tuple(words)
    region = speech_region(prosody)
    if region is None:
        return tuple(words)
    onset = region[0]
    first = words[0]
    if onset <= first.start + tolerance or onset >= first.end:
        return tuple(words)
    return (replace(first, start=onset),) + tuple(words[1:])


def alignment_drift(words, prosody) -> float | None:
    """转写比实际发声晚了多少。None 表示无法判断。

    Whisper 的词级时间戳偶尔整体错位，此时每项测量都取自错误的音频位置，
    而结果看起来完全正常——只能靠这个偏差查出来。

    只看「晚」的一侧。录音开头空一两秒是常事：等提示音、深吸一口气，
    而 Whisper 惯于把首词起点铺到 0，两者之差看着很大，实际什么问题都没有，
    snap_first_word 会把起点对回来。为此丢掉一整遍录音，是这个判据最常见的
    误伤。真正危险的是转写晚于发声——那说明开头有词没进转写。
    """
    region = speech_region(prosody)
    if region is None or not words:
        return None
    return max(0.0, words[0].start - region[0])
