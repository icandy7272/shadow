"""文本归一化。比较词是否相同时统一忽略大小写与标点。"""

from __future__ import annotations

import re

_NON_WORD = re.compile(r"[^a-z']")


def normalise(text: str) -> str:
    """归一化用于比较的词形。

    剥空时退回小写原文：全数字或全符号的词（"2023" / "2024"）被剥成空串后
    会互相误判为相等，既虚高可懂度，又会把一对错词当成时间对齐锚点喂给
    build_anchors——而整个对齐设计的前提就是 equal 的 token 可靠。
    """
    stripped = _NON_WORD.sub("", text.lower())
    return stripped or text.lower().strip()
