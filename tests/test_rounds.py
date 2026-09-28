"""旧记录里一轮被拆成了好几行：打分一行、默写一行、跟读一行。认出来并回去。

页面原来没把这一轮的编号传回服务端，每一步各开一行。练过几次被放大成三倍，
今天新练的句子还占掉了当天的复习名额。
"""

from datetime import datetime, timedelta

from shadow.rounds import Row, LISTEN, DRILL, RECORD, merges

T0 = datetime(2026, 9, 14, 9, 0)


def _row(run_id, *steps, minutes=0, unit=4):
    return Row(id=run_id, unit=(1, unit, "I'm honored."), started=T0 + timedelta(minutes=minutes),
               steps=frozenset(steps))


def test_the_three_steps_of_one_sitting_become_one_round():
    rows = [_row(151, LISTEN), _row(152, DRILL, minutes=1), _row(153, RECORD, minutes=3)]
    assert merges(rows) == [[151, 152, 153]]


def test_a_step_done_again_starts_the_next_round():
    """实测：打分、默写，又打分、默写、跟读——是两轮，不是一轮。"""
    rows = [_row(89, LISTEN), _row(90, DRILL, minutes=1),
            _row(91, LISTEN, minutes=2), _row(92, DRILL, minutes=3), _row(93, RECORD, minutes=5)]
    assert merges(rows) == [[89, 90], [91, 92, 93]]


def test_a_second_recording_is_its_own_round():
    rows = [_row(241, LISTEN), _row(242, DRILL, minutes=1),
            _row(243, RECORD, minutes=3), _row(244, RECORD, minutes=6)]
    assert merges(rows) == [[241, 242, 243]]


def test_steps_only_join_in_their_usual_order():
    """跟读完了再打分，是下一轮的开头。"""
    rows = [_row(1, RECORD), _row(2, LISTEN, minutes=2), _row(3, DRILL, minutes=3)]
    assert merges(rows) == [[2, 3]]


def test_a_long_break_splits_the_round():
    rows = [_row(1, LISTEN), _row(2, DRILL, minutes=45)]
    assert merges(rows) == []


def test_different_sentences_never_mix():
    rows = [_row(1, LISTEN, unit=4), _row(2, DRILL, minutes=1, unit=5)]
    assert merges(rows) == []


def test_a_row_that_already_holds_a_whole_round_is_left_alone():
    rows = [_row(498, LISTEN, DRILL, RECORD), _row(499, LISTEN, minutes=2)]
    assert merges(rows) == []


def test_empty_rows_are_left_alone():
    """中途取消留下的空行：本来就不算练过，不去碰它。"""
    rows = [_row(1, LISTEN), _row(2, minutes=1), _row(3, DRILL, minutes=2)]
    assert merges(rows) == [[1, 3]]
