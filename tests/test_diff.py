import pytest

from shadow.analysis.diff import (
    accuracy,
    diff_words,
    matched_pairs,
    unreliable_indices,
)

REF = ["Should", "have", "been", "there", "earlier"]


def kinds(tokens):
    return [token.kind for token in tokens]


def test_identical_sequences_are_all_equal():
    tokens = diff_words(REF, list(REF))
    assert kinds(tokens) == ["equal"] * 5
    assert accuracy(tokens) == pytest.approx(1.0)


def test_case_and_punctuation_are_ignored():
    tokens = diff_words(["Should,", "have."], ["should", "HAVE"])
    assert kinds(tokens) == ["equal", "equal"]


def test_dropped_word_is_reported_missing():
    tokens = diff_words(REF, ["Should", "been", "there", "earlier"])
    assert "missing" in kinds(tokens)
    missing = [t for t in tokens if t.kind == "missing"]
    assert missing[0].ref_text == "have"
    assert missing[0].usr_index is None


def test_substituted_word_is_reported_wrong():
    tokens = diff_words(REF, ["Should", "half", "been", "there", "earlier"])
    wrong = [t for t in tokens if t.kind == "wrong"]
    assert wrong and wrong[0].ref_text == "have" and wrong[0].usr_text == "half"


def test_inserted_word_is_reported_extra():
    tokens = diff_words(REF, ["Should", "have", "uh", "been", "there", "earlier"])
    extra = [t for t in tokens if t.kind == "extra"]
    assert extra and extra[0].usr_text == "uh"
    assert extra[0].ref_index is None


def test_matched_pairs_are_index_pairs_of_equal_tokens():
    tokens = diff_words(REF, ["Should", "half", "been", "there", "earlier"])
    pairs = matched_pairs(tokens)
    assert (0, 0) in pairs and (2, 2) in pairs
    assert all(isinstance(r, int) and isinstance(u, int) for r, u in pairs)


def test_accuracy_counts_reference_words_only():
    tokens = diff_words(REF, ["Should", "been", "there", "earlier"])
    assert accuracy(tokens) == pytest.approx(4 / 5)


def test_empty_user_transcript_yields_zero_accuracy():
    tokens = diff_words(REF, [])
    assert kinds(tokens) == ["missing"] * 5
    assert accuracy(tokens) == pytest.approx(0.0)


def test_distinct_numbers_are_not_reported_equal():
    # normalise 曾把全数字词剥成空串，导致 2023/2024 互相判等，
    # 既虚高可懂度又会污染 build_anchors 的锚点
    tokens = diff_words(["born", "in", "2023"], ["born", "in", "2024"])
    assert kinds(tokens) == ["equal", "equal", "wrong"]
    assert accuracy(tokens) == pytest.approx(2 / 3)


def test_unreliable_indices_flags_words_the_audio_does_not_support():
    """长上下文转写会把缩读还原：音频是 why'd，库里却存成 why did。"""
    stored = ["So", "why", "did", "I", "drop", "out?"]
    isolated = ["So", "why'd", "I", "drop", "out?"]
    shaky = unreliable_indices(stored, isolated)
    assert 1 in shaky or 2 in shaky      # why / did 这一带不可信
    assert 0 not in shaky and 4 not in shaky


def test_nothing_is_unreliable_when_both_agree():
    assert unreliable_indices(REF, list(REF)) == frozenset()
