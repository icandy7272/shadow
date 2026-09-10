"""原文与用户转写的词级 diff。纯函数，无 IO。

equal 类型的 token 同时是时间对齐的锚点来源——这就是本设计不需要帧级 DTW 的原因。
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Sequence

from ..text import normalise

KIND_EQUAL = "equal"
KIND_WRONG = "wrong"
KIND_MISSING = "missing"
KIND_EXTRA = "extra"


@dataclass(frozen=True, slots=True)
class DiffToken:
    kind: str
    ref_index: int | None
    usr_index: int | None
    ref_text: str
    usr_text: str


def diff_words(
    ref_texts: Sequence[str], usr_texts: Sequence[str]
) -> tuple[DiffToken, ...]:
    ref_norm = [normalise(text) for text in ref_texts]
    usr_norm = [normalise(text) for text in usr_texts]
    matcher = SequenceMatcher(a=ref_norm, b=usr_norm, autojunk=False)

    tokens: list[DiffToken] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                ref_i, usr_j = i1 + offset, j1 + offset
                tokens.append(
                    DiffToken(KIND_EQUAL, ref_i, usr_j,
                              ref_texts[ref_i], usr_texts[usr_j])
                )
        elif tag == "replace":
            for offset in range(max(i2 - i1, j2 - j1)):
                ref_i = i1 + offset if i1 + offset < i2 else None
                usr_j = j1 + offset if j1 + offset < j2 else None
                if ref_i is None:
                    tokens.append(
                        DiffToken(KIND_EXTRA, None, usr_j, "", usr_texts[usr_j])
                    )
                elif usr_j is None:
                    tokens.append(
                        DiffToken(KIND_MISSING, ref_i, None, ref_texts[ref_i], "")
                    )
                else:
                    tokens.append(
                        DiffToken(KIND_WRONG, ref_i, usr_j,
                                  ref_texts[ref_i], usr_texts[usr_j])
                    )
        elif tag == "delete":
            for ref_i in range(i1, i2):
                tokens.append(
                    DiffToken(KIND_MISSING, ref_i, None, ref_texts[ref_i], "")
                )
        elif tag == "insert":
            for usr_j in range(j1, j2):
                tokens.append(
                    DiffToken(KIND_EXTRA, None, usr_j, "", usr_texts[usr_j])
                )
    return tuple(tokens)


def matched_pairs(tokens: Sequence[DiffToken]) -> tuple[tuple[int, int], ...]:
    """时间对齐锚点：(原文词下标, 用户词下标)。"""
    return tuple(
        (token.ref_index, token.usr_index)
        for token in tokens
        if token.kind == KIND_EQUAL
        and token.ref_index is not None
        and token.usr_index is not None
    )


def accuracy(tokens: Sequence[DiffToken]) -> float:
    """可懂度：原文里有多少词被机器正确听出来。分母只算原文词。"""
    reference_total = sum(1 for token in tokens if token.ref_index is not None)
    if not reference_total:
        return 0.0
    correct = sum(1 for token in tokens if token.kind == KIND_EQUAL)
    return correct / reference_total


def unreliable_indices(
    ref_texts: Sequence[str], iso_texts: Sequence[str]
) -> frozenset[int]:
    """库内文本与「单独转写同一段音频」不一致的词下标。

    导入整段素材时 Whisper 有长上下文，会把缩读还原成完整形式——实测
    Jobs 说的是 "why'd"，库里却存成了 "why did"。拿这个当基准，会把
    照着音频模仿的人判成发音错误，填空题的标准答案也会是音频里没有的词。

    这些词不可信，不该用来判用户对错。
    """
    return frozenset(
        token.ref_index
        for token in diff_words(ref_texts, iso_texts)
        if token.kind != KIND_EQUAL and token.ref_index is not None
    )
