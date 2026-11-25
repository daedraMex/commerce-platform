"""Deleting worktrees as their owner, and proving it works (sudo rm, the probe)."""

from __future__ import annotations

from pathlib import Path

from .runner import (
    ensure_agent_cleanup,
)
from .shell import RunCommand, run_command

RM_BIN = "/usr/bin/rm"

PREFLIGHT_PREFIX = "preflight-"

CLEANUP_PROBE_RELATIVE = Path("backend") / ".cleanup-probe"

# Root-owned copy of tools/factory/scripts/cleanup-probe; the preflight checks it
# matches the repo copy (#140).
CLEANUP_PROBE_PATH = Path("/usr/local/lib/factory/cleanup-probe")

CLEANUP_PROBE_REPO_RELATIVE = Path("tools") / "factory" / "scripts" / "cleanup-probe"


class WorktreeCleanupError(RuntimeError):
    """Raised when a worktree or branch cannot be cleaned up."""


def worktree_cleanup_path(worktrees_dir: Path, worktree: Path) -> Path:
    """Return the resolved path, refusing anything but a direct child.

    The sudoers rule only allows ``rm -rf`` on direct children of the
    worktrees directory; this check mirrors that rule in code so a bad path
    never reaches sudo.
    """
    if ".." in worktree.parts:
        raise WorktreeCleanupError(f"refusing to remove {worktree}: path contains '..'.")
    try:
        base = worktrees_dir.resolve()
        target = worktree.resolve()
    except OSError as exc:
        raise WorktreeCleanupError(f"could not resolve worktree path {worktree}: {exc}") from exc
    if target == base or target.parent != base:
        raise WorktreeCleanupError(
            f"refusing to remove {target}: it is not a direct child of {base}."
        )
    return target


class WorktreeCleanup:
    """Remove worktrees the agent wrote into, as the agent, and prove it can."""

    def __init__(self, run: RunCommand = run_command, *, agent_user: str | None = None):
        self._run = run
        self._agent_user = agent_user

    def preflight_leftovers(self, worktrees_dir: Path) -> list[Path]:
        """Entries an earlier preflight left behind, live or not.

        Preflight worktrees are throwaway by name, so a leftover is never
        evidence anyone needs; ticket worktrees (``nf-*``) are, and are not listed.
        """
        if not worktrees_dir.exists():
            return []
        return sorted(
            entry for entry in worktrees_dir.iterdir() if entry.name.startswith(PREFLIGHT_PREFIX)
        )

    def create_agent_cleanup_probe(self, worktree: Path) -> Path:
        """Create an agent-owned 0770 directory inside ``worktree``.

        The root-owned ``cleanup-probe`` script runs as the agent: it creates the
        probe in a temp dir (so its group is ``factory-agent``, not the
        worktree's setgid group) and renames it into the worktree, exactly like
        pytest's cache. It never touches the worktree's check scripts (#140).
        """
        if not self._agent_user:
            raise WorktreeCleanupError(
                "FACTORY_AGENT_USER is not set; cannot create the cleanup probe as the agent."
            )
        probe_dir = worktree / CLEANUP_PROBE_RELATIVE
        result = self._run(
            ["sudo", "-n", "-u", self._agent_user, "--", str(CLEANUP_PROBE_PATH), str(worktree)],
            cwd="/",
            timeout=120,
        )
        if result.exit_code != 0:
            raise WorktreeCleanupError(
                f"could not create the cleanup probe at {probe_dir}: "
                f"{result.stderr.strip() or result.exit_code}"
            )
        return probe_dir

    def remove_worktree(self, repo_dir: Path, worktree: Path, worktrees_dir: Path) -> None:
        """Delete the worktree as its owner, then prune git's metadata.

        The agent creates files with modes the factory cannot remove, so the
        contents are deleted by ``factory-agent`` via the sudoers-allowed
        ``rm -rf`` rule, restricted to a direct child of ``worktrees_dir``.
        """
        if not self._agent_user:
            raise WorktreeCleanupError(
                "FACTORY_AGENT_USER is not set; cannot delete the worktree as its owner."
            )
        target = worktree_cleanup_path(worktrees_dir, worktree)
        # An agent process still writing (uv filling .venv after an interrupted
        # check) makes rm fail half-way and leaves a worktree git no longer
        # knows (#194). Strict: a refused cleanup raises before anything is deleted.
        ensure_agent_cleanup(self._run, self._agent_user)
        result = self._run(
            ["sudo", "-n", "-u", self._agent_user, "--", RM_BIN, "-rf", str(target)],
            cwd="/",
            timeout=300,
        )
        if result.exit_code != 0:
            raise WorktreeCleanupError(
                f"could not delete worktree {target} as {self._agent_user}: "
                f"{result.stderr.strip() or result.exit_code}"
            )
        pruned = self._run(["git", "worktree", "prune"], str(repo_dir), timeout=120)
        if pruned.exit_code != 0:
            raise WorktreeCleanupError(
                f"git worktree prune failed after deleting {target}: "
                f"{pruned.stderr.strip() or pruned.exit_code}"
            )
