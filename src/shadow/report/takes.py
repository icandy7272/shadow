"""多次录音的汇总。纯函数，无 IO。

单次录音的随机波动可能和真实进步同量级——实测句尾升降的标准差 1.68，
而目标值只有 −5.0。拿一次读数下结论会把噪声当成进步。

所以：只报**在多数 take 里都出现**的问题，并给出中位数与范围。
离散度本身也是信息：同一句每次读得都不一样，说明还没形成稳定的运动模式。
"""

from __future__ import annotations

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


def _spread(values: Sequence[float]) -> Spread:
    return Spread(median=statistics.median(values), low=min(values), high=max(values))


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

    threshold = max(1, round(total * min_share))
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

    representative = min(
        range(total),
        key=lambda index: abs(speech[index] - speech_spread.median),
    )

    return TakeSummary(
        count=total,
        accuracy=_spread([t.accuracy for t in takes]),
        speech_ratio=speech_spread,
        pause_ratio=_spread(pauses) if pauses else None,
        issues=tuple(issues),
        representative=representative,
    )
