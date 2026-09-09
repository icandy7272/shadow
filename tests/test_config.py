from shadow import config


def test_data_dir_honours_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path))
    assert config.data_dir() == tmp_path
    assert config.db_path() == tmp_path / "shadow.db"
    assert config.source_audio_dir() == tmp_path / "audio" / "sources"


def test_ensure_dirs_creates_whole_tree(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path))
    config.ensure_dirs()
    assert config.source_audio_dir().is_dir()
    assert config.attempt_audio_dir().is_dir()
    assert config.segment_audio_dir().is_dir()


def test_segment_bounds_are_sane():
    assert config.SEGMENT_MIN_SEC < config.SEGMENT_MAX_SEC
    assert 0 < config.PAUSE_GAP_SEC < 2.0


def test_unit_bounds_default_to_sentence_level():
    # 0 表示不合并短句，即严格一句一个
    assert config.UNIT_MIN_SEC == 0.0
    assert config.UNIT_MIN_WORDS >= 1
    assert config.UNIT_MAX_SEC > 1.0
