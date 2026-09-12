"""离线词典：用几行 CSV 建库，不联网。"""

import pytest

from shadow import dictionary

HEADER = ("word,phonetic,definition,translation,pos,collins,oxford,tag,bnc,frq,"
          "exchange,detail,audio\n")
# 释义里的换行在 ECDICT 的 CSV 里存成字面的 \n
ROWS = (
    "graduate,'grædʒuət,,n. 毕业生\\nv. 毕业,,,,,,,"
    "d:graduated/p:graduated/i:graduating/3:graduates,,\n"
    "graduated,,,a. 毕业了的,,,,,,,0:graduate/1:pd,,\n"
    "Jobs,,,n. 乔布斯,,,,,,,,,\n"
    "jobs,,,n. 工作（job 的复数）,,,,,,,0:job/1:s,,\n"
    "job,,,n. 工作,,,,,,,,,\n"
)


def _fetch(url, dest, report=None):
    dest.write_text(HEADER + ROWS, encoding="utf-8")


@pytest.fixture(autouse=True)
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path / "data"))


@pytest.fixture()
def installed():
    return dictionary.install(fetch=_fetch)


def test_nothing_is_found_before_installing():
    assert not dictionary.installed()
    assert dictionary.lookup("graduate") is None


def test_install_builds_the_dictionary_once(installed):
    assert installed == 4
    assert dictionary.installed()
    assert dictionary.install(fetch=_fetch) is None


def test_force_downloads_and_builds_again():
    calls = []

    def fetch(url, dest, report=None):
        calls.append(url)
        _fetch(url, dest)

    dictionary.install(fetch=fetch)
    assert dictionary.install(fetch=fetch, force=True) == 4
    assert calls == [dictionary.SOURCE_URL, dictionary.SOURCE_URL]


def test_lookup_gives_phonetic_and_one_meaning_per_line(installed):
    entry = dictionary.lookup("Graduate")
    assert entry.phonetic == "'grædʒuət"
    assert entry.meanings == ("n. 毕业生", "v. 毕业")


def test_an_inflected_word_brings_its_lemma(installed):
    """写不出 graduated，要能顺带看到 graduate 的释义。"""
    entry = dictionary.lookup("graduated")
    assert entry.meanings == ("a. 毕业了的",)
    assert entry.lemma.word == "graduate"
    assert entry.lemma.meanings == ("n. 毕业生", "v. 毕业")


def test_the_lowercase_row_wins_over_a_capitalised_duplicate(installed):
    assert dictionary.lookup("jobs").meanings == ("n. 工作（job 的复数）",)


def test_a_missing_word_is_none(installed):
    assert dictionary.lookup("Reed") is None


def test_lookup_many_answers_every_word(installed):
    found = dictionary.lookup_many(["job", "nope"])
    assert found["job"].meanings == ("n. 工作",)
    assert found["nope"] is None
