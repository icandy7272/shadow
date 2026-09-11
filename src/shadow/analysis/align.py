"""音频 + 已知原文 → 每个词的真实边界（CTC 强制对齐）。

Whisper 的词时间戳是从交叉注意力做 DTW 猜出来的，不是对齐出来的。
实测全库 199 个单元：首词起点中位偏早 0.375 秒，89% 偏出 0.15 秒以上；
还见过把末词排到声音结束之后 0.5 秒、给首词零时长、把整句的词间停顿
全报成 0（而实际中间有 1.43 秒的停顿）。

强制对齐是拿声学模型逐帧算的。原文本来就在手上，没有理由去猜。
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import Sequence

import numpy as np
import soundfile as sf

from ..models import Word

_SPELLABLE = re.compile(r"[^A-Z']")
_state: dict = {}


def spell(word: str) -> str:
    """词形规整成声学模型认得的字母串。剩下空串说明这个词没法编码。"""
    return _SPELLABLE.sub("", word.upper())


def _bundle():
    """首次使用时才加载模型——没装 torchaudio 的环境照常跑其余功能。"""
    if "model" not in _state:
        import torch
        import torchaudio

        bundle = torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H
        _state.update(
            torch=torch, torchaudio=torchaudio, bundle=bundle,
            model=bundle.get_model(),
            table={char: index for index, char in enumerate(bundle.get_labels())},
        )
    return _state


def available() -> bool:
    try:
        import torchaudio  # noqa: F401
    except ImportError:
        return False
    return True


MAX_UNSPELLED = 0.2      # 编不出的词超过这个比例就整段不碰


def _tokens(spelled: Sequence[str], table: dict) -> list[int] | None:
    out: list[int] = []
    for index, word in enumerate(spelled):
        if index:
            out.append(table["|"])
        for char in word:
            if char not in table:
                return None
            out.append(table[char])
    return out


def _interpolate(words, placed: dict, count: int) -> tuple[Word, ...]:
    """编不出的词（数字之类）按左右邻居的空档平分。

    整段因为一个「18」就放弃太可惜——把它从 token 里摘掉，对齐照做，
    再把它塞回邻居之间。声学模型会把那一小段音频吞进相邻词或空白里，
    偏差是局部的。
    """
    out = []
    for index, word in enumerate(words):
        if index in placed:
            out.append(placed[index])
            continue
        before = next((placed[i].end for i in range(index - 1, -1, -1)
                       if i in placed), None)
        after = next((placed[i].start for i in range(index + 1, count)
                      if i in placed), None)
        low = before if before is not None else max(0.0, (after or 0.0) - 0.3)
        high = after if after is not None else low + 0.3
        if high <= low:
            high = low + 0.05
        out.append(replace(word, start=round(low, 3), end=round(high, 3)))
    return tuple(out)


def align_words(path: Path, words: Sequence[Word]) -> tuple[Word, ...] | None:
    """返回时间戳被改写过的词序列。对不上就返回 None，让调用方保留原样。

    对不上的两种情形都值得原样保留：词里有模型编不出的字符（数字、外语），
    或者词数多到这段音频物理上放不下——后者说明转写本身就错了，
    见过 13 个词配 0.56 秒音频。
    """
    if not words or not available():
        return None
    spelled = [spell(word.text) for word in words]
    keep = [index for index, text in enumerate(spelled) if text]
    if not keep or len(words) - len(keep) > len(words) * MAX_UNSPELLED:
        return None

    state = _bundle()
    tokens = _tokens([spelled[i] for i in keep], state["table"])
    if tokens is None:
        return None

    samples, rate = sf.read(str(path), dtype="float32", always_2d=False)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    torch, torchaudio = state["torch"], state["torchaudio"]
    wave = torch.from_numpy(np.ascontiguousarray(samples)).unsqueeze(0)
    target = state["bundle"].sample_rate
    if rate != target:
        wave = torchaudio.functional.resample(wave, rate, target)

    with torch.inference_mode():
        emission, _ = state["model"](wave)
    try:
        paths, scores = torchaudio.functional.forced_align(
            emission, torch.tensor([tokens], dtype=torch.int32), blank=0)
    except RuntimeError:
        return None
    spans = torchaudio.functional.merge_tokens(paths[0], scores[0].exp())

    seconds = wave.size(1) / emission.size(1) / target
    placed: dict[int, Word] = {}
    cursor = 0
    for order, index in enumerate(keep):
        letters = spelled[index]
        take = spans[cursor:cursor + len(letters)]
        cursor += len(letters) + (1 if order < len(keep) - 1 else 0)
        if not take:
            return None
        placed[index] = replace(words[index],
                                start=round(take[0].start * seconds, 3),
                                end=round(take[-1].end * seconds, 3))
    return _interpolate(words, placed, len(words))
