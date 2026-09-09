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
    "p1_title": "Panel 1 · 语调轮廓：起伏形状和重音落点是否一致",
    "p1_y": "音高（半音，相对各自中位数）",
    "p2_title": "Panel 2 · 轻重分布",
    "p2_y": "能量（dB）",
    "p2_x": "时间（秒，已对齐到原声轴）",
    "p3_title": "Panel 3 · 节奏：柱子高于 1.0 = 拖长了（该弱读却发满），红柱 = 机器没听出这个词",
    "p3_y": "你的时长 / 原声时长",
}

LABELS_EN = {
    "ref": "reference",
    "usr": "you",
    "accuracy": "intelligibility",
    "p1_title": "Panel 1 - Intonation contour: same shape and stress placement?",
    "p1_y": "pitch (semitones, relative to own median)",
    "p2_title": "Panel 2 - Loudness distribution",
    "p2_y": "energy (dB)",
    "p2_x": "time (s, warped onto reference axis)",
    "p3_title": "Panel 3 - Rhythm: bar above 1.0 = stretched (should be reduced); red = not recognised",
    "p3_y": "your duration / reference duration",
}


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
    colours = [USR_COLOUR if t.ratio is None else REF_COLOUR for t in timings]
    ax_timing.bar(positions, ratios, color=colours)
    ax_timing.axhline(1.0, color="#333333", linewidth=1.2)
    ax_timing.set_xticks(positions)
    ax_timing.set_xticklabels(
        [t.text for t in timings], rotation=60, ha="right", fontsize=8
    )
    ax_timing.set_ylabel(labels["p3_y"])
    ax_timing.set_title(labels["p3_title"], loc="left")
    ax_timing.grid(alpha=0.2, axis="y")

    figure.tight_layout(rect=(0, 0, 1, 0.97))
    figure.savefig(out_path, dpi=120)
    plt.close(figure)
    return out_path
