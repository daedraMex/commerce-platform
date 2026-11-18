"""Ticket selection.

A ticket is runnable when it is labeled ``ready-for-agent``, has no open
blocker, has no open pull request and is not waiting on a human decision
(``needs-decision``). Tickets are taken oldest first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

READY_LABEL = "ready-for-agent"
NEEDS_DECISION_LABEL = "needs-decision"

_BLOCKED_BY_RE = re.compile(r"^\s*Blocked by:\s*(.+?)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Ticket:
    """A GitHub issue as the factory sees it, already resolved by the GitHub port."""

    number: int
    title: str
    body: str = ""
    labels: frozenset[str] = field(default_factory=frozenset)
    blocked_by: tuple[int, ...] = ()
    has_open_pr: bool = False


def branch_name(ticket: Ticket) -> str:
    """The branch the factory works on and pushes for a ticket."""
    return f"nf/{ticket.number}-{_slug(ticket.title)}"


class PushTargetError(RuntimeError):
    """The factory was about to push a branch that is not the ticket's own."""


def assert_push_target(branch: str, ticket: Ticket) -> None:
    """Allow a push only to the ticket's own factory branch, ``nf/<number>-<slug>``.

    New tickets push ``branch_name(ticket)``; review fixes push the PR's head, which
    the factory created for the same ticket (the slug may come from an older title).
    ADR-0025: the factory derives the branch from the ticket and never pushes any
    other branch.
    """
    # The slug is cut at 60 characters after stripping, so it can end in "-".
    if not re.fullmatch(rf"nf/{ticket.number}-[a-z0-9][a-z0-9-]*", branch):
        raise PushTargetError(
            f"refusing push target {branch!r}: not ticket #{ticket.number}'s factory branch"
        )


def worktree_dir_name(branch: str) -> str:
    """A flat directory name for a branch.

    Branch names contain a slash (``nf/46-slug``), but sudo's ``*`` does not
    cross ``/``, so a nested worktree would never match the sudoers check-script
    glob. Keep the branch unchanged and flatten it for the directory instead.
    """
    return branch.replace("/", "-")


def worktree_path(worktrees_dir: Path, branch: str) -> Path:
    """The worktree path: exactly one component under ``worktrees_dir``."""
    return worktrees_dir / worktree_dir_name(branch)


def branch_from_worktree_dir_name(name: str) -> str:
    """Recover a factory branch from its flat worktree directory name.

    Only the factory's own shapes are supported: ``nf/<n>-<slug>`` becomes
    ``nf-<n>-<slug>`` and ``preflight-<id>`` stays as-is.
    """
    if name.startswith("nf-"):
        return "nf/" + name[len("nf-") :]
    return name


def is_ready(ticket: Ticket) -> bool:
    if READY_LABEL not in ticket.labels:
        return False
    if NEEDS_DECISION_LABEL in ticket.labels:
        return False
    if ticket.has_open_pr:
        return False
    if ticket.blocked_by:
        return False
    return True


def select_tickets(tickets: list[Ticket], *, max_tickets: int) -> list[Ticket]:
    ready = sorted((t for t in tickets if is_ready(t)), key=lambda t: t.number)
    return ready[:max_tickets]


def parse_blocked_by(body: str) -> tuple[int, ...]:
    """Read the ``Blocked by: #n, #n`` fallback line from a ticket body."""
    for line in body.splitlines():
        match = _BLOCKED_BY_RE.match(line)
        if match:
            numbers = [int(n) for n in re.findall(r"#(\d+)", match.group(1))]
            return tuple(numbers)
    return ()


def _slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60] or "ticket"
