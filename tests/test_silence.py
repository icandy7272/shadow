"""裁剪点贴到停顿上。转写的词级时间戳常整体偏早，照它裁会带进上一句的尾巴。"""

import numpy as np
import pytest

from shadow.analysis.silence import loud_level, quiet_midpoint, voiced_fraction


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


def test_loud_level_is_where_the_source_is_speaking():
    """「在说话」的典型响度取高分位，不取最大值——一声咳嗽不该定标准。"""
    energy = np.linspace(-80.0, -20.0, 101)

    assert loud_level(energy) == pytest.approx(-26.0)


def test_loud_level_of_nothing_is_very_quiet():
    assert loud_level(np.array([])) < -100


def test_voiced_fraction_follows_the_source_not_an_absolute_level():
    """录音电平差得远：同样 -50 dB，在响的素材里是静音，在轻的素材里是说话。"""
    span = np.array([-50.0] * 8 + [-30.0] * 2)

    assert voiced_fraction(span, loud_db=-25.0) == pytest.approx(0.2)
    assert voiced_fraction(span, loud_db=-45.0) == pytest.approx(1.0)


def test_voiced_fraction_of_an_empty_span_is_zero():
    """时间范围落在音频之外，一帧都取不到——那就是没声音。"""
    assert voiced_fraction(np.array([]), loud_db=-20.0) == 0.0
