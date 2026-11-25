"""The installed cleanup-probe script must be the repo's, root-owned (#140).

The preflight runs ``/usr/local/lib/factory/cleanup-probe`` as the agent. The
self-update brings a new repo copy but cannot install it (that needs root), so
a changed script stops the preflight with the exact command to install it.
"""

from __future__ import annotations

import hashlib
import stat
from pathlib import Path


class CleanupProbeError(RuntimeError):
    """Raised when the installed cleanup probe cannot be trusted."""


def verify_cleanup_probe(installed: Path, repo_copy: Path, *, owner_uid: int = 0) -> None:
    install = f"sudo install -D -o root -g root -m 0755 {repo_copy} {installed}"
    try:
        expected = hashlib.sha256(repo_copy.read_bytes()).hexdigest()
    except OSError as exc:
        raise CleanupProbeError(f"cannot read the repo copy {repo_copy}: {exc}") from exc
    try:
        info = installed.lstat()
    except FileNotFoundError:
        raise CleanupProbeError(f"{installed} is not installed; as admin: {install}") from None
    if stat.S_ISLNK(info.st_mode):
        raise CleanupProbeError(f"{installed} is a symlink; as admin: {install}")
    if info.st_uid != owner_uid:
        raise CleanupProbeError(f"{installed} must be owned by root; as admin: {install}")
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise CleanupProbeError(f"{installed} is group- or world-writable; as admin: {install}")
    actual = hashlib.sha256(installed.read_bytes()).hexdigest()
    if actual != expected:
        raise CleanupProbeError(f"{installed} differs from the repo copy; as admin: {install}")
