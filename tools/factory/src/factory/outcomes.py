"""Outcome handling: what to do after an agent run, success or stuck."""

from __future__ import annotations


def build_issue_comment(
    *,
    open_question: str | None,
    decisions: str,
    log_tail: str,
    model: str,
    attempts: int,
    failing_check: str,
) -> str:
    lines = [
        "The night factory could not finish this ticket.",
        "",
        f"- Model: `{model}`",
        f"- Attempts: {attempts}",
        f"- Failing check: `{failing_check}`",
    ]
    if open_question:
        lines += ["", "## Open question", "", open_question.strip()]
    if decisions.strip():
        lines += ["", "## Decisions so far", "", decisions.strip()]
    if log_tail.strip():
        lines += ["", "## Last log lines", "", "```", log_tail.strip(), "```"]
    return "\n".join(lines) + "\n"
