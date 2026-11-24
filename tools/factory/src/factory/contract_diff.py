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
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


class _Side:
    """Where one side of the diff (before or after the change) is in the file."""

    def __init__(self) -> None:
        self.section: str | None = None
        self.in_fence = False

    def read(self, text: str) -> None:
        if _FENCE_RE.match(text):
            self.in_fence = not self.in_fence
            return
        if self.in_fence:
            return  # a "## x.y" line inside a code block is not a heading
        heading = _HEADING_RE.match(text)
        if heading is not None:
            # A level-2 heading that is not a contract id (``## Notes``) ends the section.
            title = heading["title"]
            self.section = title if _ID_RE.match(title) else None


def touched_contract_ids(diff: str) -> frozenset[str]:
    """Every contract whose section has an added or removed line in ``diff``.

    Old and new sides are tracked apart: a removed line belongs to the section it
    sat in before the change, an added line to the one it sits in after it. Lines
    that are only whitespace change no contract: git shows the blank line before a
    section appended at the end of a file as an addition to the section above.
    """
    touched: set[str] = set()
    old = new = _Side()
    in_header = True
    for line in diff.splitlines():
        line = line.rstrip("\r")
        if line.startswith("diff --git"):
            old, new = _Side(), _Side()
            in_header = True
            continue
        if line.startswith("@@"):
            in_header = False  # file headers ("--- a/x", "+++ b/x") come only before
            continue
        if in_header or not line or line.startswith("\\"):
            continue
        mark, text = line[0], line[1:]
        sides = {" ": (old, new), "-": (old,), "+": (new,)}.get(mark, ())
        for side in sides:
            side.read(text)
            if mark != " " and text.strip() and side.section is not None:
                touched.add(side.section)
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
