"""词块反馈图：两张图，各管一件事。

图 1 只管时间（真实秒数轴，块全水平），图 2 只管音高（一词一格，斜块）。
把两个变量塞进同一张图会让人两个都看不懂——这是曲线版失败的教训。

一切都挂在词上：使用者看不懂脱离单词的曲线，看不出「哪个词快了、哪个词慢了」。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch, Polygon

from ..analysis.diff import KIND_EQUAL, DiffToken
from ..analysis.prosody import Prosody
from ..analysis.rhythm import Rhythm
from ..models import Word
from . import geometry
from .geometry import Flag, PauseNote  # noqa: F401  给命令行和网页共用
from .style import FLAG_COLOUR, MUTED_COLOUR, REF_COLOUR, USR_COLOUR, configure_labels

SEMITONE_SCALE = 0.11
BLOCK_HALF = 0.13


def _quad(x0: float, x1: float, y0: float, y1: float, **kwargs) -> Polygon:
    return Polygon(
        [(x0, y0 - BLOCK_HALF), (x0, y0 + BLOCK_HALF),
         (x1, y1 + BLOCK_HALF), (x1, y1 - BLOCK_HALF)],
        closed=True, **kwargs,
    )


def _draw_rhythm(ax, labels, view) -> None:
    height = 0.20
    for base, blocks, colour, name in (
        (0.42, view.ref, REF_COLOUR, labels["ref"]),
        (-0.42, view.usr, USR_COLOUR, labels["usr"]),
    ):
        ax.text(-0.13, base, name, ha="right", va="center", fontsize=12, color=colour)
        for block in blocks:
            ax.add_patch(FancyBboxPatch(
                (block.start, base - height), block.width, 2 * height,
                boxstyle="round,pad=0.004,rounding_size=0.03",
                facecolor=colour, alpha=0.28, edgecolor=colour, lw=1.0))
            ax.text(block.start + block.width / 2, base, block.text,
                    ha="center", va="center",
                    fontsize=min(11, max(6, 26 * block.width)), color=colour)

    for lag in view.lags:
        ax.plot([lag.ref_at, lag.usr_at], [0.42 - height, -0.42 + height],
                color=USR_COLOUR if lag.marked else MUTED_COLOUR,
                lw=1.5 if lag.marked else 0.6,
                alpha=0.85 if lag.marked else 0.3, zorder=1)
        if lag.marked:
            ax.text((lag.ref_at + lag.usr_at) / 2, 0.0,
                    f"{lag.seconds:+.1f}{labels['seconds']}",
                    ha="center", va="center", fontsize=8.5, color=USR_COLOUR,
                    bbox=dict(fc="white", ec="none", pad=0.6), zorder=4)

    for span in view.spans:
        ax.axvspan(span.start, span.end, color=USR_COLOUR, alpha=0.16, zorder=0)
        ax.text((span.start + span.end) / 2, 0.80, span.flag, ha="center",
                va="bottom", fontsize=9.5, color=USR_COLOUR, zorder=5)

    ax.set_title(f"{labels['rhythm_title']}。{labels['rhythm_hint']}",
                 fontsize=12, loc="left")
    ax.set_xlim(-0.35, view.seconds + 0.1)
    ax.set_ylim(-0.95, 0.95)
    ax.set_yticks([])
    ax.set_xlabel(labels["seconds"], fontsize=10)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)


def _draw_pitch(ax, labels, slots) -> None:
    ax.axhline(0, color=MUTED_COLOUR, lw=0.8, ls=":", zorder=0)
    for slot in slots:
        ax.add_patch(_quad(slot.x, slot.x + slot.ref_width,
                           slot.ref_from * SEMITONE_SCALE,
                           slot.ref_to * SEMITONE_SCALE,
                           facecolor="none", edgecolor=REF_COLOUR, lw=1.7,
                           ls=(0, (4, 2)), zorder=3))
        label_width = slot.ref_width
        if slot.usr_from is not None:
            ax.add_patch(_quad(slot.x, slot.x + slot.usr_width,
                               slot.usr_from * SEMITONE_SCALE,
                               slot.usr_to * SEMITONE_SCALE,
                               facecolor=USR_COLOUR,
                               alpha=0.45 if slot.flag else 0.22,
                               edgecolor=USR_COLOUR,
                               lw=1.6 if slot.flag else 0.7, zorder=2))
            label_width = max(slot.ref_width, slot.usr_width)
            if slot.flag:
                ax.text(slot.x + label_width / 2, -0.60, slot.flag, ha="center",
                        va="top", fontsize=8.5, color=FLAG_COLOUR, zorder=5)
        ax.text(slot.x + label_width / 2, 0.50, slot.text,
                ha="center", va="bottom",
                fontsize=min(12, max(7, 190 * label_width)), color="#222222", zorder=4)

    ax.legend(handles=[
        Line2D([0], [0], color=REF_COLOUR, lw=1.8, ls="--", label=labels["ref_legend"]),
        Line2D([0], [0], color=USR_COLOUR, lw=6, alpha=0.4, label=labels["usr_legend"]),
    ], loc="upper right", frameon=False, fontsize=11, ncol=2)
    ax.set_title(labels["pitch_title"], fontsize=12, loc="left")
    ax.set_xlim(-0.01, 1.01)
    ax.set_ylim(-1.05, 0.92)
    ax.axis("off")


def render_feedback(
    *,
    ref_words: Sequence[Word],
    usr_words: Sequence[Word],
    tokens: Sequence[DiffToken],
    rhythm: Rhythm,
    ref_prosody: Prosody,
    usr_prosody: Prosody,
    flags: Sequence[Flag],
    pause_notes: Sequence[PauseNote] = (),
    accuracy: float,
    text: str,
    out_path: Path,
) -> Path:
    if not ref_words or not usr_words:
        raise ValueError("原声或录音的词序列为空，无法出图。")

    labels = configure_labels()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    pairs = tuple((t.ref_index, t.usr_index) for t in tokens
                  if t.kind == KIND_EQUAL
                  and t.ref_index is not None and t.usr_index is not None)

    view = geometry.rhythm_view(ref_words=ref_words, usr_words=usr_words,
                                rhythm=rhythm, pause_notes=pause_notes)
    slots = geometry.pitch_slots(ref_words=ref_words, usr_words=usr_words,
                                 pairs=pairs, ref_prosody=ref_prosody,
                                 usr_prosody=usr_prosody, flags=flags)

    figure, (ax_rhythm, ax_pitch) = plt.subplots(
        2, 1, figsize=(16, 7.4), gridspec_kw={"height_ratios": [1.0, 1.25]})
    _draw_rhythm(ax_rhythm, labels, view)
    _draw_pitch(ax_pitch, labels, slots)

    figure.suptitle(
        f"{text}\n{labels['accuracy']} {accuracy * 100:.0f}%    "
        f"{labels['speech']} {rhythm.speech_ratio:.2f}x    "
        f"{labels['pause']} "
        f"{'-' if rhythm.pause_ratio is None else format(rhythm.pause_ratio, '.2f') + 'x'}",
        fontsize=12, y=0.995)
    figure.tight_layout(rect=(0, 0, 1, 0.94))
    figure.savefig(out_path, dpi=130)
    plt.close(figure)
    return out_path
