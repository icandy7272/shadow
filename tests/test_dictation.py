"""整句默写：拆标点、判对、统计。"""

from shadow.drill import dictation
from shadow.models import Word


def _words(*texts):
    return tuple(Word(text=text, start=float(i), end=i + 0.5) for i, text in enumerate(texts))


def test_punctuation_stays_outside_the_box():
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


def test_grade_marks_every_word_and_skips_pure_punctuation():
    words = _words("Stay", "—", "hungry.", "I'm", "here.")
    answers = {
        0: dictation.Answer(guess="stay"),
        2: dictation.Answer(unknown=True),
        3: dictation.Answer(guess="im"),
    }

    marks = dictation.grade(words, answers)

    assert [(mark.index, mark.status) for mark in marks] == [
        (0, dictation.OK), (2, dictation.UNKNOWN), (3, dictation.OK), (4, dictation.WRONG)]
    assert marks[1].answer == "hungry"
    assert dictation.tally(marks) == (2, 1, 1)


def test_unknown_wins_even_if_something_was_typed():
    marks = dictation.grade(_words("adoption"),
                            {0: dictation.Answer(guess="adoption", unknown=True)})
    assert marks[0].status == dictation.UNKNOWN


def test_key_is_lowercase_without_edge_punctuation():
    assert dictation.key("Graduated,") == "graduated"
    assert dictation.key("“I'm") == "i'm"
