"""整句默写。纯函数，无 IO。

一整句写在一个框里，按词和原文对齐之后逐词判：漏一个词只算这一个漏写，
后面照样对得上。不会的词写一个 ?。判对忽略大小写、标点和撇号——手机上打撇号
很麻烦，I'm 写成 im 不该算错。录音比对共用的 text.normalise 保留撇号，这里单独比较。
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from dataclasses import dataclass
from typing import Sequence

from ..models import Word
from ..text import spell_number

OK = "ok"
WRONG = "wrong"
UNKNOWN = "unknown"
MISSING = "missing"

_EDGES = re.compile(r"^([^\w']*)(.*?)([^\w']*)$")
_IGNORED = re.compile(r"[^a-z0-9]")
_PLACEHOLDER = re.compile(r"^[?？]+$")


@dataclass(frozen=True, slots=True)
class Token:
    """原文里的一个词：前面的标点、要写的部分、后面的标点。"""

    lead: str
    core: str
    trail: str


@dataclass(frozen=True, slots=True)
class Mark:
    index: int        # 原文里第几个词（纯标点的词也占位）
    answer: str       # 要写的部分，不带首尾标点
    guess: str        # 对上的那个写的词；漏写、不会时为空
    status: str       # OK / WRONG / UNKNOWN / MISSING


@dataclass(frozen=True, slots=True)
class Graded:
    marks: tuple[Mark, ...]
    extras: tuple[str, ...]     # 写了、但对不上原文任何一个词的


def split(text: str) -> Token:
    lead, core, trail = _EDGES.match(text).groups()
    return Token(lead=lead, core=core, trail=trail)


def _bare(text: str) -> str:
    bare = _IGNORED.sub("", text.lower())
    return spell_number(bare) or bare          # 7 和 seven 是同一个词


def needs_box(text: str) -> bool:
    """纯标点的词不用写。"""
    return bool(_bare(split(text).core))


def key(text: str) -> str:
    """查词、记生词用的键：小写，去掉首尾标点。"""
    return split(text).core.lower()


def matches(guess: str, answer: str) -> bool:
    wanted = _bare(answer)
    return bool(wanted) and _bare(guess) == wanted


def _typed(text: str) -> list[tuple[str, bool]]:
    """写的内容拆成词：(写的词, 是不是 ?)。纯标点丢掉。"""
    out = []
    for raw in text.split():
        if _PLACEHOLDER.match(raw):
            out.append(("", True))
            continue
        core = split(raw).core
        if _bare(core):
            out.append((core, False))
    return out


# 代价都乘了 100，好用整数比大小（回溯时要判相等，浮点数靠不住）。
GAP = 100            # 漏写一个、多写一个
WRONG_BASE = 100     # 写错一个，再按不像的程度往上加，最多加 WRONG_SPREAD
WRONG_SPREAD = 90    # 加满也不到 GAP：写错一个永远比「漏写 + 多写」便宜


def _cost(answer: str, typed: tuple[str, bool]) -> int:
    """写的这个词对上原文这个词要花多少。

    原来写错一律算 1：celigraph 对 a 和对 calligraphy 一样贵，打平了就挑错。
    现在越像越便宜，拼错的词会对上它像的那个。
    """
    guess, unknown = typed
    if unknown or matches(guess, answer):
        return 0
    alike = SequenceMatcher(None, _bare(guess), _bare(answer), autojunk=False).ratio()
    return WRONG_BASE + round(WRONG_SPREAD * (1 - alike))


def _table(answers: Sequence[tuple[int, str]], typed: Sequence[tuple[str, bool]]):
    """编辑距离表：对上 0，写错 100–190（越不像越贵），漏写 100，多写 100。"""
    rows, cols = len(answers), len(typed)
    table = [[0] * (cols + 1) for _ in range(rows + 1)]
    for i in range(1, rows + 1):
        table[i][0] = i * GAP
    for j in range(1, cols + 1):
        table[0][j] = j * GAP
    for i in range(1, rows + 1):
        for j in range(1, cols + 1):
            table[i][j] = min(table[i - 1][j - 1] + _cost(answers[i - 1][1], typed[j - 1]),
                              table[i - 1][j] + GAP,
                              table[i][j - 1] + GAP)
    return table


def grade(words: Sequence[Word], text: str) -> Graded:
    """把写的词和原文按改动最少的方式对齐，再逐词判。

    写错优先于「漏写 + 多写」（i 对 I've 算写错一个）。几种对齐一样好时，
    靠前的词先对上、缺的算在后面——只写到一半，缺的是后半句。
    """
    answers = [(index, split(word.text).core)
               for index, word in enumerate(words) if needs_box(word.text)]
    typed = _typed(text)
    table = _table(answers, typed)
    marks: list[Mark] = []
    extras: list[str] = []
    i, j = len(answers), len(typed)
    # 从后往前回溯：一样好时先认漏写、多写，这样对上的词都靠前
    while i > 0 or j > 0:
        if i > 0 and table[i][j] == table[i - 1][j] + GAP:
            index, answer = answers[i - 1]
            marks.append(Mark(index=index, answer=answer, guess="", status=MISSING))
            i -= 1
        elif j > 0 and table[i][j] == table[i][j - 1] + GAP:
            guess, unknown = typed[j - 1]
            if not unknown:
                extras.append(guess)
            j -= 1
        else:
            index, answer = answers[i - 1]
            guess, unknown = typed[j - 1]
            status = UNKNOWN if unknown else OK if matches(guess, answer) else WRONG
            marks.append(Mark(index=index, answer=answer, guess=guess, status=status))
            i -= 1
            j -= 1
    return Graded(marks=tuple(reversed(marks)), extras=tuple(reversed(extras)))


def tally(marks: Sequence[Mark]) -> tuple[int, int, int, int]:
    """(写对, 写错, 不会, 漏写)。"""
    return tuple(sum(1 for mark in marks if mark.status == status)
                 for status in (OK, WRONG, UNKNOWN, MISSING))
