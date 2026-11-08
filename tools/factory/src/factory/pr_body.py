"""Draft pull request body."""

from __future__ import annotations


def build_pr_body(*, ticket_number: int, summary: str, model: str, decisions: str) -> str:
    parts: list[str] = [
        f"Closes #{ticket_number}",
        "",
        "## Summary",
        "",
        summary.strip(),
    ]
    if model:
        parts += ["", f"Model: {model}"]
    if decisions.strip():
        parts += ["", "## Decisions", "", decisions.strip()]
    return "\n".join(parts) + "\n"
