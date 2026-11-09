"""Git operations in the worktree, wrapped around ``git`` and faked in tests."""

from __future__ import annotations

import os
import re
from pathlib import Path

from .diff import DiffStats, build_diff_stats
from .runner import build_check_env, sudo_argv, truncate_check_output
from .shell import RunCommand, run_command

MIN_GIT_VERSION = (2, 46)
_GIT_VERSION_RE = re.compile(r"git version (\d+)\.(\d+)(?:\.(\d+))?")


class GitVersionError(RuntimeError):
    """Raised when the installed git cannot honour the safe.directory glob."""


def parse_git_version(text: str) -> tuple[int, ...] | None:
    """Read ``git version X.Y[.Z]`` into a comparable tuple, or ``None``."""
    match = _GIT_VERSION_RE.search(text)
    if match is None:
        return None
    return tuple(int(part) for part in match.groups() if part is not None)


def verify_git_version(run: RunCommand = run_command) -> None:
    """Abort unless git >= 2.46 supports the ``safe.directory`` worktree glob."""
    result = run(["git", "--version"], cwd="/", timeout=60)
    version = parse_git_version(result.stdout + result.stderr)
    if result.exit_code != 0 or version is None:
        found = result.stderr.strip() or result.stdout.strip() or "unknown"
        raise GitVersionError(f"could not determine the git version: {found}")
    if version[:2] < MIN_GIT_VERSION:
        found = ".".join(str(part) for part in version)
        minimum = ".".join(str(part) for part in MIN_GIT_VERSION)
        raise GitVersionError(
            f"git >= {minimum} is required for the safe.directory worktree glob; "
            f"found {found}. Install it from ppa:git-core/ppa: "
            "sudo add-apt-repository ppa:git-core/ppa && sudo apt update && "
            "sudo apt install -y git"
        )


class Git:
    def __init__(
        self,
        run: RunCommand = run_command,
        *,
        agent_user: str | None = None,
        agent_home: str | None = None,
        base_env: dict[str, str] | None = None,
    ):
        self._run = run
        self._agent_user = agent_user
        self._agent_home = agent_home
        self._base_env = dict(base_env if base_env is not None else os.environ)

    def fetch_main(self, repo_dir: Path) -> None:
        result = self._run(["git", "fetch", "origin", "main"], str(repo_dir), timeout=300)
        if result.exit_code != 0:
            raise RuntimeError(f"git fetch failed: {result.stderr.strip()}")

    def worktree_exists(self, repo_dir: Path, worktree: Path) -> bool:
        result = self._run(["git", "worktree", "list", "--porcelain"], str(repo_dir), timeout=120)
        if result.exit_code != 0:
            return False
        target = f"worktree {worktree}"
        return any(line.strip() == target for line in result.stdout.splitlines())

    def branch_exists(self, repo_dir: Path, branch: str) -> bool:
        result = self._run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            str(repo_dir),
            timeout=120,
        )
        return result.exit_code == 0

    def create_worktree(self, repo_dir: Path, worktree: Path, branch: str) -> Path:
        result = self._run(
            ["git", "worktree", "add", "-b", branch, str(worktree), "origin/main"],
            str(repo_dir),
            timeout=300,
        )
        if result.exit_code != 0:
            raise RuntimeError(f"could not create worktree for {branch}: {result.stderr.strip()}")
        return worktree

    def commit_all(self, worktree: Path, message: str) -> bool:
        """Stage and commit everything; return False when there was nothing to commit."""
        self._run(["git", "add", "-A"], str(worktree), timeout=120)
        result = self._run(
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "commit",
                "--no-verify",
                "-m",
                message,
            ],
            str(worktree),
            timeout=120,
        )
        if result.exit_code != 0 and "nothing to commit" in result.stdout + result.stderr:
            return False
        if result.exit_code != 0:
            raise RuntimeError(f"git commit failed: {result.stderr.strip()}")
        return True

    def push(self, worktree: Path, branch: str, token: str) -> None:
        # Authenticate this one push with the freshly minted token, scoped to
        # this subprocess, without touching any global git credential helper.
        helper = '!f() { echo "username=x-access-token"; echo "password=$FACTORY_GIT_TOKEN"; }; f'
        result = self._run(
            ["git", "-c", f"credential.helper={helper}", "push", "-u", "origin", branch],
            str(worktree),
            timeout=300,
            env={"FACTORY_GIT_TOKEN": token},
        )
        if result.exit_code != 0:
            raise RuntimeError(f"git push failed: {result.stderr.strip()}")

    def check(self, worktree: Path) -> tuple[bool, str]:
        """Run the check script as the agent user; return (passed, truncated output).

        The agent wrote this code, so the script must run as the unprivileged
        agent user with only the base environment allowlist — never as the
        factory user and never with secrets.
        """
        backend = worktree / "backend"
        env = build_check_env(
            self._base_env,
            agent_user=self._agent_user,
            agent_home=self._agent_home,
        )
        argv = [str(backend / "scripts" / "check.sh")]
        if self._agent_user:
            argv = sudo_argv(self._agent_user, argv, env)
        result = self._run(argv, str(backend), timeout=1800, env=env, replace_env=True)
        output = result.stdout
        if result.stderr:
            output += ("\n" if output else "") + result.stderr
        return result.exit_code == 0, truncate_check_output(output.strip())

    def diff_stats(self, worktree: Path) -> DiffStats:
        numstat = self._run(
            ["git", "diff", "origin/main...HEAD", "--numstat"], str(worktree), timeout=120
        ).stdout
        new_files = self._run(
            ["git", "diff", "origin/main...HEAD", "--diff-filter=A", "--name-only"],
            str(worktree),
            timeout=120,
        ).stdout.splitlines()
        return build_diff_stats(numstat, new_files)

    def read_file(self, worktree: Path, relpath: str) -> str:
        result = self._run(["cat", relpath], str(worktree), timeout=60)
        return result.stdout

    def write_file(self, worktree: Path, relpath: str, content: str) -> None:
        path = worktree / relpath
        path.write_text(content)

    def remove_worktree(self, repo_dir: Path, worktree: Path) -> None:
        self._run(
            ["git", "worktree", "remove", "--force", str(worktree)],
            str(repo_dir),
            timeout=300,
        )

    def delete_branch(self, repo_dir: Path, branch: str) -> None:
        self._run(["git", "branch", "-D", branch], str(repo_dir), timeout=120)
