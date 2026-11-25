"""Git operations on the checkout and its worktrees, wrapped around ``git``."""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

from .contract_diff import CONTRACT_DIFF_CONTEXT, CONTRACTS_DIR
from .diff import DiffStats, build_diff_stats
from .shell import RunCommand, run_command
from .worktree_cleanup import WorktreeCleanupError

MIN_GIT_VERSION = (2, 46)

_GIT_VERSION_RE = re.compile(r"git version (\d+)\.(\d+)(?:\.(\d+))?")


class GitVersionError(RuntimeError):
    """Raised when the installed git cannot honour the safe.directory glob."""


BOT_COMMIT_NAME = "xolo-bot[bot]"

BOT_COMMIT_EMAIL_DOMAIN = "users.noreply.github.com"


class GitIdentityError(RuntimeError):
    """Raised when the bot commit identity cannot be built or used."""


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


class GitRepo:
    """The checkout, its worktrees and branches; commits as the bot."""

    def __init__(self, run: RunCommand = run_command, *, bot_user_id: str | None = None):
        self._run = run
        self._bot_user_id = bot_user_id

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

    def head_sha(self, worktree: Path) -> str:
        result = self._run(["git", "rev-parse", "HEAD"], str(worktree), timeout=60)
        if result.exit_code != 0:
            raise RuntimeError(f"could not read HEAD: {result.stderr.strip()}")
        return result.stdout.strip()

    def diff_stats(self, worktree: Path, *, since: str | None = None) -> DiffStats:
        """The changes a run made.

        A new ticket compares HEAD with its merge base on ``origin/main``. A
        review fix passes ``since``, the SHA right after the runner merged main,
        and compares that tree with HEAD (two-dot). The agent may amend or reset
        that merge commit, so ``since`` is not guaranteed to be an ancestor of
        HEAD; a merge-base range would then count main's files as the agent's.
        """
        revisions = ["origin/main...HEAD"] if since is None else [since, "HEAD"]
        numstat = self._run(
            ["git", "diff", *revisions, "--numstat"], str(worktree), timeout=120
        ).stdout
        new_files = self._run(
            ["git", "diff", *revisions, "--diff-filter=A", "--name-only"],
            str(worktree),
            timeout=120,
        ).stdout.splitlines()
        return build_diff_stats(numstat, new_files)

    def read_ref_file(self, repo_dir: Path, ref: str, path: str) -> str:
        """A file's content at ``ref`` (for example REVIEW.md on origin/main)."""
        result = self._run(["git", "show", f"{ref}:{path}"], str(repo_dir), timeout=60)
        if result.exit_code != 0:
            raise RuntimeError(f"git show {ref}:{path} failed: {result.stderr.strip()}")
        return result.stdout

    def _with_temp_index(self, worktree: Path, argv: list[str]) -> str:
        """Run ``argv`` against a throwaway index holding every current file.

        The real index stays untouched, so untracked files show up in the diff
        and fingerprint without staging anything for the runner's commit.
        """
        index = self._run(["git", "rev-parse", "--git-path", "index"], str(worktree), timeout=60)
        if index.exit_code != 0:
            raise RuntimeError(f"git rev-parse failed: {index.stderr.strip()}")
        real_index = Path(index.stdout.strip())
        if not real_index.is_absolute():
            real_index = worktree / real_index
        with tempfile.TemporaryDirectory(prefix="factory-index-") as tmp:
            temp_index = Path(tmp) / "index"
            if real_index.exists():
                shutil.copyfile(real_index, temp_index)
            env = {"GIT_INDEX_FILE": str(temp_index)}
            added = self._run(["git", "add", "-A"], str(worktree), timeout=300, env=env)
            if added.exit_code != 0:
                raise RuntimeError(f"git add (temporary index) failed: {added.stderr.strip()}")
            result = self._run(argv, str(worktree), timeout=300, env=env)
        if result.exit_code != 0:
            raise RuntimeError(f"{' '.join(argv[:2])} failed: {result.stderr.strip()}")
        return result.stdout

    def review_diff(self, worktree: Path) -> str:
        """Everything the builder changed against origin/main, new files included."""
        return self._with_temp_index(worktree, ["git", "diff", "--cached", "origin/main"])

    def contract_diff(self, worktree: Path) -> str:
        """The change to ``docs/contracts/`` against origin/main, whole files as context.

        Every changed line then has its ``## <module>.<name>`` heading in the same
        hunk, which is how the factory tells which contracts a change edits (#203).
        """
        return self._with_temp_index(
            worktree,
            [
                "git",
                "diff",
                "--cached",
                f"--unified={CONTRACT_DIFF_CONTEXT}",
                "origin/main",
                "--",
                CONTRACTS_DIR,
            ],
        )

    def review_changed_files(self, worktree: Path) -> list[str]:
        """Every path the builder changed against origin/main, new files included."""
        out = self._with_temp_index(
            worktree, ["git", "diff", "--cached", "--name-only", "origin/main"]
        )
        return [line for line in out.splitlines() if line.strip()]

    def worktree_fingerprint(self, worktree: Path) -> str:
        """HEAD plus the tree of every current file; any edit or commit changes it."""
        tree = self._with_temp_index(worktree, ["git", "write-tree"]).strip()
        head = self._run(["git", "rev-parse", "HEAD"], str(worktree), timeout=60).stdout.strip()
        return f"{head}:{tree}"

    def read_file(self, worktree: Path, relpath: str) -> str:
        result = self._run(["cat", relpath], str(worktree), timeout=60)
        return result.stdout

    def write_file(self, worktree: Path, relpath: str, content: str) -> None:
        path = worktree / relpath
        path.write_text(content)

    def delete_branch(self, repo_dir: Path, branch: str) -> None:
        result = self._run(["git", "branch", "-D", branch], str(repo_dir), timeout=120)
        if result.exit_code != 0:
            raise WorktreeCleanupError(
                f"could not delete local branch {branch!r}: "
                f"{result.stderr.strip() or result.exit_code}"
            )
