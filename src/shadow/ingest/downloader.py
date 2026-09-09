"""yt-dlp / ffmpeg 封装。失败时原样保留外部工具的 stderr。"""

from __future__ import annotations

import subprocess
from pathlib import Path
from urllib.parse import urlparse

from .. import config

ALLOWED_SCHEMES = ("http", "https")


class DownloadError(RuntimeError):
    """下载或探测素材失败。消息中应包含外部工具的原始输出。"""


def _run(cmd: list[str], *, timeout: float, what: str) -> subprocess.CompletedProcess:
    """跑外部命令，把超时转成可读错误。

    不设超时的话，网络卡住会让导入永久挂起，状态停在 downloading 且没有恢复路径。
    """
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise DownloadError(
            f"{what}超时（{timeout:.0f} 秒无响应）。"
            f"网络卡住或链接无法访问，换个链接或稍后重试。"
        ) from exc


def validate_url(url: str) -> str:
    cleaned = (url or "").strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in ALLOWED_SCHEMES or not parsed.netloc:
        raise DownloadError(f"只接受 http/https 链接，收到：{url!r}")
    return cleaned


def probe(url: str) -> tuple[str, float]:
    """返回 (标题, 时长秒)。不下载媒体。"""
    proc = _run(
        [
            "yt-dlp", "--no-playlist", "--skip-download",
            "--print", "%(title)s", "--print", "%(duration)s", url,
        ],
        timeout=config.PROBE_TIMEOUT_SEC,
        what="yt-dlp 查询",
    )
    if proc.returncode != 0:
        raise DownloadError(f"yt-dlp 查询失败：\n{proc.stderr.strip()}")

    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if len(lines) < 2:
        raise DownloadError(f"yt-dlp 未返回完整元信息：\n{proc.stdout.strip()}")

    title = lines[0].strip()
    try:
        duration = float(lines[1].strip())
    except ValueError as exc:
        raise DownloadError(
            f"无法解析素材时长（直播或无时长信息？）：{lines[1]!r}"
        ) from exc
    return title, duration


def download_audio(url: str, dest_wav: Path, *, workdir: Path) -> Path:
    """下载最佳音轨并转成 16k 单声道 wav。"""
    dest_wav.parent.mkdir(parents=True, exist_ok=True)
    workdir.mkdir(parents=True, exist_ok=True)

    fetch = _run(
        [
            "yt-dlp", "--no-playlist", "-f", "bestaudio",
            "-o", str(workdir / "raw.%(ext)s"),
            "--print", "after_move:filepath", url,
        ],
        timeout=config.DOWNLOAD_TIMEOUT_SEC,
        what="yt-dlp 下载",
    )
    if fetch.returncode != 0:
        raise DownloadError(f"yt-dlp 下载失败：\n{fetch.stderr.strip()}")

    raw_lines = [line for line in fetch.stdout.splitlines() if line.strip()]
    if not raw_lines:
        raise DownloadError("yt-dlp 未报告下载后的文件路径")
    raw_path = Path(raw_lines[-1].strip())

    convert = _run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(raw_path),
            "-ar", str(config.SAMPLE_RATE), "-ac", "1",
            "-c:a", "pcm_s16le", str(dest_wav),
        ],
        timeout=config.FFMPEG_TIMEOUT_SEC,
        what="ffmpeg 转码",
    )
    if convert.returncode != 0:
        raise DownloadError(f"ffmpeg 转码失败：\n{convert.stderr.strip()}")
    return dest_wav
