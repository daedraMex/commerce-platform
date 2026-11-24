"""Which contracts a change edits, from its diff of ``docs/contracts/`` (#203).

A ticket's **Contracts** section is what the factory uses to keep two tickets off
the same contract (ADR-0031). On 2026-11-24 ticket #134 declared
``photos.catalog-port`` as consumed while its PR #195 changed it, so the conflict
check could not see the change. The PR body's Risk section and the reviewer
prompt now name every contract the diff edits that the ticket does not declare
as changed.

The diff is taken with the whole file as context, so every changed line has its
section heading (``## <module>.<name>``) above it in the same hunk.
"""

from __future__ import annotations

import re

from .tickets import Contracts

CONTRACTS_DIR = "docs/contracts/"
# Whole-file context: enough for any contract file to carry its headings.
CONTRACT_DIFF_CONTEXT = 100_000

_HEADING_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$")
_ID_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z0-9][a-z0-9_-]*$")
_FILE_HEADER_PREFIXES = (
    "diff --git",
    "index ",
    "--- ",
    "+++ ",
    "@@",
    "new file",
    "deleted file",
    "old mode",
    "new mode",
    "similarity",
    "rename ",
    "Binary files",
    "\\ No newline",
)


def _section(text: str, current: str | None) -> str | None:
    """The section a line opens, or ``current`` when it opens none.

    A level-2 heading that is not a contract id (``## Notes``) ends the section.
    """
    heading = _HEADING_RE.match(text)
    if heading is None:
        return current
    title = heading["title"]
    return title if _ID_RE.match(title) else None


def touched_contract_ids(diff: str) -> frozenset[str]:
    """Every contract whose section has an added or removed line in ``diff``.

    Old and new sides are tracked apart: a removed line belongs to the section it
    sat in before the change, an added line to the one it sits in after it.
    """
    touched: set[str] = set()
    old: str | None = None
    new: str | None = None
    for line in diff.splitlines():
        if line.startswith("diff --git"):
            old = new = None
            continue
        if not line or line.startswith(_FILE_HEADER_PREFIXES):
            continue
        mark, text = line[0], line[1:]
        if mark == " ":
            old = _section(text, old)
            new = _section(text, new)
        elif mark == "-":
            old = _section(text, old)
            if old is not None:
                touched.add(old)
        elif mark == "+":
            new = _section(text, new)
            if new is not None:
                touched.add(new)
    return frozenset(touched)


def undeclared_contracts(
    touched: frozenset[str], declared: Contracts
) -> tuple[tuple[str, str], ...]:
    """``(id, how the ticket named it)`` for each edited contract it does not hold."""
    return tuple(
        (
            contract_id,
            "declared as consumed" if contract_id in declared.consumed else "not declared",
        )
        for contract_id in sorted(touched - declared.held)
    )
