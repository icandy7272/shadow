"""把旧记录里拆开的同一轮并回一行：先备份，录音跟着挪，空行不碰。"""

from datetime import datetime, timedelta

import pytest

from shadow import cli, config, db
from tests.test_cli import _seed_segment

T0 = datetime(2026, 9, 14, 9, 0).astimezone()
TEXT = "should have been there"


@pytest.fixture(autouse=True)
def isolated_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path / "data"))


def _run(connection, segment_id, *, minutes, rating=None, dictation=False, takes=0):
    """某个时刻存下的一行：只做了其中一步（旧页面就是这么存的）。"""
    run_id = db.start_run(connection, segment_id=segment_id, unit_index=1, unit_text=TEXT)
    if rating is not None:
        db.set_blind_rating(connection, run_id, rating)
    if dictation:
        db.set_dictation(connection, run_id, correct=3, total=4, unknown=1, replays=2)
    for take in range(takes):
        db.add_attempt(connection, run_id=run_id, audio_path=f"t{run_id}-{take}.wav",
                       asr_text=TEXT, metrics={"accuracy": 1.0, "speech_ratio": 1.0,
                                               "pause_ratio": None, "issues": []})
    stamp = (T0 + timedelta(minutes=minutes)).isoformat(timespec="seconds")
    connection.execute("UPDATE practice_runs SET started_at = ?, finished_at = ? WHERE id = ?",
                       (stamp, stamp, run_id))
    connection.commit()
    return run_id


def _rows(connection):
    return [tuple(row) for row in connection.execute(
        "SELECT id, blind_rating, gapfill_total, gapfill_unknown, gapfill_replays,"
        " (SELECT COUNT(*) FROM attempts a WHERE a.run_id = r.id)"
        " FROM practice_runs r ORDER BY id")]


def test_one_sitting_is_folded_into_its_first_row(capsys):
    connection, segment_id = _seed_segment()
    first = _run(connection, segment_id, minutes=0, rating=4)
    _run(connection, segment_id, minutes=1, dictation=True)
    _run(connection, segment_id, minutes=3, takes=3)
    later = _run(connection, segment_id, minutes=60 * 24, rating=5)     # 第二天，另一轮
    connection.close()

    assert cli.main(["merge-rounds"]) == 0

    connection = db.connect()
    assert _rows(connection) == [(first, 4, 4, 1, 2, 3), (later, 5, None, None, None, 0)]
    assert connection.execute("SELECT finished_at FROM practice_runs WHERE id = ?",
                              (first,)).fetchone()[0].startswith("2026-09-14T09:03")
    connection.close()
    out = capsys.readouterr().out
    assert "并了 1 轮" in out and "少了 2 行" in out


def test_it_backs_up_first_and_a_dry_run_changes_nothing(capsys):
    connection, segment_id = _seed_segment()
    _run(connection, segment_id, minutes=0, rating=4)
    _run(connection, segment_id, minutes=1, dictation=True)
    before = _rows(connection)
    connection.close()

    assert cli.main(["merge-rounds", "--dry-run"]) == 0
    connection = db.connect()
    assert _rows(connection) == before
    connection.close()
    assert not list((config.data_dir() / "backups").glob("*.db"))
    assert "会并 1 轮" in capsys.readouterr().out

    assert cli.main(["merge-rounds"]) == 0
    backups = list((config.data_dir() / "backups").glob("shadow-before-merge-rounds-*.db"))
    assert len(backups) == 1
    import sqlite3
    saved = sqlite3.connect(backups[0])
    assert saved.execute("SELECT COUNT(*) FROM practice_runs").fetchone()[0] == 2
    saved.close()


def test_nothing_to_merge_leaves_the_database_alone(capsys):
    connection, segment_id = _seed_segment()
    _run(connection, segment_id, minutes=0, rating=4)
    connection.close()

    assert cli.main(["merge-rounds"]) == 0
    assert "没有要并的" in capsys.readouterr().out
    assert not list((config.data_dir() / "backups").glob("*.db"))
