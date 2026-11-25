"""One factory run at a time (#233).

The hourly run and a manual ``factory preflight`` both clean preflight worktrees
and kill every agent process, so two of them at once break each other: on
2026-11-25 a manual preflight removed the hourly run's worktree and killed its
checks. Each run takes an exclusive ``flock`` on ``state/run.lock`` before the
self-update; a second run stops at once and names the holder. The kernel drops
the lock when the process dies, so it can never stay stuck. The self-update's
``os.execv`` keeps it: the descriptor is inheritable and its number travels in
``FACTORY_RUN_LOCK_FD``, which is trusted only when it is that same file and
already holds the lock.
"""

from __future__ import annotations

import fcntl
import os
from collections.abc import MutableMapping
from datetime import UTC, datetime
from pathlib import Path

LOCK_ENV = "FACTORY_RUN_LOCK_FD"


class RunLocked(RuntimeError):
    """Another factory run holds the lock."""


def acquire_run_lock(
    path: str | Path,
    *,
    env: MutableMapping[str, str] = os.environ,
    command: str,
    now: str | None = None,
) -> int:
    """Hold the run lock for the rest of this process; return its descriptor."""
    path = Path(path)
    inherited = _inherited(path, env.get(LOCK_ENV))
    if inherited is not None:
        return inherited
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        holder = os.pread(fd, 200, 0).decode(errors="replace").strip() or "another run"
        os.close(fd)
        raise RunLocked(f"another factory run is in progress: {holder}") from None
    stamp = now or datetime.now(UTC).isoformat(timespec="seconds")
    os.ftruncate(fd, 0)
    os.pwrite(fd, f"pid {os.getpid()}, {command} since {stamp}\n".encode(), 0)
    os.set_inheritable(fd, True)
    env[LOCK_ENV] = str(fd)
    return fd


def _inherited(path: Path, value: str | None) -> int | None:
    """The inherited descriptor, only if it is this lock file and holds the lock."""
    if not value or not value.isdigit():
        return None
    fd = int(value)
    try:
        held = os.fstat(fd)
        current = os.stat(path, follow_symlinks=False)
    except OSError:
        return None
    if (held.st_dev, held.st_ino) != (current.st_dev, current.st_ino):
        return None
    try:
        # Re-locking the same open file description succeeds; a fresh one would not.
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return None
    return fd
