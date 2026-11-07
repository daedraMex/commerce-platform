"""Diff inspection: what a run changed, distilled for a PR and a notification."""

from __future__ import annotations

from dataclasses import dataclass


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
