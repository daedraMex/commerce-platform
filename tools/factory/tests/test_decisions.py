from factory.decisions import extract_decisions, extract_open_question, extract_summary


def test_extract_open_question_at_top():
    decisions = "OPEN QUESTION: Should this be a POST or a PUT?\n\n- Chose X.\n"
    assert extract_open_question(decisions) == "Should this be a POST or a PUT?"


def test_extract_no_question_returns_none():
    assert extract_open_question("# Summary\n\n- Chose X.\n") is None


def test_extract_empty_returns_none():
    assert extract_open_question("") is None


def test_extract_question_ignores_leading_whitespace():
    assert extract_open_question("  \n OPEN QUESTION: thing\n") == "thing"


def test_extract_summary_and_decisions():
    doc = "# Summary\nBuilt the widget.\n\n# Decisions\n\n- Chose A.\n- Chose B.\n"
    assert extract_summary(doc) == "Built the widget."
    assert extract_decisions(doc) == "- Chose A.\n- Chose B."


def test_extract_summary_missing_returns_empty():
    assert extract_summary("# Decisions\n\n- Chose A.") == ""
