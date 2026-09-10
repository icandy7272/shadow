"""review.run 的进度事件——网页版进度条全靠它。"""

import numpy as np
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
