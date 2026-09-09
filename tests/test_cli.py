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


def test_compare_writes_png(monkeypatch, tmp_path, capsys):
    reference = write_tone(tmp_path / "ref.wav")
    user = write_tone(tmp_path / "usr.wav")
    out = tmp_path / "out.png"

    def fake_transcribe(path):
        return tuple(
            Word(text=text, start=start, end=start + 0.4)
            for text, start in zip(
                ["should", "have", "been", "there"], [0.0, 0.5, 1.0, 1.5]
            )
        )

    monkeypatch.setattr(cli, "transcribe_words", fake_transcribe)
    exit_code = cli.main(
        ["compare", "--ref", str(reference), "--user", str(user), "-o", str(out)]
    )
    assert exit_code == 0
    assert out.exists()
    assert "可懂度" in capsys.readouterr().out


def test_export_reports_missing_segment_cleanly(capsys):
    # 曾经这里抛 SystemExit，绕过 except Exception，既没有错误前缀
    # 也让 main() 无法返回 int
    assert cli.main(["export", "99999"]) == 1
    assert "不存在" in capsys.readouterr().err


def test_compare_rejects_silent_recording(monkeypatch, tmp_path, capsys):
    reference = write_tone(tmp_path / "ref.wav")
    sr = 16000
    sf.write(tmp_path / "silent.wav", np.zeros(sr * 2, dtype=np.float32), sr)
    exit_code = cli.main(
        ["compare", "--ref", str(reference), "--user", str(tmp_path / "silent.wav")]
    )
    assert exit_code == 1
    assert "静音" in capsys.readouterr().err


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


def test_compare_with_segment_renders_chart(monkeypatch, tmp_path, capsys):
    connection, segment_id = _seed_segment()
    connection.close()
    user = write_tone(tmp_path / "me.wav", seconds=3.0)
    monkeypatch.setattr(cli, "transcribe_words", lambda path: tuple(
        Word(text=text, start=i * 0.5, end=i * 0.5 + 0.4)
        for i, text in enumerate(["should", "have", "been", "there"])
    ))
    out = tmp_path / "seg.png"
    exit_code = cli.main(
        ["compare", "--segment", str(segment_id), "--user", str(user), "-o", str(out)]
    )
    assert exit_code == 0
    assert out.exists()
    assert "可懂度 100%" in capsys.readouterr().out


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


def test_compare_accepts_multiple_takes(monkeypatch, tmp_path, capsys):
    reference = write_tone(tmp_path / "ref.wav")
    takes = [write_tone(tmp_path / f"t{i}.wav") for i in range(3)]

    def fake_transcribe(path):
        return tuple(
            Word(text=text, start=start, end=start + 0.4)
            for text, start in zip(
                ["should", "have", "been", "there"], [0.0, 0.5, 1.0, 1.5]
            )
        )

    monkeypatch.setattr(cli, "transcribe_words", fake_transcribe)
    argv = ["compare", "--ref", str(reference)]
    for take in takes:
        argv += ["--user", str(take)]
    argv += ["-o", str(tmp_path / "multi.png")]

    assert cli.main(argv) == 0
    out = capsys.readouterr().out
    assert "3 次录音" in out
    assert (tmp_path / "multi.png").exists()


def test_compare_rejects_when_any_take_is_silent(tmp_path, capsys):
    reference = write_tone(tmp_path / "ref.wav")
    good = write_tone(tmp_path / "good.wav")
    sr = 16000
    silent = tmp_path / "silent.wav"
    sf.write(silent, np.zeros(sr * 2, dtype=np.float32), sr)

    exit_code = cli.main(
        ["compare", "--ref", str(reference),
         "--user", str(good), "--user", str(silent)]
    )
    assert exit_code == 1
    assert "静音" in capsys.readouterr().err
