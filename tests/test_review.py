"""review.run 的进度事件——网页版进度条全靠它。"""

import numpy as np
import pytest
import soundfile as sf

from shadow import review
from shadow.models import Word

WORDS = tuple(
    Word(text=text, start=start, end=start + dur)
    for text, start, dur in (("It", 0.0, 0.3), ("was", 0.4, 0.1),
                             ("a", 0.5, 0.1), ("start.", 0.7, 0.4))
)


def _wav(path, seconds=1.5):
    t = np.arange(int(seconds * 16000)) / 16000
    sf.write(path, (0.4 * np.sin(2 * np.pi * 200 * t)).astype("float32"), 16000)
    return path


def _fake(_path):
    return WORDS


def test_run_announces_each_transcription_before_it_starts(tmp_path):
    ref = _wav(tmp_path / "ref.wav")
    takes = [_wav(tmp_path / "a.wav"), _wav(tmp_path / "b.wav")]

    steps = list(review.run(ref, WORDS, takes, transcribe=_fake))

    # 原声一步，每遍一步；done 是这步开工前已完成的步数
    assert [(s.stage, s.done, s.total) for s in steps] == [
        ("reference", 0, 3), ("take", 1, 3), ("take", 2, 3),
    ]
    assert [s.index for s in steps] == [0, 1, 2]


def test_evaluate_drives_run_to_the_end_and_returns_the_review(tmp_path):
    ref = _wav(tmp_path / "ref.wav")
    takes = [_wav(tmp_path / "a.wav")]

    result = review.evaluate(ref, WORDS, takes, transcribe=_fake)

    assert result is not None
    assert result.summary.count == 1


def test_evaluate_returns_none_when_no_take_is_usable(tmp_path):
    ref = _wav(tmp_path / "ref.wav")
    takes = [_wav(tmp_path / "a.wav")]
    late = tuple(Word(text=w.text, start=w.start + 5, end=w.end + 5) for w in WORDS)

    result = review.evaluate(ref, WORDS, takes,
                             transcribe=lambda p: WORDS if p == ref else late)

    assert result is None


def test_run_snaps_both_sides_to_their_real_onset(tmp_path):
    """两边的首词起点都对到真正的发声点，同时播放才对得齐。"""
    import numpy as np
    import soundfile as sf

    sr = 16000
    tone = 0.4 * np.sin(2 * np.pi * 150 * np.arange(sr) / sr)
    quiet = np.zeros(int(0.4 * sr), dtype="float32")
    ref = tmp_path / "ref.wav"
    take = tmp_path / "take.wav"
    sf.write(ref, np.concatenate([quiet, tone]).astype("float32"), sr)
    sf.write(take, np.concatenate([quiet, tone]).astype("float32"), sr)

    # 转写都说从 0 开始，实际两条都是 0.4 秒之后才出声
    words = tuple(Word(text=x, start=a, end=a + d)
                  for x, a, d in (("It", 0.0, 0.7), ("was", 0.7, 0.7)))
    result = review.evaluate(ref, words, [take], transcribe=lambda _p: words)

    assert result is not None
    assert result.ref_words[0].start == pytest.approx(0.4, abs=0.06)
    assert result.best.words[0].start == pytest.approx(0.4, abs=0.06)
    assert result.ref_words[1] == words[1]


def test_takes_get_their_word_boundaries_realigned(tmp_path, monkeypatch):
    """逐词判定（拖长了、该升没升）全靠词边界，而转写给的边界是猜的。"""
    from shadow.analysis import align

    seen = []

    def fake_align(path, words):
        seen.append(path.name)
        return tuple(Word(text=w.text, start=w.start + 0.1, end=w.end + 0.1)
                     for w in words)

    monkeypatch.setattr(align, "align_words", fake_align)
    monkeypatch.setattr(review, "align_words", fake_align)

    ref = _wav(tmp_path / "ref.wav")
    take = _wav(tmp_path / "take.wav")
    result = review.evaluate(ref, WORDS, [take], transcribe=_fake)

    assert result is not None
    assert seen == ["take.wav"]          # 原声的时间戳在导入时已经对过了


def test_cached_append_only_analyses_new_take_and_survives_cache_reopen(tmp_path, monkeypatch):
    from shadow.review_cache import AnalysisCache
    ref = _wav(tmp_path / 'ref.wav')
    takes = [_wav(tmp_path / f'{i}.wav') for i in range(4)]
    calls = []
    def transcribe(path):
        calls.append(path)
        return WORDS
    def result(paths):
        steps = review.run(ref, WORDS, paths, transcribe=transcribe,
                           cache=AnalysisCache(tmp_path / 'cache'))
        events = []
        while True:
            try:
                events.append(next(steps))
            except StopIteration as stop:
                return events, stop.value
    analysed = []
    analyse = review.analyse
    def counted_analyse(path):
        analysed.append(path)
        return analyse(path)
    monkeypatch.setattr(review, 'analyse', counted_analyse)
    _, first = result(takes[:3])
    assert len(calls) == 4
    calls.clear()
    analysed.clear()
    events, fourth = result(takes)
    assert calls == [takes[3]]
    assert analysed == [takes[3]]
    assert [(step.done, step.total) for step in events] == [(0, 1)]
    assert [step.index for step in events if step.stage == 'take'] == [4]
    assert fourth.summary.count == 4
    assert [take.words for take in fourth.takes[:3]] == [take.words for take in first.takes]
    for old, reused in zip(first.takes, fourth.takes):
        np.testing.assert_allclose(old.prosody.semitones, reused.prosody.semitones, equal_nan=True)
    calls.clear()
    _, retry = result(takes)
    assert calls == []
    assert retry.summary == fourth.summary
    uncached = review.evaluate(ref, WORDS, takes, transcribe=transcribe)
    assert fourth.summary == uncached.summary


def test_cache_invalidation_and_corruption_only_reprocess_affected_inputs(tmp_path):
    from shadow.review_cache import AnalysisCache
    ref = _wav(tmp_path / 'ref.wav')
    take = _wav(tmp_path / 'take.wav')
    calls = []
    def process(words=WORDS):
        cache = AnalysisCache(tmp_path / 'cache')
        return list(review.run(ref, words, [take],
            transcribe=lambda path: calls.append(path) or WORDS, cache=cache))
    process()
    calls.clear()
    _wav(take, seconds=1.7)
    process()
    assert calls == [take]
    calls.clear()
    for entry in (tmp_path / 'cache').glob('*.json'):
        entry.write_text('{broken')
    process()
    assert calls == [ref, take]
    calls.clear()
    process(tuple(Word(w.text.upper(), w.start, w.end) for w in WORDS))
    assert calls == [ref, take]


def test_cache_write_failure_does_not_discard_analysis(tmp_path):
    from shadow.review_cache import AnalysisCache
    blocked = tmp_path / 'not-a-directory'
    blocked.write_text('file')
    result = review.run(_wav(tmp_path / 'ref.wav'), WORDS, [_wav(tmp_path / 'take.wav')],
                        transcribe=_fake, cache=AnalysisCache(blocked))
    while True:
        try:
            next(result)
        except StopIteration as stop:
            assert stop.value.summary.count == 1
            break
