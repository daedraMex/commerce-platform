from factory.outcomes import build_issue_comment


def test_issue_comment_includes_open_question_decisions_and_log_tail():
    comment = build_issue_comment(
        open_question="Should it be a POST?",
        decisions="- Chose A.",
        log_tail="FAILED test_x\n1 failed",
        model="deepseek/deepseek-flash",
        attempts=5,
        failing_check="scripts/check.sh",
    )
    assert "Should it be a POST?" in comment
    assert "Chose A." in comment
    assert "FAILED test_x" in comment
    assert "scripts/check.sh" in comment


def test_issue_comment_omits_missing_sections():
    comment = build_issue_comment(
        open_question=None,
        decisions="",
        log_tail="",
        model="m",
        attempts=1,
        failing_check="x",
    )
    assert "## Open question" not in comment
    assert "## Decisions so far" not in comment
    assert "## Last log lines" not in comment
