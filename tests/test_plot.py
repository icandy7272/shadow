import numpy as np

from shadow.analysis.prosody import Prosody
from shadow.analysis.timing import WordTiming
from shadow.report.plot import pitch_axis_limits, render_comparison


def fake_prosody(duration=2.0, offset=0.0):
    times = np.arange(0.0, duration, 0.01)
    return Prosody(
        times=times,
        f0_hz=np.full(times.shape, 200.0),
        semitones=np.sin(times * 3.0) + offset,
        energy_db=-np.abs(np.cos(times * 3.0)) * 10.0,
        duration=duration,
    )


TIMINGS = (
    WordTiming(0, "should", "equal", 0.30, 0.32, 1.07),
    WordTiming(1, "have", "equal", 0.08, 0.26, 3.25),
    WordTiming(2, "been", "missing", 0.25, None, None),
    WordTiming(3, "there", "equal", 0.30, 0.21, 0.70),
)


def test_render_writes_a_png(tmp_path):
    out = tmp_path / "cmp.png"
    reference = fake_prosody()
    user = fake_prosody(offset=0.5)
    render_comparison(
        ref_prosody=reference,
        usr_prosody=user,
        usr_times_warped=user.times,
        timings=TIMINGS,
        out_path=out,
        title="test",
        accuracy=0.75,
    )
    assert out.exists()
    assert out.stat().st_size > 10_000


def test_labels_fall_back_to_english_without_cjk_font(monkeypatch):
    from shadow.report import plot

    monkeypatch.setattr(plot, "_pick_cjk_font", lambda: None)
    assert plot.configure_labels() is plot.LABELS_EN


def test_labels_use_chinese_when_font_available(monkeypatch):
    from shadow.report import plot

    monkeypatch.setattr(plot, "_pick_cjk_font", lambda: "PingFang SC")
    assert plot.configure_labels() is plot.LABELS_ZH


def test_unrecognised_positions_finds_words_with_no_ratio():
    from shadow.report.plot import unrecognised_positions

    assert unrecognised_positions(TIMINGS) == (2,)
    assert unrecognised_positions(()) == ()


def test_render_handles_all_missing_timings(tmp_path):
    out = tmp_path / "cmp2.png"
    reference = fake_prosody()
    timings = tuple(
        WordTiming(i, f"w{i}", "missing", 0.2, None, None) for i in range(4)
    )
    render_comparison(
        ref_prosody=reference,
        usr_prosody=reference,
        usr_times_warped=reference.times,
        timings=timings,
        out_path=out,
        title="empty",
        accuracy=0.0,
    )
    assert out.exists()


def test_pitch_axis_ignores_outliers():
    # 少数离群帧不该把纵轴撑开，否则真实曲线被压扁成一条线
    clean = np.concatenate([np.linspace(-4.0, 4.0, 400), np.array([28.0, 29.0])])
    low, high = pitch_axis_limits(clean)
    assert high < 12.0
    assert low > -12.0


def test_pitch_axis_handles_all_nan():
    low, high = pitch_axis_limits(np.full(50, np.nan))
    assert low < high


def test_render_draws_tempo_line_when_speeds_differ(tmp_path):
    out = tmp_path / "tempo.png"
    user = fake_prosody(duration=3.0)
    render_comparison(
        ref_prosody=fake_prosody(duration=2.0),
        usr_prosody=user,
        usr_times_warped=user.times * (2.0 / 3.0),
        timings=TIMINGS,
        out_path=out,
        title="tempo",
        accuracy=0.75,
    )
    assert out.exists()


def test_render_rejects_mismatched_warped_axis(tmp_path):
    # 长度不匹配时 matplotlib 只会抛一句看不懂的 ValueError
    import pytest

    with pytest.raises(ValueError, match="必须由 usr_prosody.times"):
        render_comparison(
            ref_prosody=fake_prosody(duration=2.0),
            usr_prosody=fake_prosody(duration=3.0),
            usr_times_warped=fake_prosody(duration=2.0).times,
            timings=TIMINGS,
            out_path=tmp_path / "bad.png",
            title="bad",
            accuracy=0.0,
        )
