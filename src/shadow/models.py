"""核心数据类型。全部 frozen——记录只追加不修改，练习历史天然可回溯。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True, slots=True)
class Word:
    text: str
    start: float
    end: float

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
    payload = [{"text": w.text, "start": w.start, "end": w.end} for w in words]
    return json.dumps(payload, ensure_ascii=False)


def words_from_json(raw: str) -> tuple[Word, ...]:
    # 老片段里还带着挖空时代的 is_blank，读的时候忽略
    return tuple(
        Word(text=item["text"], start=float(item["start"]), end=float(item["end"]))
        for item in json.loads(raw)
    )
