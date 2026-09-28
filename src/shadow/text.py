"""文本归一化。比较词是否相同时统一忽略大小写与标点，数字按读音比。"""

from __future__ import annotations

import re

_NON_WORD = re.compile(r"[^a-z']")
_NUMBER = re.compile(r"^(\d+)(st|nd|rd|th)?$")

_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen "
         "fourteen fifteen sixteen seventeen eighteen nineteen").split()
_TENS = {2: "twenty", 3: "thirty", 4: "forty", 5: "fifty",
         6: "sixty", 7: "seventy", 8: "eighty", 9: "ninety"}
_ORDINAL = {"one": "first", "two": "second", "three": "third", "five": "fifth",
            "eight": "eighth", "nine": "ninth", "twelve": "twelfth"}
SPELLED_MAX = 99    # 再大的数读出来是好几个词（one hundred and…），没法一个词对一个词


def _cardinal(n: int) -> str:
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    return _TENS[tens] + (_ONES[ones] if ones else "")


def _ordinal(n: int) -> str:
    if n >= 20 and n % 10 == 0:
        return _TENS[n // 10][:-1] + "ieth"          # twenty → twentieth
    head = _TENS[n // 10] if n >= 20 else ""
    word = _ONES[n % 10 if n >= 20 else n]
    return head + _ORDINAL.get(word, word + "th")


def spell_number(bare: str) -> str | None:
    """「7」→「seven」、「22nd」→「twentysecond」；不是 0–99 的数就返回 None。

    拼出来不带连字符，正好和「twenty-five」去掉标点后的样子一样。
    转写有时写数字有时写单词，同一句话会被判成「seven→听成 7」。
    """
    number = _NUMBER.match(bare)
    if not number or int(number.group(1)) > SPELLED_MAX:
        return None
    value = int(number.group(1))
    return _ordinal(value) if number.group(2) else _cardinal(value)


def normalise(text: str) -> str:
    """归一化用于比较的词形。

    剥空时退回小写原文：全数字或全符号的词（"2023" / "2024"）被剥成空串后
    会互相误判为相等，既虚高可懂度，又会把一对错词当成时间对齐锚点喂给
    build_anchors——而整个对齐设计的前提就是 equal 的 token 可靠。
    """
    lowered = text.lower()
    spelled = spell_number(re.sub(r"[^a-z0-9]", "", lowered))
    if spelled:
        return spelled
    stripped = _NON_WORD.sub("", lowered)
    return stripped or lowered.strip()
