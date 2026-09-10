import numpy as np
import pytest

from shadow.analysis.diff import diff_words
from shadow.analysis.prosody import Prosody
from shadow.analysis.rhythm import analyse_rhythm
from shadow.models import Word
from shadow.report.advice import build_advice, well_done

TEXTS = ["today", "i", "want", "it"]


def make(spec):
    return tuple(Word(text=t, start=s, end=s + d) for t, s, d in spec)


def prosody_from(segments, duration):
    """segments: [(start, end, 起始半音, 结束半音)]，其余为 nan。"""
    times = np.arange(0.0, duration, 0.01)
    st = np.full(times.shape, np.nan)
    for start, end, head, tail in segments:
        mask = (times >= start) & (times < end)
        if mask.any():
            st[mask] = np.linspace(head, tail, mask.sum())
    return Prosody(times=times, f0_hz=np.full(times.shape, 150.0), semitones=st,
                   energy_db=np.zeros(times.shape), duration=duration)


FLAT = [(0.0, 0.4, 0, 0), (0.9, 1.3, 0, 0), (1.3, 1.7, 0, 0), (1.7, 2.1, 0, 0)]


def scenario(usr_spec, ref_pitch=None, usr_pitch=None):
    ref = make([("today", 0.0, 0.4), ("i", 0.9, 0.4), ("want", 1.3, 0.4), ("it", 1.7, 0.4)])
    usr = make(usr_spec)
    tokens = diff_words([w.text for w in ref], [w.text for w in usr])
    pairs = tuple((t.ref_index, t.usr_index) for t in tokens if t.kind == "equal")
    return dict(
        ref_words=ref, usr_words=usr, tokens=tokens,
        rhythm=analyse_rhythm(ref, usr, pairs),
        ref_prosody=prosody_from(ref_pitch or FLAT, 2.2),
        usr_prosody=prosody_from(usr_pitch or FLAT, 2.2),
    )


def kinds(advice):
    return [a.kind for a in advice]


def test_missed_pause_is_reported():
    ctx = scenario([("today", 0.0, 0.4), ("i", 0.45, 0.4),
                    ("want", 0.85, 0.4), ("it", 1.25, 0.4)])
    advice = build_advice(**ctx)
    assert "missed_pause" in kinds(advice)
    item = next(a for a in advice if a.kind == "missed_pause")
    assert "today" in item.title
    assert item.action


def test_stretched_word_is_measured_against_own_tempo_not_reference():
    # 每个词都慢 1.5 倍 = 整体就是这个语速，不该报「拖长」
    ctx = scenario([("today", 0.0, 0.6), ("i", 1.35, 0.6),
                    ("want", 1.95, 0.6), ("it", 2.55, 0.6)])
    assert "stretched" not in kinds(build_advice(**ctx))


def test_single_stretched_word_is_reported():
    ctx = scenario([("today", 0.0, 1.2), ("i", 1.7, 0.4),
                    ("want", 2.1, 0.4), ("it", 2.5, 0.4)])
    advice = build_advice(**ctx)
    assert "stretched" in kinds(advice)
    assert "today" in next(a for a in advice if a.kind == "stretched").title


def test_missing_final_fall_is_reported():
    ref_pitch = FLAT[:3] + [(1.7, 2.1, 0, -7)]      # it 降 7 个半音
    usr_pitch = FLAT[:3] + [(1.7, 2.1, 0, -1)]      # 只降 1 个
    ctx = scenario([("today", 0.0, 0.4), ("i", 0.9, 0.4),
                    ("want", 1.3, 0.4), ("it", 1.7, 0.4)],
                   ref_pitch=ref_pitch, usr_pitch=usr_pitch)
    advice = build_advice(**ctx)
    assert "flat_fall" in kinds(advice)


def test_matching_fall_is_not_reported():
    pitch = FLAT[:3] + [(1.7, 2.1, 0, -7)]
    ctx = scenario([("today", 0.0, 0.4), ("i", 0.9, 0.4),
                    ("want", 1.3, 0.4), ("it", 1.7, 0.4)],
                   ref_pitch=pitch, usr_pitch=pitch)
    assert "flat_fall" not in kinds(build_advice(**ctx))


def test_advice_is_sorted_by_severity():
    ref_pitch = FLAT[:3] + [(1.7, 2.1, 0, -9)]
    usr_pitch = FLAT[:3] + [(1.7, 2.1, 0, 0)]
    ctx = scenario([("today", 0.0, 1.2), ("i", 1.25, 0.4),
                    ("want", 1.65, 0.4), ("it", 2.05, 0.4)],
                   ref_pitch=ref_pitch, usr_pitch=usr_pitch)
    advice = build_advice(**ctx)
    assert len(advice) >= 2
    assert [a.score for a in advice] == sorted((a.score for a in advice), reverse=True)


def test_well_done_lists_words_that_match():
    ctx = scenario([("today", 0.0, 0.4), ("i", 0.9, 0.4),
                    ("want", 1.3, 0.4), ("it", 1.7, 0.4)])
    good = well_done(ref_words=ctx["ref_words"], usr_words=ctx["usr_words"],
                     tokens=ctx["tokens"], rhythm=ctx["rhythm"])
    assert set(good) == {"today", "i", "want", "it"}


def test_no_issues_when_everything_matches():
    ctx = scenario([("today", 0.0, 0.4), ("i", 0.9, 0.4),
                    ("want", 1.3, 0.4), ("it", 1.7, 0.4)])
    assert build_advice(**ctx) == ()


def test_one_word_level_advice_per_word_keeps_only_the_worst():
    # today 同时拖长和该升没升：词级问题只保留一条（停顿是另一类，单独计）
    ref_pitch = [(0.0, 0.4, 0, 5)] + FLAT[1:]
    usr_pitch = [(0.0, 1.2, 0, -4)] + FLAT[1:]
    ctx = scenario([("today", 0.0, 1.2), ("i", 1.25, 0.4),
                    ("want", 1.65, 0.4), ("it", 2.05, 0.4)],
                   ref_pitch=ref_pitch, usr_pitch=usr_pitch)
    advice = build_advice(**ctx)
    word_level = [a for a in advice
                  if a.ref_index == 0 and a.kind != "missed_pause"]
    assert len(word_level) == 1


def test_reversed_direction_is_stated_not_hidden():
    # 原声升，用户反而降——不能说成「你只升了 0 个」
    ref_pitch = [(0.0, 0.4, 0, 5)] + FLAT[1:]
    usr_pitch = [(0.0, 0.4, 0, -4)] + FLAT[1:]
    ctx = scenario([("today", 0.0, 0.4), ("i", 0.9, 0.4),
                    ("want", 1.3, 0.4), ("it", 1.7, 0.4)],
                   ref_pitch=ref_pitch, usr_pitch=usr_pitch)
    item = next(a for a in build_advice(**ctx) if a.ref_index == 0)
    assert "反而降" in item.detail


def test_well_done_excludes_words_that_were_flagged():
    ref_pitch = FLAT[:3] + [(1.7, 2.1, 0, -8)]
    usr_pitch = FLAT[:3] + [(1.7, 2.1, 0, 0)]
    ctx = scenario([("today", 0.0, 0.4), ("i", 0.9, 0.4),
                    ("want", 1.3, 0.4), ("it", 1.7, 0.4)],
                   ref_pitch=ref_pitch, usr_pitch=usr_pitch)
    advice = build_advice(**ctx)
    good = well_done(ref_words=ctx["ref_words"], usr_words=ctx["usr_words"],
                     tokens=ctx["tokens"], rhythm=ctx["rhythm"], advice=advice)
    assert "it" not in good          # 被点名了，不能又说做对了
    assert "want" in good


def test_pause_advice_is_not_merged_with_the_word_own_issue():
    # today 既该升没升、后面又该停没停：这是两个动作，两条都要保留
    ref_pitch = [(0.0, 0.4, 0, 6)] + FLAT[1:]
    usr_pitch = [(0.0, 0.4, 0, -3)] + FLAT[1:]
    ctx = scenario([("today", 0.0, 0.4), ("i", 0.45, 0.4),
                    ("want", 0.85, 0.4), ("it", 1.25, 0.4)],
                   ref_pitch=ref_pitch, usr_pitch=usr_pitch)
    advice = build_advice(**ctx)
    today = {a.kind for a in advice if a.ref_index == 0}
    assert "missed_pause" in today
    assert today & {"flat_rise", "pitch_off", "stretched"}


def test_a_tiny_word_is_not_flagged_for_a_tiny_overrun():
    """原声 60 毫秒的词，你说了 170 毫秒——比例是 2.8 倍，绝对值只差 110 毫秒。
    转写的词边界本来就有几十毫秒的误差，这种「问题」不可操作，只会稀释真问题。"""
    usr = make([("today", 0.0, 0.4), ("i", 0.9, 0.17), ("want", 1.3, 0.4),
                ("it", 1.7, 0.4)])
    ref = make([("today", 0.0, 0.4), ("i", 0.9, 0.06), ("want", 1.3, 0.4),
                ("it", 1.7, 0.4)])
    tokens = diff_words([w.text for w in ref], [w.text for w in usr])
    pairs = tuple((x.ref_index, x.usr_index) for x in tokens if x.kind == "equal")
    advice = build_advice(
        ref_words=ref, usr_words=usr, tokens=tokens,
        rhythm=analyse_rhythm(ref, usr, pairs),
        ref_prosody=prosody_from(FLAT, 2.2), usr_prosody=prosody_from(FLAT, 2.2),
    )
    assert not [a for a in advice if a.kind == "stretched" and "i" in a.title]


def test_no_stretch_verdict_next_to_a_word_the_machine_missed():
    """隔壁词没对上，说明那条词边界靠不住，这个词的时长也就没法比。
    连读时 "out of" 的界线本来就是估的。"""
    ref = make([("today", 0.0, 0.4), ("i", 0.9, 0.4), ("want", 1.3, 0.16),
                ("it", 1.7, 0.4)])
    usr = make([("today", 0.0, 0.4), ("i", 0.9, 0.4), ("want", 1.3, 0.5),
                ("odd", 1.9, 0.4)])
    tokens = diff_words([w.text for w in ref], [w.text for w in usr])
    pairs = tuple((x.ref_index, x.usr_index) for x in tokens if x.kind == "equal")
    advice = build_advice(
        ref_words=ref, usr_words=usr, tokens=tokens,
        rhythm=analyse_rhythm(ref, usr, pairs),
        ref_prosody=prosody_from(FLAT, 2.4), usr_prosody=prosody_from(FLAT, 2.4),
    )
    assert not [a for a in advice if a.kind == "stretched" and "want" in a.title]
