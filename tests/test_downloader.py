import subprocess

import pytest

from shadow.ingest import downloader
from shadow.ingest.downloader import DownloadError


class FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_validate_url_accepts_https():
    assert downloader.validate_url("  https://example.com/v?id=1 ") == (
        "https://example.com/v?id=1"
    )


@pytest.mark.parametrize("bad", ["file:///etc/passwd", "javascript:alert(1)",
                                 "ftp://x/y", "not a url", ""])
def test_validate_url_rejects_non_http(bad):
    with pytest.raises(DownloadError):
        downloader.validate_url(bad)


def test_probe_returns_title_and_duration(monkeypatch):
    monkeypatch.setattr(
        downloader.subprocess, "run",
        lambda *a, **k: FakeProc(stdout="Some Talk\n742.5\n"),
    )
    assert downloader.probe("https://x/y") == ("Some Talk", 742.5)


def test_probe_surfaces_raw_stderr(monkeypatch):
    monkeypatch.setattr(
        downloader.subprocess, "run",
        lambda *a, **k: FakeProc(returncode=1, stderr="ERROR: Video unavailable"),
    )
    with pytest.raises(DownloadError, match="Video unavailable"):
        downloader.probe("https://x/y")


def test_probe_rejects_unparseable_duration(monkeypatch):
    monkeypatch.setattr(
        downloader.subprocess, "run",
        lambda *a, **k: FakeProc(stdout="Live Stream\nNA\n"),
    )
    with pytest.raises(DownloadError, match="时长"):
        downloader.probe("https://x/y")


def test_probe_reports_timeout_clearly(monkeypatch):
    def timeout_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 0))

    monkeypatch.setattr(downloader.subprocess, "run", timeout_run)
    with pytest.raises(DownloadError, match="超时"):
        downloader.probe("https://x/y")


def test_download_audio_invokes_ytdlp_then_ffmpeg(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "yt-dlp":
            raw = tmp_path / "raw.m4a"
            raw.write_bytes(b"x")
            return FakeProc(stdout=f"{raw}\n")
        return FakeProc()

    monkeypatch.setattr(downloader.subprocess, "run", fake_run)
    dest = tmp_path / "out.wav"
    downloader.download_audio("https://x/y", dest, workdir=tmp_path)

    assert calls[0][0] == "yt-dlp"
    assert calls[1][0] == "ffmpeg"
    assert str(dest) in calls[1]
