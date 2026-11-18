"""Diff inspection: what a run changed, distilled for a PR and a notification."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import PurePosixPath

PROTECTED_PREFIXES = (
    ".github/",
    "tools/factory/",
    "backend/scripts/",
    # Architecture tests are guards written from agent mistakes (#165).
    "backend/tests/architecture/",
    "web/console/scripts/",
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
# Protected wherever they live: test fixtures run with every check, and backend check
# configuration that outranks pyproject.toml (pytest 9 reads pytest.toml, .pytest.toml,
# pytest.ini, .pytest.ini, tox.ini and setup.cfg before [tool.pytest]; a ruff.toml
# overrides [tool.ruff] for its directory). No ticket needs them, so no label unlocks
# them (#160). .importlinter holds import contracts, which are guards (#165).
PROTECTED_NAMES = frozenset(
    {
        "conftest.py",
        ".importlinter",
        "pytest.toml",
        ".pytest.toml",
        "pytest.ini",
        ".pytest.ini",
        "setup.cfg",
        "tox.ini",
        "ruff.toml",
        ".ruff.toml",
    }
)
# Lint configuration, protected wherever it lives: lint rules are where an agent's
# recurring mistake becomes a guard, so only the owner may change them (#160).
PROTECTED_NAME_PATTERNS = ("eslint.config.*", ".eslintrc*")
# Dependency manifests and lockfiles: protected unless the ticket is labeled
# ``deps-change``, so a new dependency is always a decision the owner made.
DEPENDENCY_NAMES = frozenset({"package.json", "pnpm-lock.yaml", "pyproject.toml", "uv.lock"})

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

# Console check configuration: a ticket may change it (a new test folder, a path alias),
# but it decides which files the checks see, so the PR body flags it under Risk (#160).
CHECK_CONFIG_NAME_PATTERNS = (
    "vitest.config.*",
    "vitest.workspace.*",
    "playwright*.config.*",
    "tsconfig*.json",
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


def is_dependency_path(path: str) -> bool:
    """A dependency manifest or lockfile, anywhere in the repo."""
    return PurePosixPath(path.replace("\\", "/")).name in DEPENDENCY_NAMES


LOCKFILE_NAMES = frozenset({"pnpm-lock.yaml", "uv.lock"})
# Sections a deps-change ticket may change; anything else in the manifest (package
# "scripts", [tool.pytest], [tool.ruff]) changes what the checks run.
PACKAGE_JSON_DEPENDENCY_KEYS = frozenset(
    {"dependencies", "devDependencies", "optionalDependencies", "peerDependencies", "pnpm"}
)


def _without_pyproject_dependencies(data: dict) -> dict:
    data = dict(data)
    data.pop("dependency-groups", None)
    project = dict(data.get("project", {}))
    project.pop("dependencies", None)
    project.pop("optional-dependencies", None)
    if project or "project" in data:
        data["project"] = project
    tool = dict(data.get("tool", {}))
    uv = dict(tool.get("uv", {}))
    uv.pop("sources", None)
    uv.pop("dev-dependencies", None)
    if "uv" in tool:
        tool["uv"] = uv
    if tool or "tool" in data:
        data["tool"] = tool
    return data


def non_dependency_change(path: str, old: str | None, new: str | None) -> str | None:
    """Why a dependency file changed beyond its dependency sections, or None.

    Lockfiles only list resolved dependencies. A manifest may change only its
    dependency sections; a new, deleted or unreadable manifest is never dependency-only.
    """
    name = PurePosixPath(path.replace("\\", "/")).name
    if name in LOCKFILE_NAMES:
        return None
    if old is None or new is None:
        return f"{path} was added or deleted"
    try:
        if name == "package.json":
            before, after = json.loads(old), json.loads(new)
            keys = sorted(
                key
                for key in set(before) | set(after)
                if key not in PACKAGE_JSON_DEPENDENCY_KEYS and before.get(key) != after.get(key)
            )
        else:
            before = _without_pyproject_dependencies(tomllib.loads(old))
            after = _without_pyproject_dependencies(tomllib.loads(new))
            keys = sorted(
                key for key in set(before) | set(after) if before.get(key) != after.get(key)
            )
    except (ValueError, tomllib.TOMLDecodeError) as exc:
        return f"{path} could not be parsed ({type(exc).__name__})"
    return f"{path} changed {', '.join(keys)}" if keys else None


def is_protected_path(path: str, *, allow_dependencies: bool = False) -> bool:
    """Paths the agent must never change on an unattended run.

    ``allow_dependencies`` (a ``deps-change`` ticket) unlocks only dependency
    files outside the protected prefixes; the factory's own lockfiles stay locked.
    """
    normalized = path.replace("\\", "/")
    if normalized in PROTECTED_FILES:
        return True
    if any(normalized.startswith(prefix) for prefix in PROTECTED_PREFIXES):
        return True
    name = PurePosixPath(normalized).name
    if name in PROTECTED_NAMES:
        return True
    if any(fnmatchcase(name, pattern) for pattern in PROTECTED_NAME_PATTERNS):
        return True
    if name in DEPENDENCY_NAMES and not allow_dependencies:
        return True
    return name.startswith("opencode") and name.endswith((".json", ".jsonc"))


def is_check_config_path(path: str) -> bool:
    """Console check configuration, anywhere in the repo: flagged, never protected."""
    name = PurePosixPath(path.replace("\\", "/")).name
    return any(fnmatchcase(name, pattern) for pattern in CHECK_CONFIG_NAME_PATTERNS)


def is_sensitive_path(path: str) -> bool:
    """Paths an unattended run may change but the owner should read in full."""
    normalized = path.replace("\\", "/")
    return any(normalized.startswith(prefix) for prefix in SENSITIVE_PREFIXES)


def touches_protected_paths(paths, *, allow_dependencies: bool = False) -> bool:
    return any(is_protected_path(path, allow_dependencies=allow_dependencies) for path in paths)


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
