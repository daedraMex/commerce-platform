"""Remember whether the factory is paused, so each pause is announced once.

The marker lives in the factory's state directory. It is written before the
Telegram message and cleared as soon as a run is not paused, so the next pause
is a new transition and sends a new message.
"""

from __future__ import annotations

import os
from pathlib import Path

PAUSE_FILE = "paused"


class PauseState:
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.path = state_dir / PAUSE_FILE

    def enter(self, reason: str) -> bool:
        """Mark paused; return True only on the transition into paused."""
        if self.path.exists():
            return False
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.state_dir, 0o700)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(reason + "\n")
        return True

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
