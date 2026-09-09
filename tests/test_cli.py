import numpy as np
import pytest
import soundfile as sf

from shadow import cli, db
from shadow.models import Word


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


def test_compare_rejects_silent_recording(monkeypatch, tmp_path, capsys):
    reference = write_tone(tmp_path / "ref.wav")
    sr = 16000
    sf.write(tmp_path / "silent.wav", np.zeros(sr * 2, dtype=np.float32), sr)
    exit_code = cli.main(
        ["compare", "--ref", str(reference), "--user", str(tmp_path / "silent.wav")]
    )
    assert exit_code == 1
    assert "静音" in capsys.readouterr().err
