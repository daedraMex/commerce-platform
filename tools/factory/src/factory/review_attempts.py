"""Append-only ledger of review ids the factory has already attempted.

A review is never retried automatically, whatever the outcome. A new review on
the same pull request has a new id, so it is still picked up. The file lives in
the factory's state directory, which the agent user cannot read.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

MEXICO_CITY = ZoneInfo("America/Mexico_City")
REVIEW_ATTEMPTS_FILE = "review-attempts.log"


def _now() -> datetime:
    return datetime.now(MEXICO_CITY)


class ReviewAttemptLedger:
    def __init__(
        self,
        state_dir: Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        self.state_dir = state_dir
        self.path = state_dir / REVIEW_ATTEMPTS_FILE
        self._clock = clock or _now

    def attempted_ids(self) -> set[str]:
        """Every review id already attempted, successful or stuck."""
        if not self.path.exists():
            return set()
        ids: set[str] = set()
        for line in self.path.read_text().splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[1].strip():
                ids.add(parts[1].strip())
        return ids

    def record_attempted(self, review_id: str) -> None:
        timestamp = self._clock()
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=MEXICO_CITY)
        line = f"{timestamp.astimezone(MEXICO_CITY).isoformat()}\t{review_id}\n"
        self._ensure_state_dir()
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            handle.write(line)

    def _ensure_state_dir(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.state_dir, 0o700)
