"""音频文件操作：裁剪、格式统一、录音有效性校验。"""

from __future__ import annotations

import math
import re
import select
import shutil
import subprocess
import sys
import time
from functools import lru_cache
from pathlib import Path

import numpy as np
import soundfile as sf

from . import config
from .analysis.silence import loud_level, quiet_midpoint, voiced_fraction
from .drill.units import is_usable


class AudioError(RuntimeError):
    pass


def probe_duration(path: Path) -> float:
    return float(sf.info(str(path)).duration)


def cut_segment(source: Path, dest: Path, *, start: float, end: float) -> Path:
    """从 source 裁出 [start, end) 并统一为 16k 单声道 wav。"""
    if end <= start:
        raise AudioError(f"无效的裁剪区间：start={start} end={end}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(source),
            "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
            "-ar", str(config.SAMPLE_RATE), "-ac", "1",
            "-c:a", "pcm_s16le", str(dest),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise AudioError(f"ffmpeg 裁剪失败：\n{proc.stderr.strip()}")
    return dest


def _frame_energy_db(samples, sr: int, offset: float):
    """逐帧能量（dB）与各帧起始时刻。"""
    win, hop = int(0.025 * sr), int(0.01 * sr)
    if samples.size < win:
        return np.empty(0), np.empty(0)
    starts = np.arange(0, samples.size - win + 1, hop)
    rms = np.array([np.sqrt(np.mean(samples[i:i + win] ** 2)) for i in starts])
    return offset + starts / sr, 20.0 * np.log10(rms + 1e-12)


def snap_to_silence(path: Path, at: float, *, fallback: float,
                    window: float = None) -> float:
    """把裁剪点挪到附近真正的停顿上。附近找不到停顿就用 fallback。

    转写的词级时间戳常整体偏早几百毫秒。照它裁，上一句的尾巴会被带进来
    ——实测某句转写说句间只隔 0.04 秒，波形里真正的停顿在 0.3 秒之后。
    """
    window = config.SILENCE_WINDOW_SEC if window is None else window
    info = sf.info(str(path))
    low = max(0.0, at - window)
    high = min(info.duration, at + window)
    if high - low < 0.05:
        return fallback
    samples, sr = sf.read(str(path), start=int(low * info.samplerate),
                          stop=int(high * info.samplerate), dtype="float32",
                          always_2d=False)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    times, energy = _frame_energy_db(samples, sr, low)
    found = quiet_midpoint(times, energy)
    return fallback if found is None else found


def unit_bounds(source: Path, words, *, low: float, high: float):
    """一个练习单元在素材里的裁剪区间，尽量落在真正的停顿上。

    命令行与网页共用，免得两边各裁各的。
    """
    start = snap_to_silence(source, words[0].start,
                            fallback=words[0].start - config.UNIT_PAD_SEC)
    end = snap_to_silence(source, words[-1].end,
                          fallback=words[-1].end + config.UNIT_PAD_SEC)
    return max(low, start), min(high, end)


PROBLEM_CRUSHED = "crushed"     # 词级时间戳挤成一团
PROBLEM_SILENT = "silent"       # 时间范围里没有人声
ENERGY_BLOCK_SEC = 60.0         # 整段素材分块读，一小时的也不会一口气读进内存


@lru_cache(maxsize=8)
def _source_energy(path: str, mtime: float) -> tuple[float, np.ndarray, float]:
    """整段素材的逐帧能量，以及它「在说话」时的典型响度。

    一份素材每个进程只算一次；mtime 只用来进缓存键，素材文件换了就重算。
    返回 (帧移秒数, 逐帧能量, 典型响度)。帧长、帧移与 _frame_energy_db 一致。
    """
    info = sf.info(path)
    win, hop = int(0.025 * info.samplerate), int(0.01 * info.samplerate)
    block = hop * int(ENERGY_BLOCK_SEC / 0.01)      # 块长取帧移的整数倍，前后块的帧才接得上
    parts = []
    for begin in range(0, info.frames, block):
        samples, sr = sf.read(path, start=begin, stop=min(info.frames, begin + block + win),
                              dtype="float32", always_2d=False)
        if samples.ndim > 1:
            samples = samples.mean(axis=1)
        parts.append(_frame_energy_db(samples, sr, 0.0)[1][:block // hop])
    energy = np.concatenate(parts) if parts else np.empty(0)
    return hop / info.samplerate, energy, loud_level(energy)


def silent(source: Path | str | None, words) -> bool:
    """这句话的时间范围里确定没有人声吗。

    转写偶尔会凭空编出一句，常落在掌声、长停顿上。强制对齐会把它摊到那段
    静音上，词速看着正常，切出来却什么都听不见。
    素材文件不在就判断不了——判不了就不算没声音，拦错了那句就再也练不到。
    """
    if not source or not words:
        return False
    path = Path(source)
    if not path.exists():
        return False
    step, energy, loud = _source_energy(str(path), path.stat().st_mtime)
    first = max(0, int(words[0].start / step))
    last = max(first, math.ceil(words[-1].end / step))
    return voiced_fraction(energy[first:last], loud_db=loud) < config.MIN_VOICED_FRACTION


def unit_problem(source: Path | str | None, words) -> str | None:
    """这句为什么没法练；能练返回 None。命令行与网页共用，免得两边各判各的。"""
    if not is_usable(words):
        return PROBLEM_CRUSHED
    if silent(source, words):
        return PROBLEM_SILENT
    return None


def validate_attempt(path: Path) -> None:
    """录音提交前的守门：太短或全静音就地拦下，不浪费一次转写。"""
    duration = probe_duration(path)
    if duration < config.MIN_ATTEMPT_SEC:
        raise AudioError(
            f"录音过短（{duration:.2f}s，至少需要 {config.MIN_ATTEMPT_SEC}s）"
        )
    samples, _ = sf.read(str(path), dtype="float32", always_2d=False)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    rms = float(np.sqrt(np.mean(np.square(samples)))) if samples.size else 0.0
    rms_db = 20.0 * math.log10(rms + 1e-10)
    if rms_db < config.MIN_ATTEMPT_RMS_DB:
        raise AudioError(
            f"录音接近静音（{rms_db:.1f} dB）。检查麦克风是否被静音或选错设备。"
        )


# --- 录音（macOS / avfoundation）-------------------------------------------


def list_input_devices() -> tuple[tuple[str, str], ...]:
    """返回 ((编号, 名称), ...)。ffmpeg 把设备列表打在 stderr 且退出码非零，是正常的。"""
    proc = subprocess.run(
        ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
        capture_output=True, text=True,
    )
    devices: list[tuple[str, str]] = []
    in_audio = False
    for line in proc.stderr.splitlines():
        if "AVFoundation audio devices" in line:
            in_audio = True
            continue
        if in_audio:
            match = re.search(r"\[(\d+)\]\s+(.+?)\s*$", line)
            if match:
                devices.append((match.group(1), match.group(2)))
            elif "AVFoundation" not in line:
                break
    return tuple(devices)


def record(
    dest: Path,
    *,
    seconds: float,
    device: str = "0",
    stop_on_enter: bool = True,
) -> Path:
    """从麦克风录一段，直接产出 16k 单声道 wav。

    说完敲回车即可结束，不必干等到时长上限——固定时长会让人不确定
    有没有录进去，进而反复重读。seconds 退化成安全上限。
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "avfoundation", "-i", f":{device}",
        "-t", f"{seconds:.2f}",
        "-ar", str(config.SAMPLE_RATE), "-ac", "1",
        "-c:a", "pcm_s16le", str(dest),
    ]
    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    )

    if stop_on_enter and sys.stdin.isatty():
        deadline = time.monotonic() + seconds + 2.0
        while process.poll() is None and time.monotonic() < deadline:
            ready, _, _ = select.select([sys.stdin], [], [], 0.2)
            if not ready:
                continue
            sys.stdin.readline()
            try:
                process.stdin.write("q")     # ffmpeg 收到 q 会正常收尾并写出文件
                process.stdin.flush()
            except (BrokenPipeError, ValueError):
                process.terminate()
            break

    try:
        _, errors = process.communicate(timeout=seconds + 30)
    except subprocess.TimeoutExpired:
        process.kill()
        _, errors = process.communicate()

    if not dest.exists() or probe_duration(dest) <= 0:
        raise AudioError(
            f"录音失败：\n{(errors or '').strip()}\n"
            f"（第一次使用需要在「系统设置 → 隐私与安全性 → 麦克风」里允许终端）"
        )
    return dest


def convert_upload(data: bytes, dest: Path) -> Path:
    """浏览器录的是 webm/opus 或 mp4，统一转成 16k 单声道 wav。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    raw = dest.with_suffix(".upload")
    raw.write_bytes(data)
    try:
        proc = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw),
             "-ar", str(config.SAMPLE_RATE), "-ac", "1",
             "-c:a", "pcm_s16le", str(dest)],
            capture_output=True, text=True, timeout=120,
        )
    finally:
        raw.unlink(missing_ok=True)
    if proc.returncode != 0 or not dest.exists():
        raise AudioError(f"录音转码失败：\n{proc.stderr.strip()}")
    return dest


# --- 播放 -------------------------------------------------------------------

PLAYERS = (("afplay",), ("ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"))


def _player() -> tuple[str, ...] | None:
    for command in PLAYERS:
        if shutil.which(command[0]):
            return command
    return None


def play(path: Path, *, times: int = 1, gap: float = 0.6) -> int:
    """放 N 遍，返回实际放了几遍。中途 Ctrl+C 就停。"""
    command = _player()
    if command is None:
        raise AudioError(
            "找不到可用的播放器（试过 afplay 和 ffplay）。"
            f"可以手动打开：{path}"
        )
    duration = probe_duration(path)
    played = 0
    for _ in range(max(1, times)):
        proc = subprocess.run([*command, str(path)], capture_output=True, text=True,
                              timeout=duration + 30)
        if proc.returncode != 0:
            raise AudioError(f"播放失败：\n{proc.stderr.strip()}")
        played += 1
        if played < times and gap > 0:
            time.sleep(gap)
    return played


CUE_FREQ_HZ = 880.0
CUE_SECONDS = 0.14


def cue_path() -> Path:
    return config.data_dir() / "cue.wav"


def ensure_cue() -> Path:
    """提示音只生成一次，之后复用。"""
    path = cue_path()
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = int(CUE_SECONDS * config.SAMPLE_RATE)
    t = np.arange(samples) / config.SAMPLE_RATE
    tone = 0.35 * np.sin(2 * np.pi * CUE_FREQ_HZ * t)
    fade = max(1, samples // 8)          # 去掉首尾爆音
    tone[:fade] *= np.linspace(0.0, 1.0, fade)
    tone[-fade:] *= np.linspace(1.0, 0.0, fade)
    sf.write(path, tone.astype(np.float32), config.SAMPLE_RATE)
    return path


def beep() -> None:
    """开录提示音。戴着耳机时看不见终端，必须用声音提示。"""
    try:
        play(ensure_cue(), times=1, gap=0.0)
    except Exception:
        pass       # 提示音失败不该影响录音
