"""三面板对比图。

Panel 1 语调轮廓、Panel 2 轻重分布、Panel 3 每词时长比值——
Panel 3 是治「逐词等重音」的主图。
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402  (必须在 use("Agg") 之后)
import numpy as np  # noqa: E402
from matplotlib import font_manager  # noqa: E402

from ..analysis.prosody import Prosody  # noqa: E402
from ..analysis.timing import WordTiming  # noqa: E402

REF_COLOUR = "#1f77b4"
USR_COLOUR = "#d62728"
WRONG_COLOUR = "#ff7f0e"
FLAG_COLOUR = "#999999"

# matplotlib 内置字体不含 CJK 字形，直接写中文会渲染成一排方框。
CJK_FONT_CANDIDATES = (
    "PingFang SC", "Hiragino Sans GB", "Heiti SC", "Songti SC",
    "STHeiti", "Arial Unicode MS", "Noto Sans CJK SC",
)

LABELS_ZH = {
    "ref": "原声",
    "usr": "你",
    "accuracy": "可懂度",
    "tempo": "你的整体语速",
    "p1_title": "Panel 1 · 语调轮廓：起伏形状和重音落点是否一致",
    "p1_y": "音高（半音，相对各自中位数）",
    "p2_title": "Panel 2 · 轻重分布",
    "p2_y": "能量（dB）",
    "p2_x": "时间（秒，已对齐到原声轴）",
    "p3_title": "Panel 3 · 节奏：看柱子相对虚线（你的平均语速）的高低，不是相对 1.0；红底 = 没听出来，橙底 = 听成了别的词",
    "p3_y": "你的时长 / 原声时长",
}

LABELS_EN = {
    "ref": "reference",
    "usr": "you",
    "accuracy": "intelligibility",
    "tempo": "your overall tempo",
    "p1_title": "Panel 1 - Intonation contour: same shape and stress placement?",
    "p1_y": "pitch (semitones, relative to own median)",
    "p2_title": "Panel 2 - Loudness distribution",
    "p2_y": "energy (dB)",
    "p2_x": "time (s, warped onto reference axis)",
    "p3_title": "Panel 3 - Rhythm: read bars against the dotted line (your own tempo), not 1.0; red = not recognised, orange = heard as another word",
    "p3_y": "your duration / reference duration",
}


SEMITONE_LIMIT = 18.0


def pitch_axis_limits(*curves: np.ndarray) -> tuple[float, float]:
    """按稳健分位数定纵轴，别让个别离群帧把真实曲线压扁。"""
    finite = np.concatenate([c[np.isfinite(c)] for c in curves if c.size])
    if finite.size == 0:
        return -1.0, 1.0
    low, high = np.percentile(finite, [1, 99])
    pad = max(1.0, 0.15 * (high - low))
    return (
        max(-SEMITONE_LIMIT, low - pad),
        min(SEMITONE_LIMIT, high + pad),
    )


def _pick_cjk_font() -> str | None:
    available = {font.name for font in font_manager.fontManager.ttflist}
    for candidate in CJK_FONT_CANDIDATES:
        if candidate in available:
            return candidate
    return None


def configure_labels() -> dict[str, str]:
    """装得上中文字体就用中文标注，装不上就整体退回英文——绝不渲染方框。"""
    plt.rcParams["axes.unicode_minus"] = False
    font = _pick_cjk_font()
    if font is None:
        return LABELS_EN
    plt.rcParams["font.sans-serif"] = [font, *plt.rcParams["font.sans-serif"]]
    return LABELS_ZH


def unrecognised_positions(timings: Sequence[WordTiming]) -> tuple[int, ...]:
    """比值为 None 的词在 Panel 3 上的位置——机器没听出来，必须显式标红。"""
    return tuple(
        index for index, timing in enumerate(timings) if timing.ratio is None
    )


def flag_colour(timing: WordTiming) -> str:
    """听成别的词和完全没听出来是两种不同的问题，用颜色区分。"""
    return WRONG_COLOUR if timing.kind == "wrong" else USR_COLOUR


def render_comparison(
    *,
    ref_prosody: Prosody,
    usr_prosody: Prosody,
    usr_times_warped: np.ndarray,
    timings: Sequence[WordTiming],
    out_path: Path,
    title: str,
    accuracy: float,
) -> Path:
    if len(usr_times_warped) != len(usr_prosody.times):
        raise ValueError(
            f"弯折后的时间轴有 {len(usr_times_warped)} 个点，"
            f"但用户韵律曲线有 {len(usr_prosody.times)} 个点。"
            f"usr_times_warped 必须由 usr_prosody.times 弯折而来。"
        )

    labels = configure_labels()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    figure, (ax_pitch, ax_energy, ax_timing) = plt.subplots(
        3, 1, figsize=(14, 10), gridspec_kw={"height_ratios": [2, 1, 2]}
    )
    figure.suptitle(
        f"{title}    {labels['accuracy']} {accuracy * 100:.0f}%", fontsize=13
    )

    ax_pitch.plot(ref_prosody.times, ref_prosody.semitones,
                  color=REF_COLOUR, linewidth=2.0, label=labels["ref"])
    ax_pitch.plot(usr_times_warped, usr_prosody.semitones,
                  color=USR_COLOUR, linewidth=1.6, linestyle="--", label=labels["usr"])
    ax_pitch.axhline(0.0, color=FLAG_COLOUR, linewidth=0.6)
    ax_pitch.set_ylabel(labels["p1_y"])
    ax_pitch.set_title(labels["p1_title"], loc="left")
    ax_pitch.set_ylim(*pitch_axis_limits(ref_prosody.semitones, usr_prosody.semitones))
    ax_pitch.legend(loc="upper right")
    ax_pitch.grid(alpha=0.2)

    ax_energy.plot(ref_prosody.times, ref_prosody.energy_db,
                   color=REF_COLOUR, linewidth=1.6, label=labels["ref"])
    ax_energy.plot(usr_times_warped, usr_prosody.energy_db,
                   color=USR_COLOUR, linewidth=1.4, linestyle="--", label=labels["usr"])
    ax_energy.set_ylabel(labels["p2_y"])
    ax_energy.set_xlabel(labels["p2_x"])
    ax_energy.set_title(labels["p2_title"], loc="left")
    ax_energy.grid(alpha=0.2)

    positions = np.arange(len(timings))
    ratios = [t.ratio if t.ratio is not None else 0.0 for t in timings]
    ax_timing.bar(positions, ratios, color=REF_COLOUR)

    # 没听出来的词比值为 None，柱高为 0 会让它直接从图上消失——而「没被听懂」
    # 恰恰是最该看见的信号。改用红色背景带 + 红色词标出来，不伪造一个比值。
    for position in unrecognised_positions(timings):
        ax_timing.axvspan(position - 0.45, position + 0.45,
                          color=flag_colour(timings[position]), alpha=0.18, zorder=0)

    ax_timing.axhline(1.0, color="#333333", linewidth=1.2)

    # 整体语速不同时，1.0 这条线会误导：慢 40% 的人柱子普遍在 1.4 附近，
    # 那是他的平均水平而非问题。再画一条自己的平均线，看的是分布不是绝对值。
    tempo = (
        usr_prosody.duration / ref_prosody.duration
        if ref_prosody.duration > 0 else 1.0
    )
    if abs(tempo - 1.0) > 0.05:
        ax_timing.axhline(tempo, color="#8c564b", linewidth=1.2, linestyle=":")
        ax_timing.text(
            0.995, tempo, f" {labels['tempo']} {tempo:.2f}x ",
            transform=ax_timing.get_yaxis_transform(),
            ha="right", va="bottom", fontsize=9, color="#8c564b",
        )
    ax_timing.set_xticks(positions)
    ax_timing.set_xticklabels(
        [t.text for t in timings], rotation=60, ha="right", fontsize=8
    )
    for index in unrecognised_positions(timings):
        ax_timing.get_xticklabels()[index].set_color(flag_colour(timings[index]))
    ax_timing.set_ylabel(labels["p3_y"])
    ax_timing.set_title(labels["p3_title"], loc="left")
    ax_timing.grid(alpha=0.2, axis="y")

    figure.tight_layout(rect=(0, 0, 1, 0.97))
    figure.savefig(out_path, dpi=120)
    plt.close(figure)
    return out_path
