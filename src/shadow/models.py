"""核心数据类型。全部 frozen——记录只追加不修改，练习历史天然可回溯。"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Iterable, Sequence


@dataclass(frozen=True, slots=True)
class Word:
    text: str
    start: float
    end: float
    is_blank: bool = False

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True, slots=True)
class Segment:
    idx: int
    start: float
    end: float
    words: tuple[Word, ...]

    @property
    def text(self) -> str:
        return " ".join(word.text for word in self.words)

    @property
    def duration(self) -> float:
        return self.end - self.start


def words_to_json(words: Sequence[Word]) -> str:
    payload = [
        {"text": w.text, "start": w.start, "end": w.end, "is_blank": w.is_blank}
        for w in words
    ]
    return json.dumps(payload, ensure_ascii=False)


def words_from_json(raw: str) -> tuple[Word, ...]:
    return tuple(
        Word(
            text=item["text"],
            start=float(item["start"]),
            end=float(item["end"]),
            is_blank=bool(item.get("is_blank", False)),
        )
        for item in json.loads(raw)
    )


def with_blanks(words: Sequence[Word], indices: Iterable[int]) -> tuple[Word, ...]:
    """返回标记了挖空位的新词序列，不修改入参。"""
    marked = frozenset(indices)
    return tuple(
        replace(word, is_blank=index in marked) for index, word in enumerate(words)
    )
