"""Ticket selection.

A ticket is runnable when it is labeled ``ready-for-agent``, has no open
blocker, has no open pull request and is not waiting on a human decision
(``needs-decision``). Tickets are taken oldest first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .models import STRONG_MODEL_LABEL

READY_LABEL = "ready-for-agent"
NEEDS_DECISION_LABEL = "needs-decision"
# A ticket the owner allowed to change dependency manifests and lockfiles; the PR
# gets the same label so the owner sees it in the list.
DEPS_CHANGE_LABEL = "deps-change"
MIGRATION_LABEL = "migration"
# Every label the factory reads or writes. The preflight checks they exist, because
# gh cannot add a label the repo does not have (#160).
REQUIRED_LABELS = frozenset(
    {READY_LABEL, NEEDS_DECISION_LABEL, STRONG_MODEL_LABEL, DEPS_CHANGE_LABEL, MIGRATION_LABEL}
)

_BLOCKED_BY_RE = re.compile(r"^\s*Blocked by:\s*(.+?)\s*$", re.IGNORECASE)
_CONTRACTS_HEADING_RE = re.compile(r"^#{2,3}\s*Contracts\s*$", re.IGNORECASE | re.MULTILINE)
_NEXT_HEADING_RE = re.compile(r"^#{1,6}\s", re.MULTILINE)
_CONTRACTS_LINE_RE = re.compile(r"^\s*\**Contracts:\**\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
# Only backticked ids count, so a path such as `docs/contracts/photos.md` is never an id.
_CONTRACT_ID_RE = re.compile(r"`([a-z][a-z0-9_]*\.[a-z0-9][a-z0-9_-]*)`")
_VERBS = {"defines": "held", "changes": "held", "consumes": "consumed"}


@dataclass(frozen=True)
class Contracts:
    """The contract ids a ticket declares (ADR-0031).

    ``held`` are the ones it defines or changes; ``consumed`` the ones it relies on.
    """

    held: frozenset[str] = frozenset()
    consumed: frozenset[str] = frozenset()

    def conflicts_with(self, other: Contracts) -> frozenset[str]:
        """Shared ids where at least one side defines or changes the contract."""
        return (self.held & (other.held | other.consumed)) | (self.consumed & other.held)


def parse_contracts(body: str) -> Contracts:
    """Read a ticket's Contracts section (or ``Contracts:`` line), by verb.

    An id in a clause with no verb counts as held, so an unclear section blocks
    rather than lets two tickets race on one contract.
    """
    text = _contracts_text(body)
    held: set[str] = set()
    consumed: set[str] = set()
    verb = "held"
    for clause in text.split(";"):
        words = clause.strip().lstrip("*_").split(maxsplit=1)
        if words and words[0].lower() in _VERBS:
            verb = _VERBS[words[0].lower()]
        target = held if verb == "held" else consumed
        target.update(_CONTRACT_ID_RE.findall(clause))
    return Contracts(held=frozenset(held), consumed=frozenset(consumed - held))


def _contracts_text(body: str) -> str:
    heading = _CONTRACTS_HEADING_RE.search(body)
    if heading is not None:
        rest = body[heading.end() :]
        following = _NEXT_HEADING_RE.search(rest)
        return rest if following is None else rest[: following.start()]
    line = _CONTRACTS_LINE_RE.search(body)
    return "" if line is None else line.group(1)


@dataclass(frozen=True)
class Ticket:
    """A GitHub issue as the factory sees it, already resolved by the GitHub port."""

    number: int
    title: str
    body: str = ""
    labels: frozenset[str] = field(default_factory=frozenset)
    blocked_by: tuple[int, ...] = ()
    has_open_pr: bool = False
    # One line per contract an open pull request holds against this ticket (#144).
    contract_conflicts: tuple[str, ...] = ()


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
    if ticket.contract_conflicts:
        return False
    return True


def select_tickets(tickets: list[Ticket], *, max_tickets: int) -> list[Ticket]:
    """The oldest ready tickets, never two that conflict on a contract (ADR-0031)."""
    selected: list[Ticket] = []
    for ticket in sorted((t for t in tickets if is_ready(t)), key=lambda t: t.number):
        if len(selected) >= max_tickets:
            break
        contracts = parse_contracts(ticket.body)
        if any(contracts.conflicts_with(parse_contracts(s.body)) for s in selected):
            continue
        selected.append(ticket)
    return selected


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
