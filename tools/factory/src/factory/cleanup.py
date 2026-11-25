"""Housekeeping: drop worktrees and logs older than the retention window."""

from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from pathlib import Path


def iter_expired(paths: list[Path], *, now: float, keep_days: int) -> list[Path]:
    cutoff = now - keep_days * 86400
    return [p for p in paths if p.stat().st_mtime < cutoff]


def cleanup_old(
    directory: Path,
    *,
    now: float | None = None,
    keep_days: int,
    remove_dir: Callable[[Path], None] | None = None,
) -> None:
    """Drop entries older than ``keep_days``.

    Expired directories are handed to ``remove_dir`` when given, so the factory
    can delete agent-owned worktrees as their owner; otherwise they are removed
    with ``shutil.rmtree``. Errors from ``remove_dir`` propagate so a failed
    cleanup is loud.
    """
    if not directory.exists():
        return
    now = time.time() if now is None else now
    for entry in directory.iterdir():
        try:
            if entry.stat().st_mtime < now - keep_days * 86400:
                if entry.is_dir():
                    if remove_dir is None:
                        shutil.rmtree(entry)
                    else:
                        remove_dir(entry)
                else:
                    entry.unlink()
        except FileNotFoundError:
            continue
