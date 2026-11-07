from factory.pr_body import build_pr_body


def test_pr_body_closes_ticket_and_records_model_and_decisions():
    body = build_pr_body(
        ticket_number=7,
        summary="Adds the widget endpoint.",
        model="deepseek/deepseek-flash",
        decisions="- Chose A over B because C.\n",
    )
    assert "Closes #7" in body
    assert "Adds the widget endpoint." in body
    assert "Model: deepseek/deepseek-flash" in body
    assert "## Decisions" in body
    assert "Chose A over B because C." in body


def test_pr_body_omits_decisions_when_empty():
    body = build_pr_body(
        ticket_number=7,
        summary="Adds the widget endpoint.",
        model="deepseek/deepseek-flash",
        decisions="",
    )
    assert "## Decisions" not in body
    assert "Closes #7" in body
