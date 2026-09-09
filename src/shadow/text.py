"""文本归一化。比较词是否相同时统一忽略大小写与标点。"""

from __future__ import annotations

import re

_NON_WORD = re.compile(r"[^a-z']")


def normalise(text: str) -> str:
    return _NON_WORD.sub("", text.lower())
