import pytest

from shadow.drill.units import split_into_units
from shadow.models import Word

MIN, MAX, MIN_WORDS = 3.0, 8.0, 5


def sentence(texts, *, start=0.0, per_word=0.4, gap_after=0.3):
    """构造一句话，最后一个词带句号。返回 (词序列, 下一句起点)。"""
    words, t = [], start
    for i, text in enumerate(texts):
        mark = "." if i == len(texts) - 1 else ""
        words.append(Word(text=text + mark, start=t, end=t + per_word))
        t += per_word
    return words, t + gap_after


def build(*sentences_texts, per_word=0.4):
    words, t = [], 0.0
    for texts in sentences_texts:
        group, t = sentence(texts, start=t, per_word=per_word)
        words.extend(group)
    return tuple(words)


def split(words):
    return split_into_units(words, min_sec=MIN, max_sec=MAX, min_words=MIN_WORDS)


def texts_of(unit):
    return " ".join(w.text for w in unit)


def test_empty_input_returns_empty():
    assert split(()) == ()


def test_every_word_is_kept_exactly_once_in_order():
    words = build(["a", "b"], ["c", "d", "e"], ["f"] * 12, ["g", "h", "i"])
    units = split(words)
    assert [w for unit in units for w in unit] == list(words)


def test_short_sentences_are_merged_forward():
    # 三句各 0.8s，单独都不够 min_sec，应合并成一个单元
    words = build(["a", "b"], ["c", "d"], ["e", "f"])
    units = split(words)
    assert len(units) == 1
    assert texts_of(units[0]) == "a b. c d. e f."


def test_long_sentence_is_split_at_its_largest_internal_pause():
    # 一句 30 词 x 0.4s = 12s，超过 max_sec，应在最大停顿处断开
    texts = [f"w{i}" for i in range(30)]
    words, _ = sentence(texts, per_word=0.4)
    # 在第 15 个词之前插一个明显更大的停顿
    shifted = tuple(
        w if i < 15 else Word(text=w.text, start=w.start + 1.5, end=w.end + 1.5)
        for i, w in enumerate(words)
    )
    units = split(shifted)
    assert len(units) == 2
    assert units[0][-1].text == "w14"
    assert units[1][0].text == "w15"


def test_units_respect_the_maximum_length():
    texts = [f"w{i}" for i in range(60)]
    words, _ = sentence(texts, per_word=0.4)
    for unit in split(words):
        assert unit[-1].end - unit[0].start <= MAX + 1e-9


def test_trailing_short_sentence_is_merged_back():
    # 末尾一句太短，没有下一句可并，应并回前一个单元
    words = build([f"w{i}" for i in range(10)], ["ok"])
    units = split(words)
    assert len(units) == 1
    assert units[0][-1].text == "ok."


def test_single_short_input_still_yields_one_unit():
    words = build(["hi"])
    units = split(words)
    assert len(units) == 1
    assert texts_of(units[0]) == "hi."
