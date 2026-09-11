"""把若干次录音评成一份反馈。

只做编排：转写、对齐、diff、节奏、韵律、建议、汇总，全部复用现有模块。
出图的事交给浏览器——几何在 report/geometry.py，画在 static/figures.js。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Generator, Sequence

from .analysis.diff import accuracy as diff_accuracy
from .analysis.align import align_words
from .analysis.diff import diff_words, matched_pairs, unreliable_indices
from .analysis.prosody import analyse
from .analysis.rhythm import alignment_drift, analyse_rhythm, snap_first_word
from .ingest.transcriber import transcribe_words
from .models import Word
from .report.advice import PAUSE_KINDS, build_advice, well_done
from .report.geometry import Flag, PauseNote
from .report.takes import TakeMetrics, TakeSummary, summarise

ALIGNMENT_TOLERANCE_SEC = 1.0


@dataclass(frozen=True, slots=True)
class Step:
    """一步开工的通知。done 是这步开始前已完成的步数，画进度条用。"""

    stage: str          # reference | take
    done: int
    total: int
    index: int = 0      # 第几遍，stage == "take" 时才有意义


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
    skipped: tuple[tuple[int, str, float], ...]   # (第几遍, 文件名, 晚了多少秒)
    shaky: frozenset[int]
    ref_words: tuple[Word, ...]
    ref_prosody: object

    @property
    def best(self) -> Take:
        return self.takes[self.summary.representative]


def run(ref_path: Path, ref_words: Sequence[Word], paths: Sequence[Path],
        *, transcribe=None) -> Generator[Step, None, "Review | None"]:
    """跑完整条链路，每一步开工前先 yield 一个 Step，最后 return 结果。

    做成生成器而不是回调：回调没法把进度往上抛给正在流式输出的调用方，
    生成器可以，调用方要不要理会进度随它。return 值 None 表示所有录音的
    时间戳都对不上，没法比较。

    转写器显式传入：调用方（命令行/网页）各自持有自己的引用，
    测试打桩才盖得住这条链路。
    """
    # 默认值必须在运行时解析：写成默认参数的话，绑定发生在函数定义时，
    # 事后 patch 模块属性就盖不住了。
    transcribe = transcribe or transcribe_words
    total = len(paths) + 1

    yield Step(stage="reference", done=0, total=total)
    ref_prosody = analyse(ref_path)
    # 首词起点常被转写往前铺到片段开头，对到真正的发声点上
    ref_words = snap_first_word(ref_words, ref_prosody)
    # 库内文本来自长上下文转写，可能把缩读还原成完整形式，与音频对不上。
    # 这些词不能用来判用户对错。
    shaky = unreliable_indices(
        [w.text for w in ref_words],
        [w.text for w in transcribe(ref_path)],
    )

    takes: list[Take] = []
    metrics: list[TakeMetrics] = []
    skipped: list[tuple[int, str, float]] = []
    for index, path in enumerate(paths, 1):
        yield Step(stage="take", done=index, total=total, index=index)
        words = transcribe(path)
        prosody = analyse(path)
        drift = alignment_drift(words, prosody)
        if drift is not None and drift > ALIGNMENT_TOLERANCE_SEC:
            skipped.append((index, path.name, drift))
            continue
        # 转写给的词边界是猜的，逐词判定全靠它，能对齐就重算一遍。
        # 要在 alignment_drift 判过之后再动，先动的话那道防线就永远查不出错位。
        words = align_words(path, words) or words
        words = snap_first_word(words, prosody)
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


def evaluate(ref_path: Path, ref_words: Sequence[Word], paths: Sequence[Path],
             *, transcribe=None) -> Review | None:
    """不关心进度的调用方用这个：把 run 跑到底，只要结果。"""
    steps = run(ref_path, ref_words, paths, transcribe=transcribe)
    while True:
        try:
            next(steps)
        except StopIteration as stop:
            return stop.value


def flags_for(review: Review, limit: int, take=None):
    """给图 2 标红的词，以及图 1 的停顿标记。"""
    take = take or review.best
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


def good_words(review: Review) -> tuple[str, ...]:
    take = review.best
    return well_done(ref_words=review.ref_words, usr_words=take.words,
                     tokens=take.tokens, rhythm=take.rhythm, advice=take.advice)
