"""把若干次录音评成一份反馈。命令行与网页共用同一条链路。

只做编排：转写、diff、节奏、韵律、建议、汇总、出图，全部复用现有模块。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .analysis.diff import accuracy as diff_accuracy
from .analysis.diff import diff_words, matched_pairs, unreliable_indices
from .analysis.prosody import analyse
from .analysis.rhythm import alignment_drift, analyse_rhythm
from .ingest.transcriber import transcribe_words
from .models import Word
from .report.advice import PAUSE_KINDS, build_advice, well_done
from .report.blocks import Flag, PauseNote, render_feedback
from .report.takes import TakeMetrics, TakeSummary, summarise

ALIGNMENT_TOLERANCE_SEC = 1.0


@dataclass(frozen=True, slots=True)
class Take:
    path: Path
    words: tuple[Word, ...]
    tokens: tuple
    rhythm: object
    prosody: object
    advice: tuple


@dataclass(frozen=True, slots=True)
class Review:
    summary: TakeSummary
    takes: tuple[Take, ...]
    skipped: tuple[tuple[str, float], ...]
    shaky: frozenset[int]
    ref_words: tuple[Word, ...]
    ref_prosody: object

    @property
    def best(self) -> Take:
        return self.takes[self.summary.representative]


def evaluate(ref_path: Path, ref_words: Sequence[Word], paths: Sequence[Path],
             *, transcribe=None) -> Review | None:
    """None 表示所有录音的时间戳都对不上，没法比较。

    转写器显式传入：调用方（命令行/网页）各自持有自己的引用，
    测试打桩才盖得住这条链路。
    """
    # 默认值必须在运行时解析：写成默认参数的话，绑定发生在函数定义时，
    # 事后 patch 模块属性就盖不住了。
    transcribe = transcribe or transcribe_words
    ref_prosody = analyse(ref_path)
    # 库内文本来自长上下文转写，可能把缩读还原成完整形式，与音频对不上。
    # 这些词不能用来判用户对错。
    shaky = unreliable_indices(
        [w.text for w in ref_words],
        [w.text for w in transcribe(ref_path)],
    )

    takes: list[Take] = []
    metrics: list[TakeMetrics] = []
    skipped: list[tuple[str, float]] = []
    for path in paths:
        words = transcribe(path)
        prosody = analyse(path)
        drift = alignment_drift(words, prosody)
        if drift is not None and drift > ALIGNMENT_TOLERANCE_SEC:
            skipped.append((path.name, drift))
            continue
        tokens = diff_words([w.text for w in ref_words], [w.text for w in words])
        rhythm = analyse_rhythm(ref_words, words, matched_pairs(tokens))
        advice = build_advice(
            ref_words=ref_words, usr_words=words, tokens=tokens, rhythm=rhythm,
            ref_prosody=ref_prosody, usr_prosody=prosody,
        )
        takes.append(Take(path, words, tokens, rhythm, prosody, advice))
        metrics.append(TakeMetrics(
            accuracy=diff_accuracy(tokens), speech_ratio=rhythm.speech_ratio,
            pause_ratio=rhythm.pause_ratio, advice=advice,
        ))

    if not metrics:
        return None
    return Review(summarise(metrics), tuple(takes), tuple(skipped), shaky,
                  tuple(ref_words), ref_prosody)


def flags_for(review: Review, limit: int):
    """给图 2 标红的词，以及图 1 的停顿标记。"""
    take = review.best
    by_text: dict[str, int] = {}
    for token in take.tokens:
        if token.kind == "equal" and token.usr_index is not None:
            by_text.setdefault(review.ref_words[token.ref_index].text, token.usr_index)
    flags = []
    for item in take.advice[:limit]:
        if item.kind in PAUSE_KINDS:
            continue
        for text, usr_index in by_text.items():
            if f"“{text}”" in item.title:
                flags.append(Flag(usr_index=usr_index, text=item.flag))
                break
    notes = tuple(
        PauseNote(ref_index=item.ref_index, usr_index=item.usr_index,
                  kind=item.kind, flag=item.flag)
        for item in take.advice[:limit] if item.kind in PAUSE_KINDS
    )
    return tuple(flags), notes


def chart(review: Review, out_path: Path, limit: int) -> Path:
    take = review.best
    flags, notes = flags_for(review, limit)
    return render_feedback(
        ref_words=review.ref_words, usr_words=take.words, tokens=take.tokens,
        rhythm=take.rhythm, ref_prosody=review.ref_prosody,
        usr_prosody=take.prosody, flags=flags, pause_notes=notes,
        accuracy=diff_accuracy(take.tokens),
        text=" ".join(w.text for w in review.ref_words), out_path=out_path,
    )


def good_words(review: Review) -> tuple[str, ...]:
    take = review.best
    return well_done(ref_words=review.ref_words, usr_words=take.words,
                     tokens=take.tokens, rhythm=take.rhythm, advice=take.advice)
