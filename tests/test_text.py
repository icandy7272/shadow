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


def test_a_number_written_in_digits_or_words_is_the_same_word():
    """转写有时写 7，有时写 seven，同一句话被判成「seven→听成 7」。"""
    assert normalise("7") == normalise("seven")
    assert normalise("seven,") == normalise("7.")
    assert normalise("Twenty-five") == normalise("25")
    assert normalise("0") == normalise("zero")
    assert normalise("99") == normalise("ninety-nine")


def test_ordinals_match_their_digit_form():
    assert normalise("1st") == normalise("first")
    assert normalise("7th") == normalise("seventh")
    assert normalise("22nd") == normalise("twenty-second")
    assert normalise("40th") == normalise("fortieth")


def test_different_numbers_stay_different():
    assert normalise("7") != normalise("eight")
    assert normalise("17") != normalise("seventy")
    assert normalise("seven") != normalise("seventh")
