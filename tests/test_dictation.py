"""整句默写：拆标点、把写的词和原文对齐、判对、统计。"""

from shadow.drill import dictation
from shadow.drill.dictation import MISSING, OK, UNKNOWN, WRONG
from shadow.models import Word


def _words(*texts):
    return tuple(Word(text=text, start=float(i), end=i + 0.5) for i, text in enumerate(texts))


def _statuses(graded):
    return [mark.status for mark in graded.marks]


def test_punctuation_stays_outside_the_word():
    assert dictation.split("there.") == dictation.Token("", "there", ".")
    assert dictation.split("“Stay") == dictation.Token("“", "Stay", "")
    assert dictation.split("don't,") == dictation.Token("", "don't", ",")
    assert dictation.split("—") == dictation.Token("—", "", "")


def test_matching_ignores_case_punctuation_and_apostrophes():
    """手机上打撇号很麻烦，I'm 写成 im 不该算错。"""
    assert dictation.matches("im", "I'm")
    assert dictation.matches("THERE", "there")
    assert not dictation.matches("their", "there")
    assert not dictation.matches("", "there")


def test_one_missed_word_costs_only_that_word():
    """以前按格子一个个对：中间漏一个词，后面的全错。"""
    words = _words("and", "this", "is", "a", "college", "graduation.")

    graded = dictation.grade(words, "and this is a graduation")

    assert _statuses(graded) == [OK, OK, OK, OK, MISSING, OK]
    assert graded.extras == ()


def test_a_question_mark_stands_for_a_word_you_do_not_know():
    words = _words("a", "college", "graduation.")

    assert _statuses(dictation.grade(words, "a ? graduation")) == [OK, UNKNOWN, OK]
    assert _statuses(dictation.grade(words, "a ？ graduation")) == [OK, UNKNOWN, OK]


def test_a_misheard_word_is_wrong_not_missing_plus_extra():
    words = _words("the", "closest", "I've", "ever")

    graded = dictation.grade(words, "The closest i ever")

    assert [(mark.status, mark.guess) for mark in graded.marks] == [
        (OK, "The"), (OK, "closest"), (WRONG, "i"), (OK, "ever")]
    assert graded.extras == ()


def test_extra_words_are_listed_without_shifting_the_rest():
    words = _words("It", "was", "a", "start.")

    graded = dictation.grade(words, "it was was a start")

    assert _statuses(graded) == [OK, OK, OK, OK]
    assert graded.extras == ("was",)


def test_punctuation_typed_or_not_is_ignored_and_pure_punctuation_is_not_graded():
    words = _words("Stay", "—", "hungry.", "I'm", "here.")

    graded = dictation.grade(words, "stay, hungry! im — here")

    assert [(mark.index, mark.status) for mark in graded.marks] == [
        (0, OK), (2, OK), (3, OK), (4, OK)]
    assert graded.marks[1].answer == "hungry"


def test_when_you_stop_early_the_missing_words_are_the_last_ones():
    words = _words("It", "was", "a", "start.")

    graded = dictation.grade(words, "it is ?")

    assert _statuses(graded) == [OK, WRONG, UNKNOWN, MISSING]
    assert dictation.tally(graded.marks) == (1, 1, 1, 1)


def test_nothing_typed_means_every_word_is_missing():
    assert _statuses(dictation.grade(_words("Thank", "you."), "   ")) == [MISSING, MISSING]


def test_key_is_lowercase_without_edge_punctuation():
    assert dictation.key("Graduated,") == "graduated"
    assert dictation.key("“I'm") == "i'm"
