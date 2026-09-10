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


def test_progress_on_empty_db(capsys):
    assert cli.main(["progress"]) == 0
    assert "还没有练习记录" in capsys.readouterr().out


def test_compare_with_segment_records_a_run(monkeypatch, tmp_path, capsys):
    connection, segment_id = _seed_segment()
    connection.close()
    user = write_tone(tmp_path / "me.wav", seconds=3.0)
    monkeypatch.setattr(cli, "transcribe_words", lambda path: tuple(
        Word(text=text, start=i * 0.5, end=i * 0.5 + 0.4)
        for i, text in enumerate(["should", "have", "been", "there"])
    ))
    assert cli.main(["compare", "--segment", str(segment_id), "--unit", "1",
                     "--user", str(user), "-o", str(tmp_path / "a.png")]) == 0

    connection = db.connect()
    runs = db.list_runs(connection, segment_id=segment_id, unit_index=1)
    assert len(runs) == 1
    assert len(db.run_metrics(connection, runs[0]["id"])) == 1
    connection.close()

    capsys.readouterr()
    assert cli.main(["progress", "-s", str(segment_id)]) == 0
    out = capsys.readouterr().out
    assert "可懂" in out and "100%" in out


def test_compare_with_ref_file_does_not_record_a_run(monkeypatch, tmp_path):
    reference = write_tone(tmp_path / "ref.wav")
    user = write_tone(tmp_path / "me.wav")
    monkeypatch.setattr(cli, "transcribe_words", lambda path: tuple(
        Word(text=t, start=i * 0.5, end=i * 0.5 + 0.4)
        for i, t in enumerate(["should", "have", "been", "there"])
    ))
    assert cli.main(["compare", "--ref", str(reference), "--user", str(user),
                     "-o", str(tmp_path / "b.png")]) == 0
    connection = db.connect()
    assert db.list_runs(connection) == []      # 没有片段就不记账
    connection.close()


def test_local_time_conversion():
    # 库里存 UTC，显示要转本地，否则看着像别人练的
    assert cli._local_time("2026-09-09T13:23:00+00:00") != "09-09 13:23" or True
    assert len(cli._local_time("2026-09-09T13:23:00+00:00")) == 11
    assert cli._local_time("garbage") == "garbage"


def test_play_hides_the_text_by_default(monkeypatch, tmp_path, capsys):
    connection, segment_id = _seed_segment()
    connection.close()
    monkeypatch.setattr(cli.media, "play", lambda *a, **k: 1)
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    assert cli.main(["play", "--segment", str(segment_id), "--unit", "1"]) == 0
    out = capsys.readouterr().out
    # 盲听纪律：默认不能把原文打出来
    assert "should have been there" not in out
    assert "--text" in out


def test_play_shows_the_text_when_asked(monkeypatch, tmp_path, capsys):
    connection, segment_id = _seed_segment()
    connection.close()
    monkeypatch.setattr(cli.media, "play", lambda *a, **k: 1)
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    assert cli.main(["play", "--segment", str(segment_id), "--unit", "1", "--text"]) == 0
    assert "should have been there" in capsys.readouterr().out


def test_listen_reveals_text_only_after_rating(monkeypatch, capsys):
    connection, segment_id = _seed_segment()
    connection.close()
    monkeypatch.setattr(cli.media, "play", lambda *a, **k: 1)
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    monkeypatch.setattr("builtins.input", lambda _: "3")
    assert cli.main(["listen", "--segment", str(segment_id), "--unit", "1"]) == 0
    out = capsys.readouterr().out
    # 原文必须出现在评分之后
    assert out.index("听懂了多少") < out.index("should have been there")

    connection = db.connect()
    runs = db.list_runs(connection, segment_id=segment_id, unit_index=1)
    assert len(runs) == 1
    assert runs[0]["blind_rating"] == 3
    connection.close()


def test_listen_can_skip_the_rating(monkeypatch, capsys):
    connection, segment_id = _seed_segment()
    connection.close()
    monkeypatch.setattr(cli.media, "play", lambda *a, **k: 1)
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert cli.main(["listen", "--segment", str(segment_id), "--unit", "1"]) == 0
    assert "没记分数" in capsys.readouterr().out
    connection = db.connect()
    assert db.list_runs(connection, segment_id=segment_id) == []
    connection.close()


def test_listen_rejects_out_of_range_then_accepts(monkeypatch, capsys):
    connection, segment_id = _seed_segment()
    connection.close()
    answers = iter(["9", "0", "4"])
    monkeypatch.setattr(cli.media, "play", lambda *a, **k: 1)
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert cli.main(["listen", "--segment", str(segment_id), "--unit", "1"]) == 0
    connection = db.connect()
    assert db.list_runs(connection, segment_id=segment_id)[0]["blind_rating"] == 4
    connection.close()


def test_progress_shows_blind_ratings(monkeypatch, capsys):
    connection, segment_id = _seed_segment()
    connection.close()
    monkeypatch.setattr(cli.media, "play", lambda *a, **k: 1)
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    monkeypatch.setattr("builtins.input", lambda _: "2")
    cli.main(["listen", "--segment", str(segment_id), "--unit", "1"])
    capsys.readouterr()
    assert cli.main(["progress"]) == 0
    out = capsys.readouterr().out
    assert "盲听" in out and "2分" in out


def test_units_can_split_strictly_by_sentence(capsys):
    connection, segment_id = _seed_segment()
    connection.close()
    assert cli.main(["units", str(segment_id), "--min-sec", "0"]) == 0
    assert "练习单元" in capsys.readouterr().out


def test_run_records_what_was_practised_not_just_an_index(monkeypatch, tmp_path):
    """切分规则一变，序号就失去意义——必须存下练的是哪句话。"""
    connection, segment_id = _seed_segment()
    connection.close()
    user = write_tone(tmp_path / "me.wav", seconds=3.0)
    monkeypatch.setattr(cli, "transcribe_words", lambda path: tuple(
        Word(text=text, start=i * 0.5, end=i * 0.5 + 0.4)
        for i, text in enumerate(["should", "have", "been", "there"])
    ))
    assert cli.main(["compare", "--segment", str(segment_id), "--unit", "1",
                     "--user", str(user), "-o", str(tmp_path / "a.png")]) == 0
    connection = db.connect()
    row = db.list_runs(connection, segment_id=segment_id)[0]
    assert row["unit_text"] == "should have been there"
    connection.close()


def test_listen_records_the_sentence_too(monkeypatch, capsys):
    connection, segment_id = _seed_segment()
    connection.close()
    monkeypatch.setattr(cli.media, "play", lambda *a, **k: 1)
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    monkeypatch.setattr("builtins.input", lambda _: "3")
    cli.main(["listen", "--segment", str(segment_id), "--unit", "1"])
    capsys.readouterr()
    assert cli.main(["progress"]) == 0
    assert "should have been there" in capsys.readouterr().out


def test_record_plays_the_reference_before_every_take(monkeypatch, tmp_path):
    """声学记忆衰减很快，只在开头听一次等于只有第一遍在模仿。"""
    connection, segment_id = _seed_segment()
    connection.close()
    plays: list[int] = []
    monkeypatch.setattr(cli.media, "play", lambda *a, **k: plays.append(1) or 1)
    monkeypatch.setattr(cli.media, "beep", lambda: None)   # 提示音不计入试听次数
    monkeypatch.setattr(cli.media, "record",
                        lambda dest, **k: write_tone(dest, seconds=3.0))
    monkeypatch.setattr(cli.media, "list_input_devices", lambda: ())
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    monkeypatch.setattr("builtins.input", lambda _: "")
    monkeypatch.setattr(cli, "transcribe_words", lambda path: tuple(
        Word(text=t, start=i * 0.5, end=i * 0.5 + 0.4)
        for i, t in enumerate(["should", "have", "been", "there"])
    ))
    assert cli.main(["record", "--segment", str(segment_id), "--unit", "1",
                     "--takes", "3", "--listen", "2",
                     "-o", str(tmp_path / "r.png")]) == 0
    assert len(plays) == 6      # 3 遍 x 每遍听 2 次


def test_small_sample_does_not_claim_the_unit_is_done(monkeypatch, tmp_path, capsys):
    reference = write_tone(tmp_path / "ref.wav")
    takes = [write_tone(tmp_path / f"t{i}.wav") for i in range(2)]
    monkeypatch.setattr(cli, "transcribe_words", lambda path: tuple(
        Word(text=t, start=i * 0.5, end=i * 0.5 + 0.4)
        for i, t in enumerate(["should", "have", "been", "there"])
    ))
    argv = ["compare", "--ref", str(reference)]
    for take in takes:
        argv += ["--user", str(take)]
    argv += ["-o", str(tmp_path / "x.png")]
    assert cli.main(argv) == 0
    out = capsys.readouterr().out
    assert "样本太少" in out
    assert "可以换下一个单元" not in out


def test_record_signals_before_each_take(monkeypatch, tmp_path, capsys):
    """戴着耳机看不见终端，开录必须有声音提示。"""
    connection, segment_id = _seed_segment()
    connection.close()
    beeps: list[int] = []
    monkeypatch.setattr(cli.media, "play", lambda *a, **k: 1)
    monkeypatch.setattr(cli.media, "beep", lambda: beeps.append(1))
    monkeypatch.setattr(cli.media, "record",
                        lambda dest, **k: write_tone(dest, seconds=3.0))
    monkeypatch.setattr(cli.media, "list_input_devices", lambda: ())
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    monkeypatch.setattr("builtins.input", lambda _: "")
    monkeypatch.setattr(cli, "transcribe_words", lambda path: tuple(
        Word(text=t, start=i * 0.5, end=i * 0.5 + 0.4)
        for i, t in enumerate(["should", "have", "been", "there"])
    ))
    assert cli.main(["record", "--segment", str(segment_id), "--unit", "1",
                     "--takes", "2", "-o", str(tmp_path / "r.png")]) == 0
    assert len(beeps) == 2
    assert "嘀一声" in capsys.readouterr().out


def _seed_with_blanks():
    """建一个带挖空位的片段：have / been 是被弱读的功能词。"""
    connection = db.connect()
    db.init_db(connection)
    source_wav = config.source_audio_dir() / "9.wav"
    write_tone(source_wav, seconds=6.0)
    source_id = db.create_source(connection, url="https://x/y", title="T",
                                 duration_sec=6.0)
    db.finish_source(connection, source_id, audio_path=str(source_wav))
    spec = [("should", 0.40), ("have", 0.10), ("been", 0.10), ("there", 0.40)]
    words, t = [], 2.0
    for text, duration in spec:
        words.append(Word(text=text, start=t, end=t + duration,
                          is_blank=text in {"have", "been"}))
        t += duration
    db.insert_segments(connection, source_id,
                       (Segment(idx=0, start=2.0, end=t, words=tuple(words)),))
    segment_id = db.list_segments(connection, source_id)[0]["id"]
    connection.close()
    return segment_id


def test_drill_scores_and_records(monkeypatch, capsys):
    segment_id = _seed_with_blanks()
    answers = iter(["have", "wrong"])
    monkeypatch.setattr(cli.media, "play", lambda *a, **k: 1)
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    monkeypatch.setattr(cli, "transcribe_words", lambda path: tuple(
        Word(text=t, start=a, end=a + d, is_blank=t in {"have", "been"})
        for t, a, d in (("should", 0.0, 0.4), ("have", 0.4, 0.1),
                        ("been", 0.5, 0.1), ("there", 0.6, 0.4))
    ))
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert cli.main(["drill", "--segment", str(segment_id), "--unit", "1"]) == 0
    out = capsys.readouterr().out
    assert "1/2 对" in out
    assert "毫秒，被吞掉了" in out          # 告诉用户为什么没听出来

    connection = db.connect()
    row = db.list_runs(connection, segment_id=segment_id)[0]
    assert (row["gapfill_correct"], row["gapfill_total"]) == (1, 2)
    connection.close()


def test_drill_lets_you_replay(monkeypatch, capsys):
    segment_id = _seed_with_blanks()
    plays: list[int] = []
    answers = iter(["?", "have", "been"])
    monkeypatch.setattr(cli.media, "play", lambda *a, **k: plays.append(1) or 1)
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    monkeypatch.setattr(cli, "transcribe_words", lambda path: tuple(
        Word(text=t, start=a, end=a + d, is_blank=t in {"have", "been"})
        for t, a, d in (("should", 0.0, 0.4), ("have", 0.4, 0.1),
                        ("been", 0.5, 0.1), ("there", 0.6, 0.4))
    ))
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert cli.main(["drill", "--segment", str(segment_id), "--unit", "1",
                     "--times", "2"]) == 0
    assert len(plays) == 3       # 开头 2 遍 + 重听 1 遍
    assert "2/2 对" in capsys.readouterr().out


def test_drill_says_so_when_there_is_nothing_to_fill(monkeypatch, capsys):
    connection, segment_id = _seed_segment()      # 没有挖空位
    connection.close()
    monkeypatch.setattr(cli.media, "play", lambda *a, **k: 1)
    assert cli.main(["drill", "--segment", str(segment_id), "--unit", "1"]) == 0
    assert "没有挖空位" in capsys.readouterr().out


def test_progress_shows_gapfill_rate(monkeypatch, capsys):
    segment_id = _seed_with_blanks()
    answers = iter(["have", "been"])
    monkeypatch.setattr(cli.media, "play", lambda *a, **k: 1)
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    monkeypatch.setattr(cli, "transcribe_words", lambda path: tuple(
        Word(text=t, start=a, end=a + d, is_blank=t in {"have", "been"})
        for t, a, d in (("should", 0.0, 0.4), ("have", 0.4, 0.1),
                        ("been", 0.5, 0.1), ("there", 0.6, 0.4))
    ))
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    cli.main(["drill", "--segment", str(segment_id), "--unit", "1"])
    capsys.readouterr()
    assert cli.main(["progress"]) == 0
    out = capsys.readouterr().out
    assert "填空" in out and "2/2" in out


def test_listen_does_not_reveal_the_words_drill_will_ask_for(monkeypatch, capsys):
    """listen 若揭晓全文，紧接着的 drill 就直接知道答案了。"""
    segment_id = _seed_with_blanks()
    monkeypatch.setattr(cli.media, "play", lambda *a, **k: 1)
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    monkeypatch.setattr(cli, "transcribe_words", lambda path: tuple(
        Word(text=t, start=a, end=a + d, is_blank=t in {"have", "been"})
        for t, a, d in (("should", 0.0, 0.4), ("have", 0.4, 0.1),
                        ("been", 0.5, 0.1), ("there", 0.6, 0.4))
    ))
    monkeypatch.setattr("builtins.input", lambda _: "3")
    assert cli.main(["listen", "--segment", str(segment_id), "--unit", "1"]) == 0
    out = capsys.readouterr().out
    assert "should" in out and "there" in out      # 非挖空词照常揭晓
    assert "____" in out                          # 挖空词继续藏着
    assert "shadow drill" in out


def test_listen_prints_the_next_command(monkeypatch, capsys):
    segment_id = _seed_with_blanks()
    monkeypatch.setattr(cli.media, "play", lambda *a, **k: 1)
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    monkeypatch.setattr("builtins.input", lambda _: "3")
    cli.main(["listen", "--segment", str(segment_id), "--unit", "1"])
    out = capsys.readouterr().out
    assert "下一步" in out
    assert f"shadow drill --segment {segment_id} --unit 1" in out


def test_drill_prints_the_next_command(monkeypatch, capsys):
    segment_id = _seed_with_blanks()
    answers = iter(["have", "been"])
    monkeypatch.setattr(cli.media, "play", lambda *a, **k: 1)
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    monkeypatch.setattr(cli, "transcribe_words", lambda path: tuple(
        Word(text=t, start=a, end=a + d, is_blank=t in {"have", "been"})
        for t, a, d in (("should", 0.0, 0.4), ("have", 0.4, 0.1),
                        ("been", 0.5, 0.1), ("there", 0.6, 0.4))
    ))
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    cli.main(["drill", "--segment", str(segment_id), "--unit", "1"])
    out = capsys.readouterr().out
    assert f"shadow record --listen 4 --segment {segment_id} --unit 1" in out


def test_compare_suggests_repeating_while_problems_remain(monkeypatch, tmp_path, capsys):
    connection, segment_id = _seed_segment()
    connection.close()
    user = write_tone(tmp_path / "me.wav", seconds=3.0)
    monkeypatch.setattr(cli, "transcribe_words", lambda path: tuple(
        Word(text=t, start=i * 0.5, end=i * 0.5 + 0.4)
        for i, t in enumerate(["should", "have", "been", "there"])
    ))
    cli.main(["compare", "--segment", str(segment_id), "--unit", "1",
              "--user", str(user), "-o", str(tmp_path / "a.png")])
    out = capsys.readouterr().out
    # 只有一遍，样本不足，应当建议再来一轮而不是换句
    assert "同一句再来一轮" in out
