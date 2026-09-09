"""字体与文案。

matplotlib 内置字体不含 CJK 字形，直接写中文会渲染成一排方框。
找不到中文字体就整体退回英文，绝不出方框。
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

REF_COLOUR = "#1f77b4"
USR_COLOUR = "#d62728"
FLAG_COLOUR = "#111111"
MUTED_COLOUR = "#aaaaaa"

CJK_FONT_CANDIDATES = (
    "PingFang SC", "Hiragino Sans GB", "Heiti SC", "Songti SC",
    "STHeiti", "Arial Unicode MS", "Noto Sans CJK SC",
)

LABELS_ZH = {
    "ref": "原声", "usr": "你", "accuracy": "可懂度", "seconds": "秒",
    "rhythm_title": "图 1 · 节奏：真实秒数，块宽 = 时长，空隙 = 真实停顿",
    "rhythm_hint": "红线标出你在这个词上已经落后多少",
    "pitch_title": "图 2 · 音高：一词一格，块的高低 = 音高，块的斜度 = 词内升降（向下斜 = 降调）",
    "ref_legend": "原声（虚线）", "usr_legend": "你（实心）",
    "speech": "发声", "pause": "停顿",
}

LABELS_EN = {
    "ref": "reference", "usr": "you", "accuracy": "intelligibility", "seconds": "s",
    "rhythm_title": "Fig 1 - Rhythm: real seconds, block width = duration, gaps = real pauses",
    "rhythm_hint": "red lines show how far behind you are at that word",
    "pitch_title": "Fig 2 - Pitch: one slot per word, height = pitch, slant = movement within the word",
    "ref_legend": "reference (dashed)", "usr_legend": "you (solid)",
    "speech": "speech", "pause": "pauses",
}


def pick_cjk_font() -> str | None:
    available = {font.name for font in font_manager.fontManager.ttflist}
    for candidate in CJK_FONT_CANDIDATES:
        if candidate in available:
            return candidate
    return None


def configure_labels() -> dict[str, str]:
    plt.rcParams["axes.unicode_minus"] = False
    font = pick_cjk_font()
    if font is None:
        return LABELS_EN
    plt.rcParams["font.sans-serif"] = [font, *plt.rcParams["font.sans-serif"]]
    return LABELS_ZH
