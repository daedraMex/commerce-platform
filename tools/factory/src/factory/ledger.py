"""Append-only ledger of ticket attempts, counted in Mexico City time.

A ``started`` line is written before the agent runs, then an outcome line after
it finishes. The daily cap counts only ``started`` lines whose date is today in
America/Mexico_City, so a run killed by systemd, a reboot or SIGTERM still
consumes daily budget. The file lives in the factory's state directory, which
the agent user cannot read.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

MEXICO_CITY = ZoneInfo("America/Mexico_City")
LEDGER_FILE = "attempts.log"
STARTED = "started"


def _now() -> datetime:
    return datetime.now(MEXICO_CITY)


class AttemptLedger:
    def __init__(
        self,
        state_dir: Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        self.state_dir = state_dir
        self.path = state_dir / LEDGER_FILE
        self._clock = clock or _now

    def now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=MEXICO_CITY)
        return now.astimezone(MEXICO_CITY)

    def count_today(self) -> int:
        """How many attempts started today, success or failure alike."""
        today = self.now().date()
        if not self.path.exists():
            return 0
        count = 0
        for line in self.path.read_text().splitlines():
            fields = _parse_line(line)
            if fields is not None and fields[2] == STARTED and fields[0].date() == today:
                count += 1
        return count

    def record_started(self, ticket_number: int, *, started_at: datetime) -> None:
        self._append(ticket_number, STARTED, at=started_at)

    def record_outcome(self, ticket_number: int, outcome: str, *, finished_at: datetime) -> None:
        self._append(ticket_number, outcome, at=finished_at)

    def _append(self, ticket_number: int, outcome: str, *, at: datetime) -> None:
        timestamp = at
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=MEXICO_CITY)
        line = f"{timestamp.astimezone(MEXICO_CITY).isoformat()}\t#{ticket_number}\t{outcome}\n"
        self._ensure_state_dir()
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            handle.write(line)

    def _ensure_state_dir(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.state_dir, 0o700)


def _parse_line(line: str) -> tuple[datetime, str, str] | None:
    parts = line.split("\t")
    if len(parts) < 3:
        return None
    try:
        started = datetime.fromisoformat(parts[0])
    except ValueError:
        return None
    if started.tzinfo is None:
        return None
    return started.astimezone(MEXICO_CITY), parts[1], parts[2]
