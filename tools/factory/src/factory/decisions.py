"""Decision log: the DECISIONS.md the agent maintains in the worktree.

``DECISIONS.md`` is git-ignored and never committed. It has two sections —
``# Summary`` and ``# Decisions`` — and, when the agent cannot decide safely,
an ``OPEN QUESTION:`` line as its very first line.
"""

from __future__ import annotations

OPEN_QUESTION_PREFIX = "OPEN QUESTION:"
DECISIONS_HEADER = "# Summary\n\n\n# Decisions\n\n"


def extract_open_question(decisions: str) -> str | None:
    """Return the open question if the agent wrote one at the top of DECISIONS.md."""
    lines = decisions.strip().splitlines()
    if not lines:
        return None
    first = lines[0].strip()
    if first.upper().startswith(OPEN_QUESTION_PREFIX):
        return first[len(OPEN_QUESTION_PREFIX) :].strip() or None
    return None


def extract_summary(decisions: str) -> str:
    """The text under the ``# Summary`` heading."""
    return _section(decisions, "# summary")


def extract_decisions(decisions: str) -> str:
    """The text under the ``# Decisions`` heading."""
    return _section(decisions, "# decisions")


def _section(decisions: str, heading: str) -> str:
    capture = False
    out: list[str] = []
    for line in decisions.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            capture = stripped.lower().startswith(heading.lower())
            continue
        if capture:
            out.append(line)
    return "\n".join(out).strip()
