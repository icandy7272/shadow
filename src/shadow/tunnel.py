"""经云服务器把本机的 shadow 挂到一个好记的 HTTPS 网址上。

浏览器 → 云服务器 nginx（HTTPS + 访问密码）→ SSH 反向隧道 → 本机的 shadow serve。
活全在本机干，服务器只转发。隧道跟着 shadow serve 起、跟着它停，不在后台常驻。
配置是个人的（哪台服务器、什么域名），放在数据目录里，不进仓库。
"""

from __future__ import annotations

import subprocess
import threading
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from . import config

CONFIG_NAME = "tunnel.toml"
RETRY_SEC = (2.0, 5.0, 15.0, 30.0)   # 断了之后逐步拉长重连间隔
STABLE_SEC = 60.0                    # 连着超过这么久才算恢复，间隔从头算
CONNECT_GRACE_SEC = 3.0              # 起来这么久还没退出，就当已经连上
KEEPALIVE_SEC = 15
FORWARD_FAILED = "remote port forwarding failed"


class TunnelError(RuntimeError):
    """隧道配置写得不对。消息直接给人看。"""


@dataclass(frozen=True, slots=True)
class TunnelConfig:
    ssh_host: str       # ~/.ssh/config 里的主机名，用密钥登录
    remote_port: int    # 服务器上 nginx 转发到的端口
    url: str            # 打印给人看的网址


def config_path() -> Path:
    return config.data_dir() / CONFIG_NAME


def load(path: Path | None = None) -> TunnelConfig | None:
    """没有配置文件就是不开隧道。写错了抛 TunnelError，消息里带上文件路径。"""
    path = path or config_path()
    if not path.exists():
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        settings = TunnelConfig(ssh_host=str(data["ssh_host"]).strip(),
                                remote_port=int(data["remote_port"]),
                                url=str(data["url"]).strip())
    except KeyError as exc:
        raise TunnelError(f"{path} 里缺 {exc.args[0]}") from exc
    except (tomllib.TOMLDecodeError, TypeError, ValueError) as exc:
        raise TunnelError(f"{path} 写得不对：{exc}") from exc
    problem = _problem(settings)
    if problem:
        raise TunnelError(f"{path} 写得不对：{problem}")
    return settings


def _problem(settings: TunnelConfig) -> str | None:
    if not settings.ssh_host:
        return "ssh_host 是空的"
    if not 1024 <= settings.remote_port <= 65535:
        return "remote_port 要在 1024 到 65535 之间"
    if not settings.url.startswith("https://"):
        return "url 要以 https:// 开头——不是 HTTPS，手机浏览器不给麦克风"
    return None


def ssh_command(settings: TunnelConfig, local_port: int) -> list[str]:
    """转发端口只绑服务器的回环地址：外面只能经 nginx（带密码）进来。"""
    return [
        "ssh", "-N",
        "-o", "BatchMode=yes",              # 没配好密钥就直接失败，别卡在输密码上
        "-o", "ExitOnForwardFailure=yes",   # 端口没占上就退出好重连，而不是连着却不转发
        "-o", f"ServerAliveInterval={KEEPALIVE_SEC}",
        "-o", "ServerAliveCountMax=3",
        "-R", f"127.0.0.1:{settings.remote_port}:127.0.0.1:{local_port}",
        settings.ssh_host,
    ]


def release_command(settings: TunnelConfig) -> list[str]:
    """上一条隧道断得不干净（比如网络切换）时，服务器上那个 sshd 会话会一直占着端口。

    只清掉占着这个端口的 sshd，别的进程一概不碰。
    """
    port = settings.remote_port
    script = (f"pid=$(ss -tlnpH 'sport = :{port}' | grep -o 'sshd\",pid=[0-9]*' "
              "| head -n 1 | cut -d= -f2); [ -z \"$pid\" ] || kill \"$pid\"")
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            settings.ssh_host, script]


def retry_delay(failures: int, delays: Sequence[float] = RETRY_SEC) -> float:
    """连续失败第 failures 次（从 0 数）之后等多久再连。"""
    return delays[min(max(failures, 0), len(delays) - 1)]


def _reason(stderr: str | None) -> str:
    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]
    return lines[-1] if lines else "ssh 退出了"


def _say(note: str) -> None:
    print(note, flush=True)     # 从后台线程打印，输出重定向到文件时也要马上看得到


class Tunnel:
    """后台线程守着 ssh：断了就重连，stop() 时一起收掉。"""

    def __init__(self, settings: TunnelConfig, local_port: int, *,
                 spawn: Callable[..., subprocess.Popen] = subprocess.Popen,
                 run: Callable[..., object] = subprocess.run,
                 report: Callable[[str], None] = _say,
                 retry_delays: Sequence[float] = RETRY_SEC,
                 grace: float = CONNECT_GRACE_SEC) -> None:
        self._settings = settings
        self._local_port = local_port
        self._spawn = spawn
        self._run = run
        self._report = report
        self._delays = tuple(retry_delays)
        self._grace = grace
        self._stopping = threading.Event()
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._watch, name="shadow-tunnel",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        with self._lock:
            proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _watch(self) -> None:
        failures = 0
        last_reason = None
        while not self._stopping.is_set():
            began = time.monotonic()
            proc = self._launch()
            if proc is None:
                return
            try:
                proc.wait(timeout=self._grace)
            except subprocess.TimeoutExpired:
                self._report(f"隧道已连上：{self._settings.url}")
                last_reason = None
            _, stderr = proc.communicate()
            if self._stopping.is_set():
                return
            if time.monotonic() - began > STABLE_SEC:
                failures = 0
            if FORWARD_FAILED in (stderr or ""):
                self._release()
            reason = _reason(stderr)
            if reason != last_reason:           # 断网时同一个原因别每隔几秒刷一遍
                self._report(f"隧道断了（{reason}），会自动重连。")
                last_reason = reason
            delay = retry_delay(failures, self._delays)
            failures += 1
            self._stopping.wait(delay)

    def _launch(self) -> subprocess.Popen | None:
        with self._lock:
            if self._stopping.is_set():
                return None
            # 单独一个进程组：终端里按 Ctrl+C 不会先把 ssh 打断，由 stop() 来收
            self._proc = self._spawn(ssh_command(self._settings, self._local_port),
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.PIPE, text=True,
                                     start_new_session=True)
            return self._proc

    def _release(self) -> None:
        try:
            self._run(release_command(self._settings), stdin=subprocess.DEVNULL,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                      timeout=20, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            self._report(f"清理服务器上残留的隧道没成功：{exc}")
