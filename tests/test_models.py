import dataclasses

import pytest

from shadow.models import Segment, Word, with_blanks, words_from_json, words_to_json


def test_word_is_immutable():
    word = Word(text="the", start=1.0, end=1.1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        word.text = "a"


def test_word_duration():
    assert Word(text="the", start=1.0, end=1.25).duration == pytest.approx(0.25)


def test_segment_text_joins_words():
    words = (Word("I", 0.0, 0.1), Word("am", 0.1, 0.3), Word("here", 0.3, 0.6))
    segment = Segment(idx=0, start=0.0, end=0.6, words=words)
    assert segment.text == "I am here"
    assert segment.duration == pytest.approx(0.6)


def test_words_json_roundtrip():
    words = (Word("I", 0.0, 0.1), Word("am", 0.1, 0.3, is_blank=True))
    assert words_from_json(words_to_json(words)) == words


def test_with_blanks_returns_new_tuple_and_leaves_original_untouched():
    words = (Word("I", 0.0, 0.1), Word("am", 0.1, 0.3), Word("here", 0.3, 0.6))
    marked = with_blanks(words, (1,))
    assert [w.is_blank for w in marked] == [False, True, False]
    assert [w.is_blank for w in words] == [False, False, False]
