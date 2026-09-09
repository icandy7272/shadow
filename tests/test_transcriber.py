import sys
import types

import pytest

from shadow import config


@pytest.fixture()
def fake_whisper(monkeypatch):
    calls = {}
    module = types.ModuleType("mlx_whisper")

    def transcribe(path, **kwargs):
        calls["path"] = path
        calls["kwargs"] = kwargs
        return {
            "segments": [
                {"words": [
                    {"word": " Should", "start": 0.00, "end": 0.28},
                    {"word": " have", "start": 0.28, "end": 0.34},
                ]},
                {"words": [
                    {"word": " been", "start": 0.34, "end": 0.60},
                    {"word": "   ", "start": 0.60, "end": 0.61},
                ]},
            ]
        }

    module.transcribe = transcribe
    monkeypatch.setitem(sys.modules, "mlx_whisper", module)
    return calls


def test_transcribe_flattens_words_and_drops_blanks(fake_whisper, tmp_path):
    from shadow.ingest.transcriber import transcribe_words

    words = transcribe_words(tmp_path / "a.wav")
    assert [w.text for w in words] == ["Should", "have", "been"]
    assert words[1].start == 0.28


def test_transcribe_pins_model_and_language(fake_whisper, tmp_path):
    from shadow.ingest.transcriber import transcribe_words

    transcribe_words(tmp_path / "a.wav")
    assert fake_whisper["kwargs"]["path_or_hf_repo"] == config.WHISPER_MODEL
    assert fake_whisper["kwargs"]["language"] == config.WHISPER_LANGUAGE
    assert fake_whisper["kwargs"]["word_timestamps"] is True
