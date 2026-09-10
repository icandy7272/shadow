import pytest

from shadow.drill.gapfill import Blank, blanks_of, render, score
from shadow.models import Word

TEXTS = ["Today,", "I", "want", "to", "tell", "you", "three", "stories"]
BLANK_AT = (3, 5)          # to / you


def make():
    words, t = [], 0.0
    for index, text in enumerate(TEXTS):
        duration = 0.10 if index in BLANK_AT else 0.40
        words.append(Word(text=text, start=t, end=t + duration, is_blank=index in BLANK_AT))
        t += duration
    return tuple(words)


def test_blanks_are_numbered_in_order_with_context():
    blanks = blanks_of(make())
    assert [b.number for b in blanks] == [1, 2]
    assert [b.answer for b in blanks] == ["to", "you"]
    assert blanks[0].left == "Today, I want"
    assert blanks[0].right == "tell ____ three"      # 相邻的空必须继续遮住
    assert blanks[0].duration == pytest.approx(0.10)


def test_no_blanks_yields_empty():
    words = tuple(Word(text=t, start=i * 0.4, end=i * 0.4 + 0.4) for i, t in enumerate(TEXTS))
    assert blanks_of(words) == ()


def test_render_hides_blanks_and_numbers_them():
    text = render(make())
    assert "____1" in text and "____2" in text
    assert " to " not in text
    assert text.startswith("Today, I want ____1 tell")


def test_render_can_reveal_specific_words():
    text = render(make(), revealed=(3,))
    assert "want to tell" in text
    assert "____2" in text          # 另一个空仍然藏着


def test_matching_ignores_case_and_punctuation():
    blank = Blank(number=1, word_index=0, answer="To,", duration=0.1, left="", right="")
    assert blank.matches("to")
    assert blank.matches("  TO  ")
    assert not blank.matches("too")
    assert not blank.matches("")


def test_score_counts_skipped_as_wrong():
    blanks = blanks_of(make())
    assert score(blanks, ["to", "you"]) == (2, 2)
    assert score(blanks, ["to", None]) == (1, 2)
    assert score(blanks, [None, None]) == (0, 2)
    assert score(blanks, ["TO!", "your"]) == (1, 2)


def test_context_never_leaks_another_blank():
    """相邻的空若互相出现在对方上下文里，等于直接送答案。"""
    blanks = blanks_of(make())
    assert "you" not in blanks[0].right          # 第 2 空的答案
    assert "to" not in blanks[1].left.split()    # 第 1 空的答案
    assert "____" in blanks[0].right
    assert "____" in blanks[1].left
