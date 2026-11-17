"""Git operations in the worktree, wrapped around ``git`` and faked in tests."""

from __future__ import annotations

import os
import re
import socket
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .areas import Area, select_areas
from .diff import DiffStats, build_diff_stats
from .runner import build_check_env, kill_agent_processes, sudo_argv, truncate_check_output
from .shell import CommandTimeout, RunCommand, run_command

MIN_GIT_VERSION = (2, 46)
_GIT_VERSION_RE = re.compile(r"git version (\d+)\.(\d+)(?:\.(\d+))?")


class GitVersionError(RuntimeError):
    """Raised when the installed git cannot honour the safe.directory glob."""


BOT_COMMIT_NAME = "xolo-bot[bot]"
BOT_COMMIT_EMAIL_DOMAIN = "users.noreply.github.com"
RM_BIN = "/usr/bin/rm"
CHECK_TIMEOUT_SECONDS = 1800
CHECK_SCRIPT_RELATIVE = Path("backend") / "scripts" / "check.sh"
CLEANUP_PROBE_RELATIVE = Path("backend") / ".cleanup-probe"
CLEANUP_PROBE_SCRIPT = """#!/usr/bin/env bash
set -euo pipefail
worktree="$(cd "$(dirname "$0")/../.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
probe="$tmp/.cleanup-probe"
mkdir -m 0770 "$probe"
chgrp "$(id -gn)" "$probe"
chmod 0770 "$probe"
printf 'cleanup probe\\n' > "$probe/file"
chmod 0644 "$probe/file"
mv "$probe" "$worktree/backend/.cleanup-probe"
"""


class GitIdentityError(RuntimeError):
    """Raised when the bot commit identity cannot be built or used."""


class WorktreeCleanupError(RuntimeError):
    """Raised when a worktree or branch cannot be cleaned up."""


@dataclass(frozen=True)
class CheckResult:
    """The result of running one or more areas' check scripts."""

    passed: bool
    output: str
    failed_areas: tuple[Area, ...] = ()
    checked_areas: tuple[Area, ...] = ()


def port_in_use(port: int) -> bool:
    """Return True when something is already listening on ``port``."""
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.2)
                if sock.connect_ex((host, port)) == 0:
                    return True
        except OSError:
            continue
    return False


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


def bot_commit_email(user_id: str) -> str:
    """Return the noreply email GitHub uses for an app's bot account."""
    return f"{user_id}+{BOT_COMMIT_NAME}@{BOT_COMMIT_EMAIL_DOMAIN}"


def commit_identity_args(user_id: str | None) -> list[str]:
    """Return the ``git -c`` args that pin the commit identity in code.

    Git identity is machine state; passing it explicitly means a fresh machine
    with no global ``user.name``/``user.email`` still commits as the bot.
    """
    if not user_id:
        raise GitIdentityError(
            "XOLO_BOT_USER_ID is not set; the runner needs it to commit as "
            f"{BOT_COMMIT_NAME} without relying on machine git config."
        )
    return [
        "-c",
        f"user.name={BOT_COMMIT_NAME}",
        "-c",
        f"user.email={bot_commit_email(user_id)}",
    ]


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


TOKEN_CREDENTIAL_HELPER = (
    '!f() { echo "username=x-access-token"; echo "password=$FACTORY_GIT_TOKEN"; }; f'
)


class Git:
    def __init__(
        self,
        run: RunCommand = run_command,
        *,
        agent_user: str | None = None,
        agent_home: str | None = None,
        bot_user_id: str | None = None,
        base_env: dict[str, str] | None = None,
        port_in_use: Callable[[int], bool] = port_in_use,
    ):
        self._run = run
        self._agent_user = agent_user
        self._agent_home = agent_home
        self._bot_user_id = bot_user_id
        self._base_env = dict(base_env if base_env is not None else os.environ)
        self._port_in_use = port_in_use

    def fetch_main(self, repo_dir: Path) -> None:
        result = self._run(["git", "fetch", "origin", "main"], str(repo_dir), timeout=300)
        if result.exit_code != 0:
            raise RuntimeError(f"git fetch failed: {result.stderr.strip()}")

    def fetch_branch(self, repo_dir: Path, branch: str) -> None:
        result = self._run(["git", "fetch", "origin", branch], str(repo_dir), timeout=300)
        if result.exit_code != 0:
            raise RuntimeError(f"git fetch failed: {result.stderr.strip()}")

    def worktree_exists(self, repo_dir: Path, worktree: Path) -> bool:
        result = self._run(["git", "worktree", "list", "--porcelain"], str(repo_dir), timeout=120)
        if result.exit_code != 0:
            return False
        target = f"worktree {worktree}"
        return any(line.strip() == target for line in result.stdout.splitlines())

    def live_worktree_paths(self, repo_dir: Path) -> set[Path]:
        """Return every path ``git worktree list`` reports as live."""
        result = self._run(["git", "worktree", "list", "--porcelain"], str(repo_dir), timeout=120)
        if result.exit_code != 0:
            raise WorktreeCleanupError(
                f"could not list git worktrees: {result.stderr.strip() or result.exit_code}"
            )
        return {
            Path(line[len("worktree ") :]).resolve()
            for line in result.stdout.splitlines()
            if line.startswith("worktree ")
        }

    def verify_no_leaked_worktrees(self, repo_dir: Path, worktrees_dir: Path) -> None:
        """Fail if the worktrees directory has entries git does not know about."""
        if not worktrees_dir.exists():
            return
        live = self.live_worktree_paths(repo_dir)
        leaked = sorted(entry for entry in worktrees_dir.iterdir() if entry.resolve() not in live)
        if leaked:
            shown = ", ".join(str(entry) for entry in leaked)
            raise WorktreeCleanupError(
                "the worktrees directory contains entries that are not live git worktrees: "
                f"{shown}. Remove them before running the factory."
            )

    def branch_exists(self, repo_dir: Path, branch: str) -> bool:
        result = self._run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            str(repo_dir),
            timeout=120,
        )
        return result.exit_code == 0

    def create_worktree(self, repo_dir: Path, worktree: Path, branch: str) -> Path:
        return self.create_worktree_from(repo_dir, worktree, branch, "origin/main")

    def create_worktree_from(self, repo_dir: Path, worktree: Path, branch: str, base: str) -> Path:
        result = self._run(
            ["git", "worktree", "add", "-b", branch, str(worktree), base],
            str(repo_dir),
            timeout=300,
        )
        if result.exit_code != 0:
            raise RuntimeError(f"could not create worktree for {branch}: {result.stderr.strip()}")
        return worktree

    def merge_main(self, worktree: Path) -> bool:
        """Merge origin/main into the worktree's branch with a merge commit.

        Return False after aborting when the merge conflicts, so the branch is
        left exactly as it was. Hooks are disabled like in ``commit_all``.
        """
        identity = commit_identity_args(self._bot_user_id)
        result = self._run(
            [
                "git",
                *identity,
                "-c",
                "core.hooksPath=/dev/null",
                "merge",
                "--no-edit",
                "--no-ff",
                "origin/main",
            ],
            str(worktree),
            timeout=300,
        )
        if result.exit_code == 0:
            return True
        aborted = self._run(["git", "merge", "--abort"], str(worktree), timeout=120)
        if aborted.exit_code != 0:
            raise RuntimeError(f"git merge --abort failed: {aborted.stderr.strip()}")
        return False

    def verify_commit_identity(self, repo_dir: Path) -> None:
        """Dry-check that git can build the explicit bot identity.

        ``git var`` resolves the author and committer identity without creating
        a commit or touching a ref, so a machine with no global git identity
        passes only because the runner supplies one.
        """
        identity = commit_identity_args(self._bot_user_id)
        for variable in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT"):
            result = self._run(["git", *identity, "var", variable], str(repo_dir), timeout=60)
            if result.exit_code != 0:
                raise GitIdentityError(
                    f"git cannot build the {BOT_COMMIT_NAME} commit identity: "
                    f"{result.stderr.strip() or result.exit_code}"
                )

    def commit_all(self, worktree: Path, message: str) -> bool:
        """Stage and commit everything; return False when there was nothing to commit."""
        identity = commit_identity_args(self._bot_user_id)
        self._run(["git", "add", "-A"], str(worktree), timeout=120)
        result = self._run(
            [
                "git",
                *identity,
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

    def remote_branch_exists(self, repo_dir: Path, branch: str, token: str) -> bool:
        """Ask origin whether ``branch`` exists, authenticating like ``push`` does."""
        result = self._run(
            [
                "git",
                "-c",
                f"credential.helper={TOKEN_CREDENTIAL_HELPER}",
                "ls-remote",
                "--heads",
                "origin",
                f"refs/heads/{branch}",
            ],
            str(repo_dir),
            timeout=300,
            env={"FACTORY_GIT_TOKEN": token},
        )
        if result.exit_code != 0:
            raise RuntimeError(f"git ls-remote failed: {result.stderr.strip()}")
        return bool(result.stdout.strip())

    def push(self, worktree: Path, branch: str, token: str) -> None:
        # Authenticate this one push with the freshly minted token, scoped to
        # this subprocess, without touching any global git credential helper.
        helper = TOKEN_CREDENTIAL_HELPER
        result = self._run(
            ["git", "-c", f"credential.helper={helper}", "push", "-u", "origin", branch],
            str(worktree),
            timeout=300,
            env={"FACTORY_GIT_TOKEN": token},
        )
        if result.exit_code != 0:
            raise RuntimeError(f"git push failed: {result.stderr.strip()}")

    def changed_files(self, worktree: Path) -> list[str]:
        """Return every file this ticket changed, committed or not.

        The diff against the merge base covers the branch's commits, the
        working-tree diff covers what the agent has edited but not committed,
        and ``git ls-files`` covers new files the agent has not added.
        """
        committed = self._run(
            ["git", "diff", "origin/main...HEAD", "--name-only"], str(worktree), timeout=120
        ).stdout
        working = self._run(
            ["git", "diff", "HEAD", "--name-only"], str(worktree), timeout=120
        ).stdout
        untracked = self._run(
            ["git", "ls-files", "--others", "--exclude-standard"], str(worktree), timeout=120
        ).stdout
        return sorted(
            {
                line.strip()
                for text in (committed, working, untracked)
                for line in text.splitlines()
                if line.strip()
            }
        )

    def _port_still_busy(self, port: int) -> bool:
        """Check a fixed port, cleaning up leftover agent servers once first."""
        if not self._port_in_use(port):
            return False
        kill_agent_processes(self._run, self._agent_user)
        return self._port_in_use(port)

    def check(self, worktree: Path, *, areas: tuple[Area, ...] | None = None) -> CheckResult:
        """Run each selected area's check script as the agent user.

        With no explicit ``areas`` the ticket's changed files decide them; the
        preflight passes every area because its worktree is fresh main. Each
        script gets its own timeout and a labelled slice of the output. The
        agent wrote this code, so the scripts must run as the unprivileged agent
        user with only the environment allowlist their area needs — never as the
        factory user and never with secrets. A missing script is skipped, not a
        failure.
        """
        selected = select_areas(self.changed_files(worktree)) if areas is None else areas
        chunks: list[str] = []
        failed: list[Area] = []
        checked: list[Area] = []
        for area in selected:
            script = worktree / area.script
            label = f"{area.name} ({area.script.as_posix()})"
            if not script.is_file():
                chunks.append(f"=== {label}: skipped (script not found) ===")
                continue
            if area.port is not None and self._port_still_busy(area.port):
                failed.append(area)
                chunks.append(f"=== {label}: failed: port {area.port} busy after agent cleanup ===")
                continue
            env = build_check_env(
                self._base_env,
                agent_user=self._agent_user,
                agent_home=self._agent_home,
                area=area,
            )
            checked.append(area)
            argv = [str(script)]
            if self._agent_user:
                argv = sudo_argv(self._agent_user, argv, env)
            try:
                result = self._run(
                    argv,
                    str(script.parent),
                    timeout=CHECK_TIMEOUT_SECONDS,
                    env=env,
                    replace_env=True,
                )
            except CommandTimeout:
                kill_agent_processes(self._run, self._agent_user)
                failed.append(area)
                chunks.append(f"=== {label}: timed out after {CHECK_TIMEOUT_SECONDS}s ===")
                continue
            output = result.stdout
            if result.stderr:
                output += ("\n" if output else "") + result.stderr
            body = output.strip()
            chunks.append(f"=== {label} ===\n{body}" if body else f"=== {label} ===")
            if result.exit_code != 0:
                failed.append(area)
        return CheckResult(
            passed=not failed,
            output=truncate_check_output("\n\n".join(chunks).strip()),
            failed_areas=tuple(failed),
            checked_areas=tuple(checked),
        )

    def head_sha(self, worktree: Path) -> str:
        result = self._run(["git", "rev-parse", "HEAD"], str(worktree), timeout=60)
        if result.exit_code != 0:
            raise RuntimeError(f"could not read HEAD: {result.stderr.strip()}")
        return result.stdout.strip()

    def diff_stats(self, worktree: Path, base: str = "origin/main") -> DiffStats:
        """Changes on HEAD since its merge base with ``base``.

        New tickets compare with ``origin/main``; review fixes pass the SHA the
        fix started from, which is an ancestor of HEAD, so the three-dot range
        is exactly the fix's own commits.
        """
        numstat = self._run(
            ["git", "diff", f"{base}...HEAD", "--numstat"], str(worktree), timeout=120
        ).stdout
        new_files = self._run(
            ["git", "diff", f"{base}...HEAD", "--diff-filter=A", "--name-only"],
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

    def create_agent_cleanup_probe(self, worktree: Path) -> Path:
        """Create an agent-owned 0770 directory inside ``worktree``.

        The allowed ``check.sh`` path is used as a one-shot trampoline: it
        creates the probe in a temp dir (so its group is ``factory-agent``, not
        the worktree's setgid group) and renames it into the worktree, exactly
        like pytest's cache. This must run after the real check script.
        """
        if not self._agent_user:
            raise WorktreeCleanupError(
                "FACTORY_AGENT_USER is not set; cannot create the cleanup probe as the agent."
            )
        probe_dir = worktree / CLEANUP_PROBE_RELATIVE
        script_path = worktree / CHECK_SCRIPT_RELATIVE
        script_path.write_text(CLEANUP_PROBE_SCRIPT)
        script_path.chmod(0o755)
        env = build_check_env(
            self._base_env,
            agent_user=self._agent_user,
            agent_home=self._agent_home,
        )
        argv = sudo_argv(self._agent_user, [str(script_path)], env)
        result = self._run(
            argv,
            str(script_path.parent),
            timeout=120,
            env=env,
            replace_env=True,
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

    def delete_branch(self, repo_dir: Path, branch: str) -> None:
        result = self._run(["git", "branch", "-D", branch], str(repo_dir), timeout=120)
        if result.exit_code != 0:
            raise WorktreeCleanupError(
                f"could not delete local branch {branch!r}: "
                f"{result.stderr.strip() or result.exit_code}"
            )
