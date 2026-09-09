import pytest

from shadow.analysis.diff import diff_words
from shadow.analysis.timing import word_timings
from shadow.models import Word

REF_TEXTS = ["should", "have", "been", "there"]


def make(texts, durations):
    words, t = [], 0.0
    for text, duration in zip(texts, durations):
        words.append(Word(text=text, start=t, end=t + duration))
        t += duration
    return tuple(words)


def test_ratio_is_user_duration_over_reference():
    ref = make(REF_TEXTS, [0.30, 0.08, 0.25, 0.30])
    usr = make(REF_TEXTS, [0.30, 0.24, 0.25, 0.30])
    timings = word_timings(ref, usr, diff_words(REF_TEXTS, REF_TEXTS))
    by_text = {t.text: t for t in timings}
    assert by_text["have"].ratio == pytest.approx(3.0)
    assert by_text["should"].ratio == pytest.approx(1.0)


def test_missing_word_has_no_ratio():
    ref = make(REF_TEXTS, [0.3, 0.1, 0.3, 0.3])
    spoken = ["should", "been", "there"]
    usr = make(spoken, [0.3, 0.3, 0.3])
    timings = word_timings(ref, usr, diff_words(REF_TEXTS, spoken))
    have = next(t for t in timings if t.text == "have")
    assert have.ratio is None
    assert have.usr_duration is None
    assert have.kind == "missing"


def test_one_entry_per_reference_word_in_order():
    ref = make(REF_TEXTS, [0.3, 0.1, 0.3, 0.3])
    usr = make(REF_TEXTS, [0.3, 0.1, 0.3, 0.3])
    timings = word_timings(ref, usr, diff_words(REF_TEXTS, REF_TEXTS))
    assert [t.ref_index for t in timings] == [0, 1, 2, 3]
    assert [t.text for t in timings] == REF_TEXTS


def test_zero_length_reference_word_is_skipped_safely():
    ref = make(REF_TEXTS, [0.3, 0.0, 0.3, 0.3])
    usr = make(REF_TEXTS, [0.3, 0.1, 0.3, 0.3])
    timings = word_timings(ref, usr, diff_words(REF_TEXTS, REF_TEXTS))
    assert next(t for t in timings if t.text == "have").ratio is None
