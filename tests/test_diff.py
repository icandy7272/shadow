import pytest

from shadow.analysis.diff import accuracy, diff_words, matched_pairs

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
