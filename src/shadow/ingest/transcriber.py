"""mlx-whisper 封装：音频 -> 词级时间戳。"""

from __future__ import annotations

from pathlib import Path

from .. import config
from ..models import Word


class TranscribeError(RuntimeError):
    pass


def transcribe_words(wav_path: Path) -> tuple[Word, ...]:
    """转写音频，返回扁平的词序列。

    模型固定为 config.WHISPER_MODEL——素材与用户录音必须用同一个模型，
    否则 diff 会把模型缺陷算成用户的发音问题。
    """
    import mlx_whisper

    try:
        result = mlx_whisper.transcribe(
            str(wav_path),
            path_or_hf_repo=config.WHISPER_MODEL,
            language=config.WHISPER_LANGUAGE,
            word_timestamps=True,
        )
    except Exception as exc:  # 模型下载失败、音频损坏等
        raise TranscribeError(f"转写失败（{wav_path}）：{exc}") from exc

    words: list[Word] = []
    for segment in result.get("segments", ()):
        for item in segment.get("words", ()):
            text = str(item.get("word", "")).strip()
            if not text:
                continue
            words.append(
                Word(text=text, start=float(item["start"]), end=float(item["end"]))
            )
    return tuple(words)
