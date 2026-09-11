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


def test_implausible_word_density_is_flagged():
    """实测某单元 13 个词挤在 0.56 秒里 —— Whisper 词级时间戳崩了。"""
    from shadow.drill.units import is_usable, words_per_second

    crammed = tuple(
        Word(text=f"w{i}", start=110.32 + i * 0.001, end=110.32 + i * 0.001 + 0.02)
        for i in range(13)
    )
    assert words_per_second(crammed) > 8
    assert is_usable(crammed) is False


def test_normal_speech_is_usable():
    from shadow.drill.units import is_usable

    normal, _ = sentence([f"w{i}" for i in range(12)], per_word=0.3)  # 约 3.3 词/秒
    assert is_usable(tuple(normal)) is True


def test_empty_unit_is_not_usable():
    from shadow.drill.units import is_usable

    assert is_usable(()) is False


def test_overlong_sentence_with_no_pauses_splits_near_the_middle():
    """时间戳崩掉时所有间隔都是 0，只取最大间隔会切出两词碎片。"""
    words, _ = sentence([f"w{i}" for i in range(40)], per_word=0.3, gap_after=0.0)
    units = split_into_units(tuple(words), min_sec=0.0, max_sec=6.0, min_words=2)
    assert len(units) >= 2
    assert all(len(u) >= 5 for u in units), [len(u) for u in units]


def test_a_real_pause_still_wins_over_the_middle():
    words, _ = sentence([f"w{i}" for i in range(40)], per_word=0.3, gap_after=0.0)
    words = list(words)
    shift = 1.5
    for i in range(10, len(words)):        # 第 10 个词前插一个明显的停顿
        words[i] = Word(text=words[i].text, start=words[i].start + shift,
                        end=words[i].end + shift)
    units = split_into_units(tuple(words), min_sec=0.0, max_sec=6.0, min_words=2)
    assert units[0][-1].text == "w9"


def _sentence(text, per_word=0.29):
    """一句话，词间无停顿——只能靠语言线索决定在哪切。"""
    from shadow.models import Word

    return tuple(
        Word(text=token, start=index * per_word, end=index * per_word + per_word * 0.9)
        for index, token in enumerate(text.split())
    )


def test_an_overlong_sentence_splits_before_the_conjunction():
    """切在 graduated / from college 中间，两半都不成话。
    该切在 and 前面——那才是这句的接缝。"""
    words = _sentence(
        "My biological mother found out later that my mother had never graduated "
        "from college and that my father had never graduated from high school."
    )

    units = split_into_units(words, max_sec=6.0)

    assert len(units) == 2
    assert units[0][-1].text == "college"
    assert units[1][0].text == "and"


def test_a_comma_beats_a_conjunction():
    words = _sentence(
        "So my parents who were on a waiting list got a call in the middle of the "
        "night, and they were asked whether they wanted this unexpected baby boy."
    )

    units = split_into_units(words, max_sec=6.0)

    assert units[0][-1].text == "night,"


def test_it_still_splits_when_there_is_no_linguistic_seam():
    words = _sentence("one two three four five six seven eight nine ten " * 3)

    units = split_into_units(words, max_sec=6.0)

    assert len(units) > 1
    assert all(unit[-1].end - unit[0].start <= 6.0 for unit in units)


def test_the_split_stays_near_the_middle():
    """逗号在第二个词后面，也不能切出一个两词的碎片。"""
    words = _sentence(
        "well, everything was all set for me to be adopted at birth by a lawyer "
        "and his wife who lived on the other side of the country entirely."
    )

    units = split_into_units(words, max_sec=6.0)

    for unit in units:
        assert len(unit) >= 5


def test_ends_mid_phrase_spots_a_dangling_function_word():
    from shadow.drill.units import ends_mid_phrase

    assert ends_mid_phrase(_sentence("was replaced by the"))
    assert ends_mid_phrase(_sentence("it turned out to be a"))


def test_a_sentence_that_simply_ends_in_a_preposition_is_fine():
    """「…to buy food with.」是完整的一句，别当成切坏。"""
    from shadow.drill.units import ends_mid_phrase

    assert not ends_mid_phrase(_sentence("for the deposits to buy food with."))
    assert not ends_mid_phrase(_sentence("as the years roll on."))
