"""词块图的几何：算在哪画、画多宽，不碰任何绘图库。

抽出来是因为同一份图有两个渲染端——命令行出 PNG，网页直接画 DOM。
数字只能有一份，否则两边会各自漂移。

网页那端不用图片：PNG 里的字随图缩放，页面一宽字就变得极小；
DOM 里的字是页面字号，跟容器宽度无关。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..analysis.prosody import Prosody, word_trace
from ..analysis.rhythm import Rhythm
from ..models import Word

LAG_STEP_SEC = 0.15      # 落后量变化超过这个才标注，否则每个词都标太吵
MIN_BLOCK_SEC = 0.02     # 再短的词也得看得见
MIN_SLOT_WIDTH = 0.002
SLOT_PAD = 0.004
TRIM = ".,!?"


@dataclass(frozen=True, slots=True)
class Flag:
    """音高图上要标红的词。"""

    usr_index: int
    text: str


@dataclass(frozen=True, slots=True)
class PauseNote:
    """节奏图上要标出的停顿问题。"""

    ref_index: int
    usr_index: int | None
    kind: str
    flag: str


@dataclass(frozen=True, slots=True)
class Block:
    """节奏图里的一个词块，秒为单位，相对本行第一个词。"""

    text: str
    start: float
    width: float


@dataclass(frozen=True, slots=True)
class Lag:
    """一条落后连线：原声在 ref_at 秒说到这个词，你在 usr_at 秒才说到。"""

    ref_at: float
    usr_at: float
    seconds: float
    marked: bool         # 只有明显变化的那几条才标数字


@dataclass(frozen=True, slots=True)
class Span:
    """一段该停没停 / 停过头的区间。"""

    row: str             # ref | usr
    start: float
    end: float
    flag: str


@dataclass(frozen=True, slots=True)
class RhythmView:
    ref: tuple[Block, ...]
    usr: tuple[Block, ...]
    lags: tuple[Lag, ...]
    spans: tuple[Span, ...]
    seconds: float


@dataclass(frozen=True, slots=True)
class Slot:
    """音高图里的一格：一个词占一格，宽度是相对时长，走向是半音序列。

    存整条走向而不是首尾两个数：句尾降调常是「先扬后抑」，
    两点摘要会把它画成上扬，与耳朵听到的相反。
    走向里的 None 是无浊音的段（清辅音、气声），画的时候断开。
    """

    text: str
    x: float
    ref_width: float
    usr_width: float
    ref_trace: tuple[float | None, ...]
    usr_trace: tuple[float | None, ...]
    flag: str | None


def lag_annotations(
    lags: Sequence[tuple[int, float]], *, step: float = LAG_STEP_SEC
) -> tuple[tuple[int, float], ...]:
    """只在落后量明显变化处标注。全标会把图糊掉。"""
    marked: list[tuple[int, float]] = []
    last = 0.0
    for ref_index, lag in lags:
        if abs(lag - last) >= step:
            marked.append((ref_index, lag))
            last = lag
    return tuple(marked)


def blocks_of(words: Sequence[Word]) -> tuple[Block, ...]:
    origin = words[0].start
    return tuple(
        Block(text=w.text.strip(TRIM), start=w.start - origin,
              width=max(w.duration, MIN_BLOCK_SEC))
        for w in words
    )


def _pause_span(note, ref_words, usr_words, ref_origin, usr_origin) -> Span | None:
    if note.kind == "missed_pause":
        # 该停没停：标在原声的空隙上——你本该在这里停
        if note.ref_index + 1 >= len(ref_words):
            return None
        return Span(row="ref", flag=note.flag,
                    start=ref_words[note.ref_index].end - ref_origin,
                    end=ref_words[note.ref_index + 1].start - ref_origin)
    # 停过头 / 多停一下：标在你自己那段过长的静音上
    if note.usr_index is None or note.usr_index + 1 >= len(usr_words):
        return None
    return Span(row="usr", flag=note.flag,
                start=usr_words[note.usr_index].end - usr_origin,
                end=usr_words[note.usr_index + 1].start - usr_origin)


def rhythm_view(
    *, ref_words: Sequence[Word], usr_words: Sequence[Word], rhythm: Rhythm,
    pause_notes: Sequence = (),
) -> RhythmView:
    ref_origin = ref_words[0].start
    usr_origin = usr_words[0].start
    marked = {index for index, _ in lag_annotations(rhythm.lags)}
    lags = tuple(
        Lag(ref_at=ref_words[index].start - ref_origin,
            usr_at=ref_words[index].start - ref_origin + lag,
            seconds=lag, marked=index in marked)
        for index, lag in rhythm.lags
    )
    spans = tuple(
        span for span in (
            _pause_span(note, ref_words, usr_words, ref_origin, usr_origin)
            for note in pause_notes
        ) if span is not None
    )
    return RhythmView(
        ref=blocks_of(ref_words), usr=blocks_of(usr_words), lags=lags, spans=spans,
        seconds=max(rhythm.ref_span, rhythm.usr_span),
    )


def pitch_slots(
    *, ref_words: Sequence[Word], usr_words: Sequence[Word],
    pairs: Sequence[tuple[int, int]], ref_prosody: Prosody, usr_prosody: Prosody,
    flags: Sequence = (),
) -> tuple[Slot, ...]:
    """一词一格。格子按相对时长排开，横轴不再是真实秒数——那是图 1 的事。"""
    ref_span = (ref_words[-1].end - ref_words[0].start) or 1.0
    usr_span = ((usr_words[-1].end - usr_words[0].start) if usr_words else 1.0) or 1.0
    matched = dict(pairs)
    flagged = {f.usr_index: f.text for f in flags}

    placed: list[tuple[float, float, float, int, int | None]] = []
    cursor = 0.0
    for index, word in enumerate(ref_words):
        ref_width = word.duration / ref_span
        usr_index = matched.get(index)
        usr_width = (usr_words[usr_index].duration / usr_span
                     if usr_index is not None else 0.0)
        placed.append((cursor, ref_width, usr_width, index, usr_index))
        gap = ((ref_words[index + 1].start - word.end) / ref_span
               if index + 1 < len(ref_words) else 0.0)
        cursor += max(ref_width, usr_width) + gap + SLOT_PAD
    total = cursor or 1.0

    slots = []
    for start, ref_width, usr_width, index, usr_index in placed:
        word = ref_words[index]
        usr_trace: tuple[float | None, ...] = ()
        if usr_index is not None:
            usr = usr_words[usr_index]
            usr_trace = word_trace(usr_prosody, usr.start, usr.end)
        slots.append(Slot(
            text=word.text.strip(TRIM),
            x=start / total,
            ref_width=max(ref_width / total, MIN_SLOT_WIDTH),
            usr_width=(max(usr_width / total, MIN_SLOT_WIDTH)
                       if usr_index is not None else 0.0),
            ref_trace=word_trace(ref_prosody, word.start, word.end),
            usr_trace=usr_trace,
            flag=flagged.get(usr_index) if usr_index is not None else None,
        ))
    return tuple(slots)
