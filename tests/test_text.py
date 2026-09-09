from shadow.text import normalise


def test_ignores_case_and_punctuation():
    assert normalise("Should,") == "should"
    assert normalise("HAVE.") == "have"
    assert normalise("don't") == "don't"


def test_distinct_numeric_words_do_not_collide():
    # 全数字词被剥成空串会互相误判为相等，虚高可懂度并污染时间对齐锚点
    assert normalise("2023") != normalise("2024")
    assert normalise("2023") == "2023"


def test_empty_input_stays_empty():
    assert normalise("") == ""
