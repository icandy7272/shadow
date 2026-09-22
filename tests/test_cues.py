"""复述页的提示：只给几个关键词，提醒讲到哪儿了，不给原句。"""

from shadow.drill.cues import cues


def test_it_keeps_the_words_that_carry_the_meaning_in_order():
    assert cues(["Truth be told, I never graduated from college."]) == ["graduated", "college"]


def test_names_stay_together_and_a_particle_stays_with_its_verb():
    """「dropped」单独给等于没给，「Reed」和「College」拆开也认不出是那所学校。"""
    assert cues(["I dropped out of Reed College after the first six months,"]) == \
        ["dropped out", "Reed College"]


def test_the_first_word_of_a_sentence_is_not_mistaken_for_a_name():
    assert cues(["Truth be told."]) == ["truth"]


def test_a_word_is_given_only_once():
    got = cues(["Truth be told, I never graduated from college.",
                "And this is the closest I've ever gotten to a college graduation."])
    assert got.count("college") == 1
    assert got == ["graduated", "college", "closest", "graduation"]


def test_there_is_a_ceiling():
    sentences = [f"Remarkable {word} happened yesterday." for word in
                 ("adventures", "discoveries", "friendships", "inventions", "journeys",
                  "lessons", "memories", "mistakes")]
    assert len(cues(sentences, limit=5)) == 5


def test_nothing_in_nothing_out():
    assert cues([]) == []
    assert cues(["I am, you know, so."]) == []


def test_a_capitalised_first_word_does_not_swallow_the_name_after_it():
    """句首的 Then 也是大写开头，不能和后面的 Reed College 连成一个名字。"""
    assert cues(["Then Reed College offered calligraphy instruction."])[0] == "Reed College"


def test_singular_and_plural_count_as_the_same_word():
    got = cues(["Today I want to tell you three stories.", "The first story is about dots."])
    assert "stories" in got
    assert "story" not in got


def test_with_many_sentences_every_one_still_gets_a_cue():
    """每句都给两个的话，上限用完时后面几句一个提示都没有——讲到后面就断了。"""
    pairs = [("adventures", "mountains"), ("discoveries", "oceans"), ("friendships", "rivers"),
             ("inventions", "valleys"), ("journeys", "deserts"), ("lessons", "forests"),
             ("memories", "islands"), ("mistakes", "glaciers"), ("surprises", "canyons")]
    got = cues([f"{a.title()} beside {b}." for a, b in pairs], limit=12)
    assert len(got) <= 12
    assert any(cue in ("surprises", "canyons") for cue in got)     # 最后一句也有


def test_rare_words_beat_common_ones():
    """实测：「following · turned out」落选了真正讲内容的 curiosity、intuition。
    常见的动词也能当提示，但排在不常见的实词后面。"""
    got = cues(["And much of what I stumbled into by following my curiosity and intuition "
                "turned out to be priceless later on."])
    assert got == ["curiosity", "intuition"]


def test_prepositions_are_not_cues():
    got = cues(["And I would walk the seven miles across town every Sunday night"])
    assert "across" not in got
    assert "Sunday" in got


def test_a_word_and_its_ing_form_count_once():
    got = cues(["I could stop taking the required classes that didn't interest me",
                "and begin dropping in on the ones that looked far more interesting."])
    assert not ("interest" in got and "interesting" in got)


def test_a_name_seen_once_is_not_given_again_in_part():
    got = cues(["Welcome to Stanford University.", "Stanford is beautiful."])
    assert "Stanford University" in got
    assert "stanford" not in [cue.lower() for cue in got]     # 句首那个会被当成普通词小写


def test_politeness_and_degree_words_are_not_cues():
    got = cues(["Please visit us.", "Thank you.", "It was pretty scary at the time."])
    assert not {"please", "thank", "pretty"} & set(got)
    assert "scary" in got
