"""强制对齐。原文本来就在手上，词边界没有理由去猜。"""

import pytest

from shadow.analysis import align
from shadow.models import Word


def _words(spec):
    return tuple(Word(text=t, start=a, end=b) for t, a, b in spec)


def test_spell_keeps_only_what_the_model_can_read():
    assert align.spell("College,") == "COLLEGE"
    assert align.spell("don't") == "DON'T"
    assert align.spell("five-cent") == "FIVECENT"
    assert align.spell("18") == ""          # 数字编不出来


def test_a_sentence_full_of_numbers_is_left_alone(tmp_path):
    """编不出的词太多就整段不碰，保留原时间戳，别拿插值糊弄。"""
    words = _words([("18", 0.0, 0.2), ("30,", 0.2, 0.4), ("okay", 0.4, 0.8)])

    assert align.align_words(tmp_path / "nope.wav", words) is None


def test_no_words_is_not_an_alignment(tmp_path):
    assert align.align_words(tmp_path / "nope.wav", ()) is None


def test_an_unspellable_word_is_placed_between_its_neighbours():
    words = _words([("for", 0.0, 0.3), ("18", 0.3, 0.5), ("months", 0.5, 1.0)])
    placed = {0: Word(text="for", start=0.10, end=0.34),
              2: Word(text="months", start=0.62, end=1.05)}

    out = align._interpolate(words, placed, 3)

    assert out[1].text == "18"
    assert out[1].start == pytest.approx(0.34)
    assert out[1].end == pytest.approx(0.62)
    assert out[0] == placed[0] and out[2] == placed[2]


def test_an_unspellable_word_at_the_edge_still_gets_a_span():
    words = _words([("18", 0.0, 0.3), ("months", 0.3, 1.0)])
    placed = {1: Word(text="months", start=0.40, end=1.02)}

    out = align._interpolate(words, placed, 2)

    assert out[0].end == pytest.approx(0.40)
    assert out[0].start < out[0].end
