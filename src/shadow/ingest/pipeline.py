"""导入流程编排：URL -> 音频 -> 转写 -> 切片 -> 入库。

时长上限在下载之前检查，避免用户等十分钟才发现失败。
任何一步失败都把原始错误写进 sources.error 并原样抛出。
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from .. import config, db
from .downloader import download_audio, probe, validate_url
from .segmenter import split_into_segments
from .transcriber import transcribe_words


class ImportError_(RuntimeError):
    """导入前置校验失败（命名避开内置 ImportError）。"""


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


def begin_import(url: str, *, conn: sqlite3.Connection) -> int:
    """建一条导入记录，马上返回。标题和时长要联网查，先用链接占位。

    网页导入靠它让卡片立刻出现；链接格式不对在这里就拦下，什么都不建。
    """
    clean_url = validate_url(url)
    return db.create_source(conn, url=clean_url, title=clean_url, duration_sec=0.0)


def run_import(source_id: int, *, conn: sqlite3.Connection) -> None:
    """把一条导入记录跑完。任何一步出错都记下原始错误并原样抛出。"""
    url = db.get_source(conn, source_id)["url"]
    try:
        db.set_source_status(conn, source_id, db.STATUS_PROBING)
        title, duration = probe(url)
        limit_sec = config.MAX_SOURCE_MINUTES * 60
        if duration > limit_sec:
            raise ImportError_(
                f"素材时长 {duration / 60:.1f} 分钟，超过上限 "
                f"{config.MAX_SOURCE_MINUTES:.0f} 分钟。请改用更短的素材或先自行裁剪。"
            )
        db.update_source_meta(conn, source_id, title=title, duration_sec=duration)

        db.set_source_status(conn, source_id, db.STATUS_DOWNLOADING)
        wav_path = config.source_audio_dir() / f"{source_id}.wav"
        with tempfile.TemporaryDirectory() as workdir:
            download_audio(url, wav_path, workdir=Path(workdir))

        db.set_source_status(conn, source_id, db.STATUS_TRANSCRIBING)
        words = transcribe_words(wav_path)

        db.set_source_status(conn, source_id, db.STATUS_SEGMENTING)
        words = _realign(wav_path, words)
        db.insert_segments(conn, source_id, split_into_segments(words))

        db.finish_source(conn, source_id, audio_path=str(wav_path))
    except Exception as exc:
        db.fail_source(conn, source_id, str(exc))
        raise


def import_source(url: str, *, conn: sqlite3.Connection) -> int:
    """命令行用：建记录并一口气跑完。"""
    source_id = begin_import(url, conn=conn)
    run_import(source_id, conn=conn)
    return source_id
