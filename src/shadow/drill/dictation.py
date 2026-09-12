"""整句默写。纯函数，无 IO。

每个词都要写；不会的可以勾「不会」。判对忽略大小写、标点和撇号——
手机上打撇号很麻烦，I'm 写成 im 不该算错。录音比对共用的 text.normalise
保留撇号，这里单独比较，不去动它。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Sequence

from ..models import Word

OK = "ok"
WRONG = "wrong"
UNKNOWN = "unknown"

_EDGES = re.compile(r"^([^\w']*)(.*?)([^\w']*)$")
_IGNORED = re.compile(r"[^a-z0-9]")


@dataclass(frozen=True, slots=True)
class Token:
    """页面上的一个词：框前的标点、要写的部分、框后的标点。"""

    lead: str
    core: str
    trail: str


@dataclass(frozen=True, slots=True)
class Answer:
    guess: str = ""
    unknown: bool = False


@dataclass(frozen=True, slots=True)
class Mark:
    index: int
    answer: str       # 要写的部分，不带首尾标点
    guess: str
    status: str       # OK / WRONG / UNKNOWN


def split(text: str) -> Token:
    lead, core, trail = _EDGES.match(text).groups()
    return Token(lead=lead, core=core, trail=trail)


def _bare(text: str) -> str:
    return _IGNORED.sub("", text.lower())


def needs_box(text: str) -> bool:
    """纯标点的词不出框。"""
    return bool(_bare(split(text).core))


def key(text: str) -> str:
    """查词、记生词用的键：小写，去掉首尾标点。"""
    return split(text).core.lower()


def matches(guess: str, answer: str) -> bool:
    wanted = _bare(answer)
    return bool(wanted) and _bare(guess) == wanted


def grade(words: Sequence[Word], answers: Mapping[int, Answer]) -> tuple[Mark, ...]:
    """逐词判。纯标点不判；没交上来的词算写错。"""
    marks = []
    for index, word in enumerate(words):
        if not needs_box(word.text):
            continue
        core = split(word.text).core
        answer = answers.get(index, Answer())
        if answer.unknown:
            status = UNKNOWN
        elif matches(answer.guess, core):
            status = OK
        else:
            status = WRONG
        marks.append(Mark(index=index, answer=core, guess=answer.guess.strip(),
                          status=status))
    return tuple(marks)


def tally(marks: Sequence[Mark]) -> tuple[int, int, int]:
    """(写对, 写错, 不会)。"""
    return tuple(sum(1 for mark in marks if mark.status == status)
                 for status in (OK, WRONG, UNKNOWN))
