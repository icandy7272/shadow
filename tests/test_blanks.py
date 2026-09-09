from shadow.drill.blanks import count_syllables, select_blanks, weak_ratios
from shadow.models import Word

FUNC = {"i", "would", "have", "to", "the", "but", "it", "was", "and", "had", "no",
        "for", "that"}

TEXTS = ["I", "would", "have", "gone", "to", "the", "market", "but", "it", "was",
         "closed", "and", "I", "had", "no", "time", "for", "that", "today", "anyway"]


def build_words(texts=TEXTS, *, func_dur=0.06, content_dur=0.45):
    words, t = [], 0.0
    for text in texts:
        duration = func_dur if text.lower() in FUNC else content_dur
        words.append(Word(text=text, start=t, end=t + duration))
        t += duration
    return tuple(words)


def test_count_syllables_uses_cmudict():
    assert count_syllables("the") == 1
    assert count_syllables("banana") == 3
    assert count_syllables("beautiful") == 3


def test_count_syllables_falls_back_for_unknown_words():
    assert count_syllables("zblorptrix") >= 1
    assert count_syllables("") == 1


def test_weak_ratios_are_lower_for_swallowed_words():
    words = build_words()
    ratios = weak_ratios(words)
    assert ratios[TEXTS.index("have")] < 0.6
    assert ratios[TEXTS.index("market")] > 1.0


def test_select_blanks_picks_only_swallowed_function_words():
    picked = select_blanks(build_words())
    assert len(picked) >= 3
    assert all(TEXTS[i].lower() in FUNC for i in picked)
    assert list(picked) == sorted(picked)


def test_select_blanks_respects_ratio_cap():
    # 20 词 -> int(20 * 0.15) = 3，下限也是 3
    assert len(select_blanks(build_words())) == 3


def test_select_blanks_caps_at_twelve_for_long_segments():
    words = build_words(TEXTS * 10)  # 200 词
    assert len(select_blanks(words)) == 12


def test_select_blanks_handles_empty_input():
    assert select_blanks(()) == ()


def test_select_blanks_degrades_gracefully_when_no_function_words():
    # 全是实词，没有功能词可挖 —— 应返回空，而不是硬凑到下限
    words = build_words(["market", "closed", "time", "today", "anyway"])
    assert select_blanks(words) == ()
