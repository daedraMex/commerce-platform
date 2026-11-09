"""Prove the machine can run a night before touching any ticket.

The preflight uses the real tools and the real code paths: it fetches
``origin/main``, lists tickets through the GitHub port, builds a throwaway
worktree from the fresh main, runs ``check.sh`` as the agent user, and verifies
isolation and the git version. Any failure is reported to Telegram with a
short, secret-free description and aborts the run before ticket selection.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from .config import Settings
from .credentials import TokenProvider
from .git import Git, verify_git_version
from .github import GitHub
from .isolation import sensitive_paths, verify_isolation, write_protected_paths
from .notify import Notifier, RunFailedInfo
from .tickets import Ticket, worktree_path

MAX_ERROR_CHARS = 300


class PreflightError(RuntimeError):
    """Raised when a preflight step fails; the run must not touch tickets."""

    def __init__(self, step: str, detail: str):
        self.step = step
        self.detail = detail
        super().__init__(f"{step}: {detail}")


def short_error(text: str, *, limit: int = MAX_ERROR_CHARS) -> str:
    """Collapse an error to one bounded line for Telegram."""
    collapsed = " ".join(str(text).split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "…"


class Preflight:
    def __init__(
        self,
        settings: Settings,
        *,
        git: Git,
        github: GitHub,
        notifier: Notifier,
        token_provider: TokenProvider,
        clock: Callable[[], int] | None = None,
        verify_isolation_fn: Callable[..., None] = verify_isolation,
        verify_git_version_fn: Callable[[], None] = verify_git_version,
    ):
        self.settings = settings
        self.git = git
        self.github = github
        self.notifier = notifier
        self.token_provider = token_provider
        self._clock = clock or (lambda: int(time.time()))
        self._verify_isolation = verify_isolation_fn
        self._verify_git_version = verify_git_version_fn

    def run(self) -> list[Ticket]:
        worktree = None
        branch = None
        step = "fetch origin/main"
        try:
            self.git.fetch_main(self.settings.repo_dir)

            step = "list tickets"
            token = self.token_provider.mint(self.settings.repo)
            tickets = self.github.list_tickets(token)

            step = "create worktree"
            branch = f"preflight-{self._clock()}"
            worktree = worktree_path(self.settings.worktrees_dir, branch)
            self.git.create_worktree(self.settings.repo_dir, worktree, branch)

            step = "check.sh"
            passed, _output = self.git.check(worktree)
            if not passed:
                raise RuntimeError("check.sh failed")

            step = "verify isolation"
            self._verify_isolation(
                agent_user=self.settings.agent_user,
                paths=sensitive_paths(self.settings),
                write_paths=write_protected_paths(self.settings),
            )

            step = "verify git version"
            self._verify_git_version()

            return tickets
        except PreflightError:
            raise
        except Exception as exc:
            detail = short_error(exc) or type(exc).__name__
            self.notifier.send_run_failed(
                RunFailedInfo(reason=f"preflight failed: {step}: {detail}")
            )
            raise PreflightError(step, detail) from exc
        finally:
            self._cleanup(worktree, branch)

    def _cleanup(self, worktree, branch) -> None:
        if worktree is not None:
            try:
                self.git.remove_worktree(self.settings.repo_dir, worktree)
            except Exception:
                pass
        if branch is not None:
            try:
                self.git.delete_branch(self.settings.repo_dir, branch)
            except Exception:
                pass
