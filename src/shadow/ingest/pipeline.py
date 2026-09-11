"""导入流程编排：URL -> 音频 -> 转写 -> 切片 -> 挖空 -> 入库。

时长上限在下载之前检查，避免用户等十分钟才发现失败。
任何一步失败都把原始错误写进 sources.error 并原样抛出。
"""

from __future__ import annotations

import sqlite3
import tempfile
from dataclasses import replace
from pathlib import Path

from .. import config, db
from ..drill.blanks import select_blanks
from ..models import Segment, with_blanks
from .downloader import download_audio, probe, validate_url
from .segmenter import split_into_segments
from .transcriber import transcribe_words


class ImportError_(RuntimeError):
    """导入前置校验失败（命名避开内置 ImportError）。"""


def _apply_blanks(segments: tuple[Segment, ...]) -> tuple[Segment, ...]:
    return tuple(
        replace(segment, words=with_blanks(segment.words, select_blanks(segment.words)))
        for segment in segments
    )


def _realign(wav_path, words):
    """转写给的词时间戳是猜的，用强制对齐重算一遍。

    实测偏差很大：首词起点中位偏早 0.375 秒，见过把末词排到声音之外
    半秒、把整句的词间停顿全报成 0。对不上就保留原样，不影响导入。
    """
    from ..analysis.align import align_words

    try:
        aligned = align_words(wav_path, words)
    except Exception:
        return words
    return aligned or words


def import_source(url: str, *, conn: sqlite3.Connection) -> int:
    clean_url = validate_url(url)
    title, duration = probe(clean_url)

    limit_sec = config.MAX_SOURCE_MINUTES * 60
    if duration > limit_sec:
        raise ImportError_(
            f"素材时长 {duration / 60:.1f} 分钟，超过上限 "
            f"{config.MAX_SOURCE_MINUTES:.0f} 分钟。请改用更短的素材或先自行裁剪。"
        )

    source_id = db.create_source(
        conn, url=clean_url, title=title, duration_sec=duration
    )
    try:
        db.set_source_status(conn, source_id, db.STATUS_DOWNLOADING)
        wav_path = config.source_audio_dir() / f"{source_id}.wav"
        with tempfile.TemporaryDirectory() as workdir:
            download_audio(clean_url, wav_path, workdir=Path(workdir))

        db.set_source_status(conn, source_id, db.STATUS_TRANSCRIBING)
        words = transcribe_words(wav_path)

        db.set_source_status(conn, source_id, db.STATUS_SEGMENTING)
        words = _realign(wav_path, words)
        segments = _apply_blanks(split_into_segments(words))
        db.insert_segments(conn, source_id, segments)

        db.finish_source(conn, source_id, audio_path=str(wav_path))
    except Exception as exc:
        db.fail_source(conn, source_id, str(exc))
        raise
    return source_id
