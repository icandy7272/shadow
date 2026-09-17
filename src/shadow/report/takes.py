"""多次录音的汇总。纯函数，无 IO。

单次录音的随机波动可能和真实进步同量级——实测句尾升降的标准差 1.68，
而目标值只有 −5.0。拿一次读数下结论会把噪声当成进步。

所以：只报**在多数 take 里都出现**的问题，并给出中位数与范围。
离散度本身也是信息：同一句每次读得都不一样，说明还没形成稳定的运动模式。
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Sequence

from .advice import Advice


@dataclass(frozen=True, slots=True)
class TakeMetrics:
    accuracy: float
    speech_ratio: float
    pause_ratio: float | None
    advice: tuple[Advice, ...]


@dataclass(frozen=True, slots=True)
class Spread:
    median: float
    low: float
    high: float

    @property
    def width(self) -> float:
        return self.high - self.low


@dataclass(frozen=True, slots=True)
class ConsistentIssue:
    hits: int
    total: int
    score: float
    advice: Advice

    @property
    def always(self) -> bool:
        return self.hits == self.total


@dataclass(frozen=True, slots=True)
class TakeSummary:
    count: int
    accuracy: Spread
    speech_ratio: Spread
    pause_ratio: Spread | None
    issues: tuple[ConsistentIssue, ...]
    representative: int


ACCURACY_SLACK = 0.15    # 比最好的一遍低这么多，就不是同一次尝试了
PAUSE_OUTLIER = 2.0      # 停顿比同批中位数大这么多倍，多半是中间卡了一下
RATIO_FLOOR = 0.05       # 完全没停顿时比值是 0，取对数前垫一下


def _representative(takes: Sequence[TakeMetrics], speech, typical: float) -> int:
    """画图和逐词试听都取这一遍，所以先把念砸的排除掉，再挑最有代表性的。

    原来只按「语速最接近中位数」挑。实测三遍里卡壳那遍停顿是原声的 5.3 倍，
    语速却正好居中，于是被选中——整张图和逐词试听全来自那一遍。
    指标本身仍是全部遍数的中位数，不受这里影响。
    """
    best = max(take.accuracy for take in takes)
    clean = [index for index, take in enumerate(takes)
             if take.accuracy >= best - ACCURACY_SLACK]

    pauses = [takes[index].pause_ratio for index in clean
              if takes[index].pause_ratio is not None]
    if len(pauses) > 2:
        limit = statistics.median(pauses) * PAUSE_OUTLIER
        steady = [index for index in clean
                  if takes[index].pause_ratio is None
                  or takes[index].pause_ratio <= limit]
        clean = steady or clean

    if len(clean) == 2:
        # 两遍没有中位可言：中位就是两遍的平均，两遍离它一样远，原来总落到第 1 遍，
        # 念砸的那遍照样入选。只能拿原声当尺子，挑节奏离原声近的
        return min(clean, key=lambda index: _off_reference(takes[index]))
    return min(clean, key=lambda index: abs(speech[index] - typical))


def _off_reference(take: TakeMetrics) -> float:
    """语速、停顿各自离原声差几倍。取对数：慢一倍和快一倍算一样远。"""
    def fold(ratio: float | None) -> float:
        return 0.0 if ratio is None else abs(math.log(max(ratio, RATIO_FLOOR)))
    return fold(take.speech_ratio) + fold(take.pause_ratio)


def _spread(values: Sequence[float]) -> Spread:
    return Spread(median=statistics.median(values), low=min(values), high=max(values))


def recurrence_threshold(total: int, *, min_share: float = 0.5) -> int:
    """犯几次才算「反复出现」。

    两遍时「半数以上」等于「出现过一次」，没有任何过滤作用。只有一遍时无从判断
    一致性，只能全报；两遍及以上至少要犯两次才算数。
    """
    return 1 if total == 1 else max(2, math.ceil(total * min_share))


def summarise(takes: Sequence[TakeMetrics], *, min_share: float = 0.5) -> TakeSummary:
    if not takes:
        raise ValueError("至少需要一次录音。")

    total = len(takes)
    speech = [t.speech_ratio for t in takes]
    speech_spread = _spread(speech)
    pauses = [t.pause_ratio for t in takes if t.pause_ratio is not None]

    grouped: dict[tuple[str, int], list[Advice]] = {}
    for take in takes:
        seen: set[tuple[str, int]] = set()
        for item in take.advice:
            key = (item.kind, item.ref_index)
            if key in seen:      # 同一 take 内不重复计数
                continue
            seen.add(key)
            grouped.setdefault(key, []).append(item)

    threshold = recurrence_threshold(total, min_share=min_share)
    issues = [
        ConsistentIssue(
            hits=len(items),
            total=total,
            score=statistics.median(item.score for item in items),
            advice=max(items, key=lambda item: item.score),
        )
        for items in grouped.values()
        if len(items) >= threshold
    ]
    # 一致性优先于严重度：3/3 次出现的问题比 2/3 次更值得改
    issues.sort(key=lambda issue: (-issue.hits, -issue.score))

    representative = _representative(takes, speech, speech_spread.median)

    return TakeSummary(
        count=total,
        accuracy=_spread([t.accuracy for t in takes]),
        speech_ratio=speech_spread,
        pause_ratio=_spread(pauses) if pauses else None,
        issues=tuple(issues),
        representative=representative,
    )
