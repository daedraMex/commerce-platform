from factory.decisions import extract_open_question


def test_extract_open_question_at_top():
    decisions = "OPEN QUESTION: Should this be a POST or a PUT?\n\n- Chose X.\n"
    assert extract_open_question(decisions) == "Should this be a POST or a PUT?"


def test_extract_no_question_returns_none():
    assert extract_open_question("# Decisions\n\n- Chose X.\n") is None


def test_extract_empty_returns_none():
    assert extract_open_question("") is None


def test_extract_question_ignores_leading_whitespace():
    assert extract_open_question("  \n OPEN QUESTION: thing\n") == "thing"
