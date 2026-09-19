"""页面上的日期写法。同一件事在四处露面，写法得是同一个。"""

from datetime import date

from shadow.dates import day_label

TODAY = date(2026, 9, 19)


def test_this_year_leaves_the_year_out():
    assert day_label("2026-09-17T10:30:00+08:00", TODAY) == "09-17"
    assert day_label(date(2026, 1, 3), TODAY) == "01-03"


def test_another_year_keeps_it():
    """去年练的那句，只写 09-17 会看成前天。"""
    assert day_label("2025-09-17T10:30:00+08:00", TODAY) == "2025-09-17"


def test_nothing_in_nothing_out():
    assert day_label(None, TODAY) is None
    assert day_label("", TODAY) is None


def test_something_unparsable_comes_back_as_it_is():
    assert day_label("前天", TODAY) == "前天"
