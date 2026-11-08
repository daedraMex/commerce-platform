"""Housekeeping: drop worktrees and logs older than the retention window."""

from __future__ import annotations

import shutil
import time
from pathlib import Path


def iter_expired(paths: list[Path], *, now: float, keep_days: int) -> list[Path]:
    cutoff = now - keep_days * 86400
    return [p for p in paths if p.stat().st_mtime < cutoff]


def cleanup_old(directory: Path, *, now: float | None = None, keep_days: int) -> None:
    if not directory.exists():
        return
    now = time.time() if now is None else now
    for entry in directory.iterdir():
        try:
            if entry.stat().st_mtime < now - keep_days * 86400:
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
        except FileNotFoundError:
            continue
