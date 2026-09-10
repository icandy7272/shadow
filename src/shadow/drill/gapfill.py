"""精听填空。纯函数，无 IO。

挖空的是被弱读的功能词——用户听不懂的从来不是大词，而是 "should have been"
被读成 "shoulda bin"。填空正确率是**唯一客观测量听力的指标**：
发声、停顿、音高全是产出侧的。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..models import Word
from ..text import normalise

BLANK_MARK = "____"
CONTEXT_WORDS = 3


@dataclass(frozen=True, slots=True)
class Blank:
    number: int          # 第几个空，从 1 起
    word_index: int      # 在词序列中的下标
    answer: str
    duration: float
    left: str
    right: str

    def matches(self, guess: str) -> bool:
        return bool(guess) and normalise(guess) == normalise(self.answer)


def _context(words: Sequence[Word], start: int, stop: int) -> str:
    """上下文里的其他空必须继续遮住，否则相邻的空互相送答案。"""
    return " ".join(
        BLANK_MARK if word.is_blank else word.text for word in words[start:stop]
    )


def blanks_of(words: Sequence[Word], *, context: int = CONTEXT_WORDS) -> tuple[Blank, ...]:
    found: list[Blank] = []
    for index, word in enumerate(words):
        if not word.is_blank:
            continue
        found.append(Blank(
            number=len(found) + 1,
            word_index=index,
            answer=word.text,
            duration=word.duration,
            left=_context(words, max(0, index - context), index),
            right=_context(words, index + 1, index + 1 + context),
        ))
    return tuple(found)


def render(words: Sequence[Word], *, revealed: Sequence[int] = ()) -> str:
    """挖空后的文本。revealed 里的下标照常显示。"""
    shown = frozenset(revealed)
    parts = []
    number = 0
    for index, word in enumerate(words):
        if word.is_blank:
            number += 1
            parts.append(word.text if index in shown else f"{BLANK_MARK}{number}")
        else:
            parts.append(word.text)
    return " ".join(parts)


GUESS_MARK = "?"


@dataclass(frozen=True, slots=True)
class Response:
    guess: str | None
    guessed: bool = False      # True = 靠上下文推的，不是听出来的

    @property
    def heard(self) -> bool:
        return bool(self.guess) and not self.guessed


def parse_answer(raw: str) -> Response:
    """词后加问号表示「是推出来的」。

    功能词恰恰是最容易从语法推断出来的一类词——put me ___ for adoption
    闭着眼也能填 up。不区分听到与推断，填空就测不出听力。
    """
    text = (raw or "").strip()
    if not text:
        return Response(guess=None)
    if text.endswith(GUESS_MARK):
        return Response(guess=text[:-1].strip() or None, guessed=True)
    return Response(guess=text)


def score(blanks: Sequence[Blank], answers: Sequence[str | None]) -> tuple[int, int]:
    """返回 (答对数, 总数)。跳过的空算错。"""
    correct = sum(
        1 for blank, guess in zip(blanks, answers) if guess and blank.matches(guess)
    )
    return correct, len(blanks)


def tally(
    blanks: Sequence[Blank], responses: Sequence[Response]
) -> tuple[int, int, int]:
    """返回 (答对, 总数, 答对且是听出来的)。后者才是真听力。"""
    correct = heard = 0
    for blank, response in zip(blanks, responses):
        if response.guess and blank.matches(response.guess):
            correct += 1
            if response.heard:
                heard += 1
    return correct, len(blanks), heard
