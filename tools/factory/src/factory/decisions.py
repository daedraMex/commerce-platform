"""Decision log: the DECISIONS.md the agent maintains in the worktree."""

from __future__ import annotations

OPEN_QUESTION_PREFIX = "OPEN QUESTION:"
DECISIONS_HEADER = "# Decisions\n\n"


def extract_open_question(decisions: str) -> str | None:
    """Return the open question if the agent wrote one at the top of DECISIONS.md."""
    lines = decisions.strip().splitlines()
    if not lines:
        return None
    first = lines[0].strip()
    if first.upper().startswith(OPEN_QUESTION_PREFIX):
        return first[len(OPEN_QUESTION_PREFIX) :].strip() or None
    return None
