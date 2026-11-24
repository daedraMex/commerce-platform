"""The factory moves its own checkout to origin/main before every run (#215).

The factory runs from ``/srv/factory/repo`` but only ever fetched there, for the
ticket worktrees. On 2026-11-24 that checkout was 48 commits behind, so none of
the factory fixes merged after #190 were running, and nothing said so.

Before anything else, every run (hourly and ``factory preflight``) fetches
``origin/main``. When the checkout is behind, on ``main`` and clean, it
fast-forwards, runs ``uv sync`` and re-executes the same command, so the run uses
the code it just pulled. Anything else (local changes, another branch, a
diverged history, a failed sync) stops the run with the reason; the factory never
resets or discards anything there.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
from pathlib import Path

from .shell import RunCommand, run_command

# Set on re-exec to the commit just pulled, so the new process never updates twice.
REEXEC_ENV = "FACTORY_SELF_UPDATED"
UV_BIN = "uv"


@dataclass(frozen=True)
class UpdateOutcome:
    status: str  # "current", "updated" or "blocked"
    head: str = ""
    reason: str = ""


def _short(sha: str) -> str:
    return sha[:7]


def _said(result) -> str:
    return " ".join((result.stderr or result.stdout).split())[:300] or f"exit {result.exit_code}"


class SelfUpdate:
    def __init__(
        self,
        *,
        repo_dir: Path,
        tools_dir: Path,
        run: RunCommand = run_command,
        env: MutableMapping[str, str] | None = None,
        execv: Callable[[str, list[str]], None] = os.execv,
        command: list[str] | None = None,
    ):
        self.repo_dir = repo_dir
        self.tools_dir = tools_dir
        self._run = run
        self._env = os.environ if env is None else env
        self._execv = execv
        # The venv's Python running the same subcommand: independent of how the
        # process was started (`uv run factory`, the console script, a path).
        self._command = command or [sys.executable, "-m", "factory.main", *sys.argv[1:]]

    def _git(self, *args: str):
        return self._run(["git", *args], str(self.repo_dir), timeout=300)

    def _rev(self, ref: str) -> str:
        return self._git("rev-parse", ref).stdout.strip()

    def head(self) -> str:
        """The commit the checkout is on, without fetching or changing anything."""
        return self._rev("HEAD")

    def run(self) -> UpdateOutcome:
        """Move the checkout to origin/main if it is safe; re-exec when it moved."""
        head = self.head()
        if self._env.get(REEXEC_ENV):
            # The process that pulled this code just fetched and synced.
            return UpdateOutcome("current", head=head)
        fetched = self._git("fetch", "origin", "main")
        if fetched.exit_code != 0:
            return UpdateOutcome("blocked", head=head, reason=f"git fetch failed: {_said(fetched)}")
        target = self._rev("origin/main")
        if head == target:
            return UpdateOutcome("current", head=head)
        moving = f"{_short(head)} -> {_short(target)}"
        branch = self._git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        if branch != "main":
            return self._blocked(head, f"the checkout is not on main (on {branch}), {moving}")
        if self._git("status", "--porcelain").stdout.strip():
            return self._blocked(head, f"the checkout has local changes, {moving}")
        if self._git("merge-base", "--is-ancestor", "HEAD", "origin/main").exit_code != 0:
            return self._blocked(head, f"the checkout has diverged from origin/main, {moving}")
        merged = self._git("merge", "--ff-only", "origin/main")
        if merged.exit_code != 0:
            return self._blocked(head, f"fast-forward failed, {moving}: {_said(merged)}")
        # --locked: a stale uv.lock fails here instead of being rewritten, which
        # would leave "local changes" and stop every later run.
        synced = self._run(
            [UV_BIN, "sync", "--locked", "--quiet"], str(self.tools_dir), timeout=600
        )
        if synced.exit_code != 0:
            return self._blocked(target, f"uv sync failed after {moving}: {_said(synced)}")
        self._env[REEXEC_ENV] = target
        print(f"self-update {moving}", file=sys.stderr, flush=True)  # the journal's record
        self._execv(self._command[0], self._command)
        return UpdateOutcome("updated", head=target)

    def _blocked(self, head: str, reason: str) -> UpdateOutcome:
        return UpdateOutcome(
            "blocked",
            head=head,
            reason=f"self-update stopped: {reason}. Fix /srv/factory/repo by hand "
            "(docs/factory.md, Updating the factory).",
        )
