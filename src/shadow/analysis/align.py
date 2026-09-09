"""词锚点分段线性时间弯折。纯函数，无 IO。

不用帧级 DTW：90 秒片段是 9000x9000 的 DP，纯 Python 跑不动。而 diff 已经给出了
词级对应关系，用匹配词的中点作锚点做分段线性插值即可，O(n) 且锚点带语言学意义。
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

from ..models import Word

MIN_ANCHORS = 3


def _centre(word: Word) -> float:
    return 0.5 * (word.start + word.end)


def build_anchors(
    *,
    ref_words: Sequence[Word],
    usr_words: Sequence[Word],
    pairs: Sequence[tuple[int, int]],
    ref_duration: float,
    usr_duration: float,
) -> tuple[np.ndarray, np.ndarray]:
    """返回 (用户时间锚点, 原声时间锚点)，含首尾端点，严格递增。"""
    candidates = [(0.0, 0.0)]
    for ref_index, usr_index in pairs:
        candidates.append((_centre(usr_words[usr_index]), _centre(ref_words[ref_index])))
    candidates.append((usr_duration, ref_duration))

    xs: list[float] = []
    ys: list[float] = []
    for x, y in candidates:
        if xs and (x <= xs[-1] or y <= ys[-1]):
            continue
        xs.append(float(x))
        ys.append(float(y))
    return np.asarray(xs), np.asarray(ys)


def warp_user_times(
    usr_times,
    *,
    ref_words: Sequence[Word],
    usr_words: Sequence[Word],
    pairs: Sequence[tuple[int, int]],
    ref_duration: float,
    usr_duration: float,
) -> np.ndarray:
    """把用户时间轴映射到原声时间轴。"""
    times = np.asarray(usr_times, dtype=float)

    if len(pairs) < MIN_ANCHORS:
        scale = ref_duration / usr_duration if usr_duration > 0 else 1.0
        return times * scale

    xs, ys = build_anchors(
        ref_words=ref_words,
        usr_words=usr_words,
        pairs=pairs,
        ref_duration=ref_duration,
        usr_duration=usr_duration,
    )
    if xs.size < 2:
        scale = ref_duration / usr_duration if usr_duration > 0 else 1.0
        return times * scale
    return np.interp(times, xs, ys)
