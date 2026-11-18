"""Tickets held out of runs until their ``needs-decision`` label lands.

The stuck flow writes the hold before any GitHub call and drops it once the label
is on the ticket. If commenting or labeling fails, the ticket still looks ready in
GitHub, so without the hold the next run would pick it again (#160). Each run
retries the label first. The file lives in the factory's state directory, which
the agent user cannot read.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

LABEL_HOLDS_FILE = "label-holds.log"
_LINE_RE = re.compile(r"^#(\d+)$")


class LabelHolds:
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.path = state_dir / LABEL_HOLDS_FILE

    def numbers(self) -> frozenset[int]:
        if not self.path.exists():
            return frozenset()
        numbers = set()
        for line in self.path.read_text().splitlines():
            match = _LINE_RE.match(line.strip())
            if match:
                numbers.add(int(match.group(1)))
        return frozenset(numbers)

    def add(self, ticket_number: int) -> None:
        self._write(self.numbers() | {ticket_number})

    def remove(self, ticket_number: int) -> None:
        self._write(self.numbers() - {ticket_number})

    def _write(self, numbers: frozenset[int]) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.state_dir, 0o700)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.writelines(f"#{number}\n" for number in sorted(numbers))
        os.replace(tmp, self.path)
