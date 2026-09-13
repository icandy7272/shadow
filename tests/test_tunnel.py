"""隧道：读配置、拼 ssh 命令、断了重连、停得干净。不连真服务器，也不真的等。"""

import subprocess
import threading
import time

import pytest

from shadow import tunnel

SETTINGS = tunnel.TunnelConfig(ssh_host="cloud", remote_port=18000,
                               url="https://shadow.example.com")
GOOD = 'ssh_host = "cloud"\nremote_port = 18000\nurl = "https://shadow.example.com"\n'


@pytest.fixture(autouse=True)
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path / "data"))


def _write(text):
    path = tunnel.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_no_config_means_no_tunnel():
    assert tunnel.load() is None


def test_config_is_read_from_the_data_dir():
    _write(GOOD)
    assert tunnel.load() == SETTINGS


@pytest.mark.parametrize("text", [
    'ssh_host = "cloud"\nremote_port = 18000\n',                                    # 缺 url
    'ssh_host = "cloud"\nremote_port = "abc"\nurl = "https://shadow.example.com"\n',
    'ssh_host = "cloud"\nremote_port = 80\nurl = "https://shadow.example.com"\n',    # 特权端口
    'ssh_host = "cloud"\nremote_port = 18000\nurl = "http://shadow.example.com"\n',  # 不是 HTTPS 就没有麦克风
    'ssh_host = ""\nremote_port = 18000\nurl = "https://shadow.example.com"\n',
    'ssh_host = \n',                                                                # 连 TOML 都不是
])
def test_a_broken_config_names_the_file(text):
    _write(text)
    with pytest.raises(tunnel.TunnelError, match="tunnel.toml"):
        tunnel.load()


def test_the_tunnel_only_listens_on_the_servers_loopback():
    command = tunnel.ssh_command(SETTINGS, local_port=8000)
    assert command[0] == "ssh" and command[-1] == "cloud"
    assert "127.0.0.1:18000:127.0.0.1:8000" in command
    assert "ExitOnForwardFailure=yes" in command
    assert "BatchMode=yes" in command


def test_releasing_a_stale_port_only_touches_sshd():
    command = tunnel.release_command(SETTINGS)
    assert command[0] == "ssh" and "cloud" in command
    assert "sport = :18000" in command[-1]
    assert 'sshd",pid=' in command[-1]


def test_retry_delay_grows_and_levels_off():
    delays = [tunnel.retry_delay(n) for n in range(10)]
    assert delays == sorted(delays)
    assert delays[0] < delays[-1] == tunnel.RETRY_SEC[-1]


class FakeProc:
    """假的 ssh：给了 error 就带着报错马上退出，否则一直连着直到被 terminate。"""

    def __init__(self, error=None):
        self.error = error
        self.returncode = 255 if error is not None else None
        self.gone = threading.Event()
        if error is not None:
            self.gone.set()
        self.terminated = False

    def wait(self, timeout=None):
        if not self.gone.wait(timeout):
            raise subprocess.TimeoutExpired("ssh", timeout)
        return self.returncode

    def communicate(self):
        self.gone.wait()
        return "", self.error or ""

    def poll(self):
        return self.returncode if self.gone.is_set() else None

    def terminate(self):
        self.terminated = True
        self.returncode = -15
        self.gone.set()

    kill = terminate


def _until(check, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.01)
    return False


def _tunnel(errors, *, released, notes):
    """按顺序起假进程：errors 里每一项对应一次 ssh，None 表示这次连上了。"""
    procs = []

    def spawn(command, **kwargs):
        procs.append(FakeProc(errors[len(procs)] if len(procs) < len(errors) else None))
        return procs[-1]

    link = tunnel.Tunnel(SETTINGS, 8000, spawn=spawn,
                         run=lambda command, **kwargs: released.append(command),
                         report=notes.append, retry_delays=(0,), grace=0.05)
    return link, procs


def test_a_stale_port_is_freed_before_reconnecting():
    released, notes = [], []
    link, procs = _tunnel(
        ["Warning: remote port forwarding failed for listen port 18000", None],
        released=released, notes=notes)

    link.start()
    try:
        assert _until(lambda: len(procs) == 2 and any("已连上" in n for n in notes))
    finally:
        link.stop()

    assert released == [tunnel.release_command(SETTINGS)]
    assert procs[1].terminated
    assert any("https://shadow.example.com" in n for n in notes)


def test_other_failures_are_reported_without_touching_the_server():
    released, notes = [], []
    link, procs = _tunnel(["root@1.2.3.4: Permission denied (publickey).", None],
                          released=released, notes=notes)

    link.start()
    try:
        assert _until(lambda: len(procs) == 2)
    finally:
        link.stop()

    assert released == []
    assert any("Permission denied" in n for n in notes)


def test_stop_ends_ssh_and_does_not_reconnect():
    released, notes = [], []
    link, procs = _tunnel([], released=released, notes=notes)

    link.start()
    assert _until(lambda: procs)
    link.stop()
    time.sleep(0.1)

    assert len(procs) == 1
    assert procs[0].terminated
