"""词块图的几何。命令行的 PNG 和网页的 DOM 共用这份数字。"""

import numpy as np
import pytest
import soundfile as sf

from shadow.analysis.prosody import analyse
from shadow.report import geometry
from shadow.report.geometry import Block
from shadow.models import Word


def _words(spec):
    return tuple(Word(text=t, start=a, end=a + d) for t, a, d in spec)


REF = _words([("Just", 1.0, 0.5), ("three", 1.6, 0.2), ("stories.", 1.9, 0.5)])
USR = _words([("Just", 0.0, 0.9), ("three", 1.0, 0.2), ("stories.", 1.3, 0.5)])


@pytest.fixture()
def prosody(tmp_path):
    path = tmp_path / "tone.wav"
    t = np.arange(16000 * 3) / 16000
    sf.write(path, (0.4 * np.sin(2 * np.pi * 150 * t)).astype("float32"), 16000)
    return analyse(path)


def test_blocks_are_relative_to_the_first_word():
    blocks = geometry.blocks_of(REF)
    assert blocks[0] == Block(text="Just", start=0.0, width=0.5)
    assert blocks[1].start == pytest.approx(0.6)
    # 句号不进标签，块上只写词
    assert blocks[2].text == "stories"


def test_a_word_shorter_than_the_floor_still_gets_a_visible_block():
    blocks = geometry.blocks_of(_words([("a", 0.0, 0.004)]))
    assert blocks[0].width == geometry.MIN_BLOCK_SEC


def test_only_meaningful_changes_in_lag_are_annotated():
    marked = geometry.lag_annotations(
        [(0, 0.0), (1, 0.05), (2, 0.5), (3, 0.52), (4, 0.9)], step=0.15
    )
    assert [index for index, _ in marked] == [2, 4]


def test_rhythm_view_pairs_each_lag_with_where_it_starts_and_lands():
    class FakeRhythm:
        lags = ((0, 0.2), (1, 0.6))
        ref_span = 1.4
        usr_span = 1.8

    view = geometry.rhythm_view(ref_words=REF, usr_words=USR, rhythm=FakeRhythm())

    assert view.seconds == 1.8
    assert view.lags[0].ref_at == pytest.approx(0.0)
    assert view.lags[0].usr_at == pytest.approx(0.2)
    assert view.lags[1].usr_at == pytest.approx(0.6 + 0.6)
    # 0.2 → 0.6 变化超过 0.15，两条都值得标
    assert [lag.marked for lag in view.lags] == [True, True]


def test_a_missed_pause_is_marked_on_the_reference_gap():
    class Note:
        kind = "missed_pause"
        ref_index = 0
        usr_index = 0
        flag = "该停"

    class FakeRhythm:
        lags = ()
        ref_span = 1.4
        usr_span = 1.8

    view = geometry.rhythm_view(ref_words=REF, usr_words=USR,
                                rhythm=FakeRhythm(), pause_notes=[Note()])
    span = view.spans[0]
    assert span.row == "ref"
    assert (span.start, span.end) == pytest.approx((0.5, 0.6))


def test_pitch_slots_run_left_to_right_within_the_unit_interval(prosody):
    slots = geometry.pitch_slots(
        ref_words=REF, usr_words=USR, pairs=[(0, 0), (1, 1), (2, 2)],
        ref_prosody=prosody, usr_prosody=prosody,
    )
    assert [s.text for s in slots] == ["Just", "three", "stories"]
    assert slots[0].x == 0.0
    assert all(0.0 <= s.x <= 1.0 for s in slots)
    assert slots[-1].x + slots[-1].ref_width <= 1.0 + 1e-9
    # 每格都有原声走向；配上的词才有你的走向
    assert all(any(v is not None for v in s.ref_trace) for s in slots)
    assert all(s.usr_trace for s in slots)


def test_an_unmatched_word_gets_no_block_of_yours(prosody):
    slots = geometry.pitch_slots(
        ref_words=REF, usr_words=USR, pairs=[(0, 0), (2, 2)],
        ref_prosody=prosody, usr_prosody=prosody,
    )
    assert slots[1].usr_trace == ()
    assert slots[1].usr_width == 0.0


def test_a_word_read_as_something_else_still_shows_your_pitch(prosody):
    """实际遇到的：papers 被听成 paper。图 1 有你的块，图 2 却一条线都没有——
    你在这个位置确实出了声，音高照样该画出来比着看。"""
    from types import SimpleNamespace

    from shadow.analysis.diff import diff_words
    from shadow.web.view import _take_view

    usr = _words([("Just", 0.0, 0.9), ("three", 1.0, 0.2), ("story.", 1.3, 0.5)])
    rhythm = SimpleNamespace(lags=(), ref_span=1.4, usr_span=1.8,
                             speech_ratio=1.0, pause_ratio=None)
    take = SimpleNamespace(tokens=diff_words([w.text for w in REF], [w.text for w in usr]),
                           words=usr, rhythm=rhythm, prosody=prosody, advice=())
    review = SimpleNamespace(ref_words=REF, ref_prosody=prosody, best=take, shaky=frozenset())

    view = _take_view(review, take, 3, {"ref": "r"})

    assert view["pitch"][2]["usrTrace"]
    # 图 1 照旧标出这个词没对上
    assert view["rhythm"]["usr"][2]["matched"] is False


def test_each_take_lists_the_words_the_machine_misheard_in_that_take(prosody):
    """实际遇到的：切到第 2、3 遍，可懂度跟着变，「机器没听对的词」却一直是挑出来那一遍的。"""
    from types import SimpleNamespace

    from shadow.analysis.diff import diff_words
    from shadow.web.view import feedback_view

    rhythm = SimpleNamespace(lags=(), ref_span=1.4, usr_span=1.8,
                             speech_ratio=1.0, pause_ratio=None)
    texts = [w.text for w in REF]

    def take(said, path):
        usr = _words([(text, i * 0.6, 0.5) for i, text in enumerate(said)])
        return SimpleNamespace(tokens=diff_words(texts, said), words=usr, rhythm=rhythm,
                               prosody=prosody, advice=(), path=path)

    takes = (take(["Just", "three", "stories."], "a.wav"),
             take(["Just", "tree", "stories."], "b.wav"))

    def view(shaky):
        review = SimpleNamespace(ref_words=REF, ref_prosody=prosody, shaky=frozenset(shaky),
                                 takes=takes, best=takes[0],
                                 summary=SimpleNamespace(representative=0))
        return feedback_view(review, 3, audio={"ref": "r"},
                             takes={"a.wav": "/take/a", "b.wav": "/take/b"})

    assert [t["problems"] for t in view(())["takes"]] == [
        [], [{"kind": "wrong", "ref": "three", "usr": "tree"}]]
    # 原声这一带转写本身就不可信的，不算你读错
    assert view({1})["takes"][1]["problems"] == []


def test_a_slot_carries_the_whole_shape_not_just_its_ends(prosody):
    """两点摘要会把「先扬后抑」画成上扬。格子里要带上整条走向。"""
    slots = geometry.pitch_slots(
        ref_words=REF, usr_words=USR, pairs=[(0, 0)],
        ref_prosody=prosody, usr_prosody=prosody,
    )
    assert len(slots[0].ref_trace) > 2


def test_blocks_say_whether_the_word_was_matched():
    """读错的词要能一眼看出来是哪一个。"""

    class FakeRhythm:
        lags = ()
        ref_span = 1.4
        usr_span = 1.8

    view = geometry.rhythm_view(ref_words=REF, usr_words=USR, rhythm=FakeRhythm(),
                                pairs=[(0, 0), (2, 2)])

    assert [b.matched for b in view.ref] == [True, False, True]
    assert [b.matched for b in view.usr] == [True, False, True]
