"""裁剪点贴到停顿上。转写的词级时间戳常整体偏早，照它裁会带进上一句的尾巴。"""

import numpy as np
import pytest

from shadow.analysis.silence import quiet_midpoint


def frames(pattern, hop=0.01):
    """pattern: [(秒数, dB)]，展开成等间隔的两条数组。"""
    times, values = [], []
    t = 0.0
    for seconds, db in pattern:
        for _ in range(int(round(seconds / hop))):
            times.append(t)
            values.append(db)
            t += hop
    return np.array(times), np.array(values)


def test_finds_the_pause_between_two_stretches_of_speech():
    times, db = frames([(0.5, -18.0), (0.2, -46.0), (0.5, -18.0)])

    at = quiet_midpoint(times, db)

    assert at == pytest.approx(0.6, abs=0.02)


def test_ignores_a_brief_dip_inside_speech():
    """词与词之间的爆破音闭塞也会掉下去，但只有两三帧。"""
    times, db = frames([(0.4, -18.0), (0.03, -46.0), (0.4, -18.0),
                        (0.15, -46.0), (0.3, -18.0)])

    at = quiet_midpoint(times, db)

    assert at == pytest.approx(0.905, abs=0.02)


def test_returns_none_when_speech_never_stops():
    times, db = frames([(1.0, -18.0)])

    assert quiet_midpoint(times, db) is None


def test_returns_none_on_an_empty_window():
    assert quiet_midpoint(np.array([]), np.array([])) is None
