"""Diff inspection: what a run changed, distilled for a PR and a notification."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

PROTECTED_PREFIXES = (
    ".github/",
    "tools/factory/",
    "backend/scripts/",
    ".opencode/",
)
PROTECTED_FILES = frozenset(
    {
        "AGENTS.md",
        "CLAUDE.md",
        "REVIEW.md",
        ".pre-commit-config.yaml",
    }
)

# Paths whose changes the PR body flags under Risk so the owner reads them in full:
# authentication, store permissions and credentials, the shared ports (Authorizer,
# CredentialStore), the project config and wiring, and the console session.
SENSITIVE_PREFIXES = (
    "backend/apps/accounts/",
    "backend/apps/stores/",
    "backend/apps/shared/",
    "backend/config/",
    "web/console/src/lib/auth/",
)


@dataclass(frozen=True)
class FileChange:
    path: str
    added: int
    deleted: int


@dataclass(frozen=True)
class DiffStats:
    files: tuple[FileChange, ...] = ()
    new_tests: tuple[str, ...] = ()
    migrations_changed: bool = False

    @property
    def added(self) -> int:
        return sum(f.added for f in self.files)

    @property
    def deleted(self) -> int:
        return sum(f.deleted for f in self.files)


def is_migration_path(path: str) -> bool:
    return "/migrations/" in path and path.endswith(".py")


def is_test_path(path: str) -> bool:
    return "tests/" in path and path.endswith(".py")


def is_protected_path(path: str) -> bool:
    """Paths the agent must never change on an unattended run."""
    normalized = path.replace("\\", "/")
    if normalized in PROTECTED_FILES:
        return True
    if any(normalized.startswith(prefix) for prefix in PROTECTED_PREFIXES):
        return True
    name = PurePosixPath(normalized).name
    return name.startswith("opencode") and name.endswith(".json")


def is_sensitive_path(path: str) -> bool:
    """Paths an unattended run may change but the owner should read in full."""
    normalized = path.replace("\\", "/")
    return any(normalized.startswith(prefix) for prefix in SENSITIVE_PREFIXES)


def touches_protected_paths(paths) -> bool:
    return any(is_protected_path(path) for path in paths)


def build_diff_stats(numstat: str, new_files: list[str]) -> DiffStats:
    """Build a ``DiffStats`` from ``git diff --numstat`` output and newly added files."""
    files: list[FileChange] = []
    for line in numstat.splitlines():
        if not line.strip():
            continue
        added_s, deleted_s, path = line.split("\t", 2)
        files.append(
            FileChange(
                path=path,
                added=_count(added_s),
                deleted=_count(deleted_s),
            )
        )
    new_tests = tuple(sorted(f for f in new_files if is_test_path(f)))
    migrations_changed = any(is_migration_path(f.path) for f in files)
    return DiffStats(files=tuple(files), new_tests=new_tests, migrations_changed=migrations_changed)


def _count(token: str) -> int:
    return 0 if token == "-" else int(token)
