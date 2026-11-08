"""Compose the prompt handed to the agent for one ticket.

The prompt reuses the repo's ``/implement`` command file — the same source of
truth the manual path uses — and appends the night-factory overlay with the
extra rules that apply only to unattended runs.
"""

from __future__ import annotations

from .tickets import Ticket

ARGUMENTS_TOKEN = "$ARGUMENTS"

_OVERLAY_TOKENS = (
    "{{BRANCH}}",
    "{{MODEL}}",
    "{{MAX_ATTEMPTS}}",
)


def read_command_body(text: str) -> str:
    """Strip a command file's YAML frontmatter and return its body."""
    if text.lstrip().startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].strip()
    return text.strip()


def compose_prompt(
    ticket: Ticket,
    *,
    model: str,
    branch: str,
    max_attempts: int,
    command_template: str,
    overlay: str,
) -> str:
    arguments = f"#{ticket.number}: {ticket.title}\n\n{ticket.body}".strip()
    base = command_template.replace(ARGUMENTS_TOKEN, arguments)
    filled_overlay = overlay
    for token, value in zip(_OVERLAY_TOKENS, (branch, model, str(max_attempts)), strict=True):
        filled_overlay = filled_overlay.replace(token, value)
    return f"{base}\n\n{filled_overlay}".strip() + "\n"
