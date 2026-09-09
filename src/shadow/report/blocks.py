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
from ..analysis.prosody import Prosody, word_contour
from ..analysis.rhythm import Rhythm
from ..models import Word
from .style import FLAG_COLOUR, MUTED_COLOUR, REF_COLOUR, USR_COLOUR, configure_labels

LAG_STEP_SEC = 0.15      # 落后量变化超过这个才标注，否则每个词都标太吵
SEMITONE_SCALE = 0.11
BLOCK_HALF = 0.13
SLOT_PAD = 0.004


@dataclass(frozen=True, slots=True)
class Flag:
    usr_index: int
    text: str


def lag_annotations(
    lags: Sequence[tuple[int, float]], *, step: float = LAG_STEP_SEC
) -> tuple[tuple[int, float], ...]:
    """只在落后量明显变化处标注。全标会把图糊掉。"""
    marked: list[tuple[int, float]] = []
    last = 0.0
    for ref_index, lag in lags:
        if abs(lag - last) >= step:
            marked.append((ref_index, lag))
            last = lag
    return tuple(marked)


def _quad(x0: float, x1: float, y0: float, y1: float, **kwargs) -> Polygon:
    return Polygon(
        [(x0, y0 - BLOCK_HALF), (x0, y0 + BLOCK_HALF),
         (x1, y1 + BLOCK_HALF), (x1, y1 - BLOCK_HALF)],
        closed=True, **kwargs,
    )


def _draw_rhythm(ax, labels, ref_words, usr_words, rhythm, missed_pauses) -> None:
    height = 0.20
    for base, words, colour, name in (
        (0.42, ref_words, REF_COLOUR, labels["ref"]),
        (-0.42, usr_words, USR_COLOUR, labels["usr"]),
    ):
        origin = words[0].start
        ax.text(-0.13, base, name, ha="right", va="center", fontsize=12, color=colour)
        for word in words:
            x0 = word.start - origin
            width = max(word.duration, 0.02)
            ax.add_patch(FancyBboxPatch(
                (x0, base - height), width, 2 * height,
                boxstyle="round,pad=0.004,rounding_size=0.03",
                facecolor=colour, alpha=0.28, edgecolor=colour, lw=1.0))
            ax.text(x0 + width / 2, base, word.text.strip(".,!?"),
                    ha="center", va="center",
                    fontsize=min(11, max(6, 26 * width)), color=colour)

    marked = dict(lag_annotations(rhythm.lags))
    ref_origin = ref_words[0].start
    for ref_index, lag in rhythm.lags:
        a = ref_words[ref_index].start - ref_origin
        b = a + lag
        important = ref_index in marked
        ax.plot([a, b], [0.42 - height, -0.42 + height],
                color=USR_COLOUR if important else MUTED_COLOUR,
                lw=1.5 if important else 0.6,
                alpha=0.85 if important else 0.3, zorder=1)
        if important:
            ax.text((a + b) / 2, 0.0, f"{lag:+.1f}{labels['seconds']}",
                    ha="center", va="center", fontsize=8.5, color=USR_COLOUR,
                    bbox=dict(fc="white", ec="none", pad=0.6), zorder=4)

    for ref_index in missed_pauses:
        if ref_index + 1 >= len(ref_words):
            continue
        a = ref_words[ref_index].end - ref_origin
        b = ref_words[ref_index + 1].start - ref_origin
        ax.axvspan(a, b, color=USR_COLOUR, alpha=0.16, zorder=0)
        ax.text((a + b) / 2, 0.80, labels["missed_pause"], ha="center", va="bottom",
                fontsize=9.5, color=USR_COLOUR, zorder=5)

    ax.set_title(f"{labels['rhythm_title']}。{labels['rhythm_hint']}",
                 fontsize=12, loc="left")
    ax.set_xlim(-0.35, max(rhythm.ref_span, rhythm.usr_span) + 0.1)
    ax.set_ylim(-0.95, 0.95)
    ax.set_yticks([])
    ax.set_xlabel(labels["seconds"], fontsize=10)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)


def _draw_pitch(ax, labels, ref_words, usr_words, pairs, ref_prosody, usr_prosody,
                flags) -> None:
    ref_span = ref_words[-1].end - ref_words[0].start or 1.0
    usr_span = (usr_words[-1].end - usr_words[0].start) if usr_words else 1.0
    usr_span = usr_span or 1.0
    matched = dict(pairs)
    flagged = {f.usr_index: f.text for f in flags}

    slots: list[tuple[float, float, float, int, int | None]] = []
    cursor = 0.0
    for index, word in enumerate(ref_words):
        ref_width = word.duration / ref_span
        usr_index = matched.get(index)
        usr_width = (usr_words[usr_index].duration / usr_span
                     if usr_index is not None else 0.0)
        slots.append((cursor, ref_width, usr_width, index, usr_index))
        gap = ((ref_words[index + 1].start - word.end) / ref_span
               if index + 1 < len(ref_words) else 0.0)
        cursor += max(ref_width, usr_width) + gap + SLOT_PAD
    total = cursor or 1.0

    ax.axhline(0, color=MUTED_COLOUR, lw=0.8, ls=":", zorder=0)
    for start, ref_width, usr_width, ref_index, usr_index in slots:
        x0 = start / total
        ref_w = ref_width / total
        usr_w = usr_width / total
        word = ref_words[ref_index]
        contour = word_contour(ref_prosody, word.start, word.end) or (0.0, 0.0)
        ax.add_patch(_quad(x0, x0 + max(ref_w, 0.002),
                           contour[0] * SEMITONE_SCALE, contour[1] * SEMITONE_SCALE,
                           facecolor="none", edgecolor=REF_COLOUR, lw=1.7,
                           ls=(0, (4, 2)), zorder=3))
        label_width = ref_w
        if usr_index is not None:
            usr = usr_words[usr_index]
            usr_contour = word_contour(usr_prosody, usr.start, usr.end) or (0.0, 0.0)
            note = flagged.get(usr_index)
            ax.add_patch(_quad(x0, x0 + max(usr_w, 0.002),
                               usr_contour[0] * SEMITONE_SCALE,
                               usr_contour[1] * SEMITONE_SCALE,
                               facecolor=USR_COLOUR, alpha=0.45 if note else 0.22,
                               edgecolor=USR_COLOUR, lw=1.6 if note else 0.7, zorder=2))
            label_width = max(ref_w, usr_w)
            if note:
                ax.text(x0 + label_width / 2, -0.60, note, ha="center", va="top",
                        fontsize=8.5, color=FLAG_COLOUR, zorder=5)
        ax.text(x0 + label_width / 2, 0.50, word.text.strip(".,!?"),
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
    missed_pauses: Sequence[int] = (),
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

    figure, (ax_rhythm, ax_pitch) = plt.subplots(
        2, 1, figsize=(16, 7.4), gridspec_kw={"height_ratios": [1.0, 1.25]})
    _draw_rhythm(ax_rhythm, labels, ref_words, usr_words, rhythm, missed_pauses)
    _draw_pitch(ax_pitch, labels, ref_words, usr_words, pairs,
                ref_prosody, usr_prosody, flags)

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
