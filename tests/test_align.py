import numpy as np
import pytest

from shadow.analysis.align import build_anchors, warp_user_times
from shadow.models import Word


def words_at(starts, *, dur=0.4):
    return tuple(Word(text=f"w{i}", start=s, end=s + dur) for i, s in enumerate(starts))


REF = words_at([0.0, 1.0, 2.0, 3.0, 4.0])
ALL_PAIRS = tuple((i, i) for i in range(5))


def test_identical_timings_warp_to_identity():
    times = np.linspace(0.0, 4.4, 50)
    warped = warp_user_times(
        times, ref_words=REF, usr_words=REF, pairs=ALL_PAIRS,
        ref_duration=4.4, usr_duration=4.4,
    )
    assert np.allclose(warped, times, atol=1e-6)


def test_uniformly_slower_user_is_compressed():
    usr = words_at([0.0, 2.0, 4.0, 6.0, 8.0], dur=0.8)
    warped = warp_user_times(
        np.array([0.0, 4.4, 8.8]), ref_words=REF, usr_words=usr, pairs=ALL_PAIRS,
        ref_duration=4.4, usr_duration=8.8,
    )
    assert warped[0] == pytest.approx(0.0)
    assert warped[1] == pytest.approx(2.2, abs=0.1)
    assert warped[2] == pytest.approx(4.4, abs=0.1)


def test_falls_back_to_linear_scale_when_too_few_anchors():
    usr = words_at([0.0, 2.0, 4.0, 6.0, 8.0], dur=0.8)
    warped = warp_user_times(
        np.array([0.0, 4.4, 8.8]), ref_words=REF, usr_words=usr, pairs=((0, 0),),
        ref_duration=4.4, usr_duration=8.8,
    )
    assert np.allclose(warped, np.array([0.0, 2.2, 4.4]), atol=1e-6)


def test_output_is_monotonic_non_decreasing():
    usr = words_at([0.0, 0.9, 2.6, 3.1, 5.0], dur=0.5)
    times = np.linspace(0.0, 5.5, 200)
    warped = warp_user_times(
        times, ref_words=REF, usr_words=usr, pairs=ALL_PAIRS,
        ref_duration=4.4, usr_duration=5.5,
    )
    assert np.all(np.diff(warped) >= -1e-9)


def test_build_anchors_includes_endpoints_and_is_strictly_increasing():
    usr = words_at([0.0, 1.5, 3.0, 4.5, 6.0])
    xs, ys = build_anchors(
        ref_words=REF, usr_words=usr, pairs=ALL_PAIRS,
        ref_duration=4.4, usr_duration=6.4,
    )
    assert xs[0] == 0.0 and ys[0] == 0.0
    assert xs[-1] == pytest.approx(6.4) and ys[-1] == pytest.approx(4.4)
    assert np.all(np.diff(xs) > 0) and np.all(np.diff(ys) > 0)
