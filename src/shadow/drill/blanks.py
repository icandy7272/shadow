"""挖空选词。纯函数，无 IO。

不挖生词，专挖被弱读的功能词——用户听不懂的从来不是大词，而是
"should have been" 被读成 "shoulda bin"。
"""

from __future__ import annotations

import functools
import re
from typing import Sequence

from .. import config
from ..models import Word

FUNCTION_WORDS = frozenset(
    """
    a an the of to in for on at by with from as into onto over under about
    and or but nor so yet if then than when while because though although
    is are was were be been being am do does did done have has had having
    can could shall should will would may might must ought
    i you he she it we they me him her us them
    my your his its our their mine yours hers ours theirs
    this that these those there here what which who whom whose
    not no none nor up out off down just very too also only even still
    """.split()
)

_VOWEL_GROUPS = re.compile(r"[aeiouy]+")
_NON_WORD = re.compile(r"[^a-z']")


@functools.lru_cache(maxsize=1)
def _cmu() -> dict[str, list[list[str]]]:
    import cmudict

    return cmudict.dict()


def normalise(text: str) -> str:
    return _NON_WORD.sub("", text.lower())


def count_syllables(word: str) -> int:
    key = normalise(word)
    if not key:
        return 1
    entries = _cmu().get(key)
    if entries:
        counted = sum(1 for phone in entries[0] if phone[-1].isdigit())
        if counted:
            return counted
    groups = len(_VOWEL_GROUPS.findall(key))
    if key.endswith("e") and groups > 1:
        groups -= 1
    return max(1, groups)


def weak_ratios(words: Sequence[Word]) -> tuple[float, ...]:
    """每个词的弱读比值：实际时长相对于「该词音节数 x 平均每音节时长」的倍数。"""
    if not words:
        return ()
    syllables = [count_syllables(word.text) for word in words]
    total_duration = sum(word.duration for word in words)
    total_syllables = sum(syllables) or 1
    baseline = total_duration / total_syllables
    if baseline <= 0:
        return tuple(1.0 for _ in words)
    return tuple(
        word.duration / (count * baseline)
        for word, count in zip(words, syllables)
    )


def select_blanks(
    words: Sequence[Word],
    *,
    ratio_max: float = config.BLANK_RATIO_MAX,
    min_blanks: int = config.BLANK_MIN,
    max_blanks: int = config.BLANK_MAX,
    strict: float = config.WEAK_RATIO_STRICT,
    relaxed: float = config.WEAK_RATIO_RELAXED,
) -> tuple[int, ...]:
    if not words:
        return ()

    ratios = weak_ratios(words)
    cap = max(min_blanks, min(max_blanks, int(len(words) * ratio_max)))
    cap = min(cap, len(words))

    def candidates(threshold: float) -> list[int]:
        picked = [
            index
            for index, word in enumerate(words)
            if normalise(word.text) in FUNCTION_WORDS and ratios[index] < threshold
        ]
        picked.sort(key=lambda index: ratios[index])
        return picked

    chosen = candidates(strict)
    if len(chosen) < min_blanks:
        chosen = candidates(relaxed)

    return tuple(sorted(chosen[:cap]))
