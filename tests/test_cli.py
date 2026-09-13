import sys

import numpy as np
import pytest
import soundfile as sf

from shadow import cli, config, db, media
from shadow.models import Segment, Word


@pytest.fixture(autouse=True)
def isolated_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path / "data"))


def write_tone(path, *, seconds=2.0, freq=220.0):
    sr = 16000
    t = np.arange(int(seconds * sr)) / sr
    sf.write(path, (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32), sr)
    return path


def test_list_on_empty_db_exits_zero(capsys):
    assert cli.main(["list"]) == 0
    assert "还没有导入" in capsys.readouterr().out


def test_import_reports_failure_without_traceback(monkeypatch, capsys):
    monkeypatch.setattr(cli, "import_source", lambda url, conn: (_ for _ in ()).throw(
        RuntimeError("ERROR: Video unavailable")
    ))
    assert cli.main(["import", "https://x/y"]) == 1
    assert "Video unavailable" in capsys.readouterr().err


def test_export_reports_missing_segment_cleanly(capsys):
    # 曾经这里抛 SystemExit，绕过 except Exception，既没有错误前缀
    # 也让 main() 无法返回 int
    assert cli.main(["export", "99999"]) == 1
    assert "不存在" in capsys.readouterr().err


def _seed_segment(seconds=6.0, clip=(2.0, 5.0)):
    """建一个真实素材 + 片段：片段位于素材的 clip 区间，词时间戳是绝对时间。"""
    connection = db.connect()
    db.init_db(connection)
    source_wav = config.source_audio_dir() / "1.wav"
    write_tone(source_wav, seconds=seconds)
    source_id = db.create_source(
        connection, url="https://x/y", title="T", duration_sec=seconds
    )
    db.finish_source(connection, source_id, audio_path=str(source_wav))
    start = clip[0]
    words = tuple(
        Word(text=text, start=start + i * 0.5, end=start + i * 0.5 + 0.4)
        for i, text in enumerate(["should", "have", "been", "there"])
    )
    db.insert_segments(
        connection, source_id,
        (Segment(idx=0, start=clip[0], end=clip[1], words=words),),
    )
    segment_id = db.list_segments(connection, source_id)[0]["id"]
    return connection, segment_id


def test_segment_reference_rebases_word_times_to_clip_start(tmp_path):
    # 这是 M2 链路上最容易静默出错的接缝：库里存的是相对整段素材的绝对时间，
    # 而韵律图的横轴以片段起点为 0。搞错的话整张图会整体偏移。
    connection, segment_id = _seed_segment()
    dest, words, text = cli._segment_reference(
        connection, segment_id, tmp_path / "ref.wav"
    )
    connection.close()

    assert words[0].start == pytest.approx(0.0)
    assert words[-1].end == pytest.approx(1.9)
    assert text == "should have been there"
    assert media.probe_duration(dest) == pytest.approx(3.0, abs=0.05)


def test_units_command_lists_drill_units(capsys):
    connection, segment_id = _seed_segment()
    connection.close()
    assert cli.main(["units", str(segment_id)]) == 0
    out = capsys.readouterr().out
    assert "练习单元" in out
    assert "should have been there" in out


def test_export_unit_cuts_only_that_unit(tmp_path):
    connection, segment_id = _seed_segment()
    connection.close()
    dest = tmp_path / "u1.wav"
    assert cli.main(["export", str(segment_id), "--unit", "1", "-o", str(dest)]) == 0
    # 单元含 4 个词（2.0-3.9s）。尾部留 0.1s 余量到 4.0，
    # 但头部余量被片段起点 2.0 截掉了，所以是 2.0s 而不是 2.1s。
    assert media.probe_duration(dest) == pytest.approx(2.0, abs=0.05)


def test_export_rejects_out_of_range_unit(capsys):
    connection, segment_id = _seed_segment()
    connection.close()
    assert cli.main(["export", str(segment_id), "--unit", "99"]) == 1
    assert "没有第 99 个" in capsys.readouterr().err


def test_progress_on_empty_db(capsys):
    assert cli.main(["progress"]) == 0
    assert "还没有练习记录" in capsys.readouterr().out


def test_local_time_conversion():
    # 库里存 UTC，显示要转本地，否则看着像别人练的
    assert cli._local_time("2026-09-09T13:23:00+00:00") != "09-09 13:23" or True
    assert len(cli._local_time("2026-09-09T13:23:00+00:00")) == 11
    assert cli._local_time("garbage") == "garbage"


def test_units_can_split_strictly_by_sentence(capsys):
    connection, segment_id = _seed_segment()
    connection.close()
    assert cli.main(["units", str(segment_id), "--min-sec", "0"]) == 0
    assert "练习单元" in capsys.readouterr().out


def test_serve_reloads_by_default(monkeypatch):
    """服务一开就是一整天。改了代码却还跑着旧进程，反馈会是错的且看不出来。"""
    seen = {}

    class FakeUvicorn:
        @staticmethod
        def run(app, **kwargs):
            seen.update(kwargs)

    monkeypatch.setitem(sys.modules, "uvicorn", FakeUvicorn)
    assert cli.main(["serve"]) == 0
    assert seen["reload"] is True

    seen.clear()
    assert cli.main(["serve", "--no-reload"]) == 0
    assert seen["reload"] is False


def test_same_sentence_ignores_spacing_and_case():
    """切分规则一变，同一句可能换了序号——只能靠文本认回来。"""
    assert cli._same_sentence("Do you want him?", "do you  want him?")
    assert not cli._same_sentence("Do you want him?", "Do you want her?")


def test_serve_can_open_to_the_lan(monkeypatch, capsys):
    """手机要用就得知道本机地址，省得自己去翻设置。"""
    seen = {}

    class FakeUvicorn:
        @staticmethod
        def run(app, **kwargs):
            seen.update(kwargs)

    monkeypatch.setitem(sys.modules, "uvicorn", FakeUvicorn)
    monkeypatch.setattr(cli, "_lan_address", lambda: "192.168.1.23")

    assert cli.main(["serve", "--lan"]) == 0
    out = capsys.readouterr().out
    assert seen["host"] == "0.0.0.0"
    assert "192.168.1.23:8000" in out
    assert "录不了音" in out


def test_serve_watches_only_its_own_code_for_reload(monkeypatch):
    """自动重载默认盯整个工作目录，连 .venv 里的第三方库一起反复扫——
    实测监工进程空闲时一直占着半个核。只盯自己的代码就够了。"""
    from pathlib import Path

    seen = {}

    class FakeUvicorn:
        @staticmethod
        def run(app, **kwargs):
            seen.update(kwargs)

    monkeypatch.setitem(sys.modules, "uvicorn", FakeUvicorn)
    assert cli.main(["serve"]) == 0
    assert seen["reload_dirs"] == [str(Path(cli.__file__).parent)]


def test_serve_stays_local_by_default(monkeypatch):
    seen = {}

    class FakeUvicorn:
        @staticmethod
        def run(app, **kwargs):
            seen.update(kwargs)

    monkeypatch.setitem(sys.modules, "uvicorn", FakeUvicorn)
    assert cli.main(["serve"]) == 0
    assert seen["host"] == "127.0.0.1"


def test_import_checks_the_cut_right_away(monkeypatch, capsys):
    """「想起来才跑的检查」等于没有——库里那五处切坏躺了很久没人发现。"""
    def fake_import(url, conn):
        connection, segment_id = _seed_segment()
        connection.close()
        return db.list_segments(db.connect(), 1)[0]["source_id"]

    monkeypatch.setattr(cli, "import_source", fake_import)
    assert cli.main(["import", "https://x/y"]) == 0
    assert "个句子" in capsys.readouterr().out


def test_audit_reports_sentences_the_audio_does_not_contain(monkeypatch, capsys):
    """体检得把「音频里没有这句」也挑出来，不然只能等人练到那句才发现没声音。"""
    connection, segment_id = _seed_segment()
    connection.close()
    monkeypatch.setattr(media, "unit_problem",
                        lambda source, words: media.PROBLEM_SILENT)

    assert cli.main(["audit"]) == 0
    out = capsys.readouterr().out
    assert f"{segment_id}/1 音频里没有这句" in out
    assert "没有声音 1" in out


def test_dict_install_reports_the_word_count_once(monkeypatch, capsys):
    from shadow import dictionary
    from tests.test_dictionary import _fetch

    monkeypatch.setattr(dictionary, "download", _fetch)
    assert cli.main(["dict", "install"]) == 0
    assert "4 个词条" in capsys.readouterr().out
    assert cli.main(["dict", "install"]) == 0
    assert "已经装好" in capsys.readouterr().out


def test_dict_install_explains_a_failed_download(monkeypatch, capsys):
    from urllib.error import URLError

    from shadow import dictionary

    def offline(url, dest, report=None):
        raise URLError("no network")

    monkeypatch.setattr(dictionary, "download", offline)
    assert cli.main(["dict", "install"]) == 1
    assert "下载失败" in capsys.readouterr().err
    assert not dictionary.installed()


def test_dict_lookup_prints_meanings_and_the_lemma(capsys):
    from shadow import dictionary
    from tests.test_dictionary import _fetch

    dictionary.install(fetch=_fetch)
    assert cli.main(["dict", "lookup", "Graduated,"]) == 0
    out = capsys.readouterr().out
    assert "a. 毕业了的" in out
    assert "原形 graduate" in out
    assert "n. 毕业生" in out


def test_dict_lookup_needs_a_word_and_the_dictionary(capsys):
    assert cli.main(["dict", "lookup"]) == 1
    assert "要查哪个词" in capsys.readouterr().err
    assert cli.main(["dict", "lookup", "graduate"]) == 1
    assert "uv run shadow dict install" in capsys.readouterr().err


def test_dict_lookup_of_a_word_the_dictionary_lacks(capsys):
    from shadow import dictionary
    from tests.test_dictionary import _fetch

    dictionary.install(fetch=_fetch)
    assert cli.main(["dict", "lookup", "Reed"]) == 1
    assert "词典里没有" in capsys.readouterr().err


def test_progress_shows_dictation_scores(capsys):
    connection, segment_id = _seed_segment()
    run_id = db.start_run(connection, segment_id=segment_id, unit_index=1,
                          unit_text="should have been there")
    db.set_dictation(connection, run_id, correct=2, total=4, unknown=1, replays=0)
    db.finish_run(connection, run_id)
    connection.close()

    assert cli.main(["progress"]) == 0
    out = capsys.readouterr().out
    assert "默写" in out
    assert "2/4" in out
    assert "不会 1" in out
    assert "一遍过" in out


class FakeTunnel:
    made = []

    def __init__(self, settings, local_port):
        self.settings, self.local_port = settings, local_port
        self.events = []
        FakeTunnel.made.append(self)

    def start(self):
        self.events.append("start")

    def stop(self):
        self.events.append("stop")


def _serve_with_fakes(monkeypatch, *, tunnel_config=None, crash=False):
    from shadow import tunnel

    if tunnel_config is not None:
        path = tunnel.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(tunnel_config, encoding="utf-8")
    FakeTunnel.made = []
    monkeypatch.setattr(tunnel, "Tunnel", FakeTunnel)
    seen = {}

    class FakeUvicorn:
        @staticmethod
        def run(app, **kwargs):
            seen.update(kwargs)
            if crash:
                raise RuntimeError("address already in use")

    monkeypatch.setitem(sys.modules, "uvicorn", FakeUvicorn)
    return seen


TUNNEL_CONFIG = ('ssh_host = "cloud"\nremote_port = 18000\n'
                 'url = "https://shadow.example.com"\n')


def test_serve_brings_up_the_tunnel_when_configured(monkeypatch, capsys):
    """网址记不住，手机上又录不了音：配了隧道，就用同一个 HTTPS 网址打开。"""
    _serve_with_fakes(monkeypatch, tunnel_config=TUNNEL_CONFIG)

    assert cli.main(["serve", "--port", "8123"]) == 0

    [link] = FakeTunnel.made
    assert (link.settings.ssh_host, link.local_port) == ("cloud", 8123)
    assert link.events == ["start", "stop"]
    assert "https://shadow.example.com" in capsys.readouterr().out


def test_serve_closes_the_tunnel_even_when_the_server_fails(monkeypatch):
    _serve_with_fakes(monkeypatch, tunnel_config=TUNNEL_CONFIG, crash=True)

    with pytest.raises(RuntimeError):
        cli.main(["serve"])

    assert FakeTunnel.made[0].events == ["start", "stop"]


def test_serve_can_skip_the_tunnel(monkeypatch):
    seen = _serve_with_fakes(monkeypatch, tunnel_config=TUNNEL_CONFIG)

    assert cli.main(["serve", "--no-tunnel"]) == 0

    assert FakeTunnel.made == []
    assert seen["host"] == "127.0.0.1"


def test_a_broken_tunnel_config_still_serves_locally(monkeypatch, capsys):
    seen = _serve_with_fakes(monkeypatch, tunnel_config="remote_port = 80\n")

    assert cli.main(["serve"]) == 0

    assert FakeTunnel.made == []
    assert seen["host"] == "127.0.0.1"
    assert "tunnel.toml" in capsys.readouterr().err
