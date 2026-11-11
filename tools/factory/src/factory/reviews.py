"""Review feedback the factory can address on its own pull requests.

Only the repository owner can ask the factory to revisit a pull request. The
review body and its inline comments are untrusted data: they describe what to
change and are never treated as instructions to the runner.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .tickets import Ticket

CHANGES_REQUESTED = "CHANGES_REQUESTED"


@dataclass(frozen=True)
class ReviewComment:
    """One inline review comment: a file, a line (when known) and its text."""

    path: str
    line: int | None
    body: str


@dataclass(frozen=True)
class ReviewFix:
    """A pull request whose latest owner review asks for changes."""

    review_id: str
    pr_number: int
    branch: str
    ticket: Ticket
    review_body: str
    comments: tuple[ReviewComment, ...]
    submitted_at: datetime
