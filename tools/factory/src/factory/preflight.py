"""Prove the machine can run unattended before touching any ticket.

The preflight uses the real tools and the real code paths: it fetches
``origin/main``, lists tickets through the GitHub port, builds a throwaway
worktree from the fresh main, runs ``check.sh`` as the agent user, and verifies
isolation and the git version. Any failure is reported to Telegram with a
short, secret-free description and aborts the run before ticket selection.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from .areas import AREAS
from .config import Settings
from .credentials import TokenProvider
from .git import Git, verify_git_version
from .github import GitHub
from .isolation import sensitive_paths, verify_isolation, write_protected_paths
from .notify import CleanedUpInfo, Notifier, RunFailedInfo
from .sudoers import verify_sudoers_logging
from .tickets import REQUIRED_LABELS, Ticket, worktree_path

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
        verify_sudoers_logging_fn: Callable[[], None] = verify_sudoers_logging,
        runner=None,
    ):
        self.settings = settings
        self.git = git
        self.github = github
        self.notifier = notifier
        self.token_provider = token_provider
        self._clock = clock or (lambda: int(time.time()))
        self._verify_isolation = verify_isolation_fn
        self._verify_git_version = verify_git_version_fn
        self._verify_sudoers_logging = verify_sudoers_logging_fn
        # The agent runner, when given, proves the cleanup works and that OpenCode
        # starts as the agent with the real env (read-only config home, #153).
        self.runner = runner

    def run(self, token: str | None = None) -> list[Ticket]:
        run_id = str(self._clock())
        log_path = self.settings.logs_dir / f"preflight-{run_id}.log"
        worktree = None
        branch = None
        failed_after: str | None = None
        step = "fetch origin/main"
        try:
            self.git.fetch_main(self.settings.repo_dir)

            step = "list tickets"
            if token is None:
                token = self.token_provider.mint(self.settings.repo)
            tickets = self.github.list_tickets(token)

            step = "verify labels"
            self._verify_labels(token)

            step = "verify isolation"
            self._verify_isolation(
                agent_user=self.settings.agent_user,
                paths=sensitive_paths(self.settings),
                write_paths=write_protected_paths(self.settings),
                existing_dirs=[
                    self.settings.agent_config_home,
                    self.settings.agent_config_home / "opencode",
                ],
                repo_dir=self.settings.repo_dir,
            )

            step = "verify git version"
            self._verify_git_version()

            step = "verify commit identity"
            self.git.verify_commit_identity(self.settings.repo_dir)

            step = "verify sudoers logging"
            self._verify_sudoers_logging()

            step = "remove preflight leftovers"
            self._remove_preflight_leftovers()

            step = "verify worktrees directory"
            self.git.verify_no_leaked_worktrees(self.settings.repo_dir, self.settings.worktrees_dir)

            step = "create worktree"
            branch = f"preflight-{run_id}"
            worktree = worktree_path(self.settings.worktrees_dir, branch)
            self.git.create_worktree(self.settings.repo_dir, worktree, branch)

            step = "check.sh"
            check = self.git.check(worktree, areas=AREAS)
            if not check.passed:
                self._write_check_log(log_path, check.output)
                raise RuntimeError(f"check.sh failed; see {log_path}")

            if self.runner is not None:
                step = "verify agent sandbox"
                self.runner.ensure_clean()
                self.runner.verify_home_is_clean()
                self.runner.smoke_check(worktree)

            step = "verify worktree cleanup"
            probe = self.git.create_agent_cleanup_probe(worktree)
            doomed_worktree, doomed_branch = worktree, branch
            worktree = None
            branch = None
            self._cleanup(doomed_worktree, doomed_branch)
            if doomed_worktree.exists() or probe.exists():
                raise RuntimeError(f"worktree cleanup left files behind at {doomed_worktree}")

            return tickets
        except PreflightError:
            failed_after = step
            raise
        except Exception as exc:
            failed_after = step
            detail = short_error(exc) or type(exc).__name__
            self.notifier.send_run_failed(
                RunFailedInfo(reason=f"preflight failed: {step}: {detail}")
            )
            raise PreflightError(step, detail) from exc
        except BaseException:
            failed_after = f"interrupted during {step}"
            raise
        finally:
            if failed_after is None:
                self._cleanup(worktree, branch)
            else:
                self._cleanup_keeping_the_failure(worktree, branch, failed_after)

    def _verify_labels(self, token: str) -> None:
        """Fail before any model spend when a label the factory writes is missing."""
        missing = sorted(REQUIRED_LABELS - self.github.list_label_names(token))
        if missing:
            # Short enough that MAX_ERROR_CHARS keeps every name, even with all missing.
            raise RuntimeError(
                f"missing labels {', '.join(missing)}; create each with "
                f"gh label create <name> --repo {self.settings.repo}"
            )

    def _write_check_log(self, log_path, output: str) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(output)

    def _remove_preflight_leftovers(self) -> None:
        """Delete what an interrupted preflight left, so it never stops later runs (#194).

        Runs after the sudoers and isolation checks, because the delete needs them.
        A leftover that cannot be deleted fails the step, as any cleanup failure does.
        """
        for leftover in self.git.preflight_leftovers(self.settings.worktrees_dir):
            self._cleanup(leftover, leftover.name)
            self.notifier.send_cleaned_up(
                CleanedUpInfo(reason=f"removed a leftover preflight worktree: {leftover}")
            )

    def _cleanup_keeping_the_failure(self, worktree, branch, failed_after: str) -> None:
        """Clean up after a failure without letting a cleanup error replace it.

        An exception from ``finally`` would replace the one in flight, and the
        reason the preflight stopped would be lost (#194). The cleanup error is
        reported on its own; the original keeps propagating.
        """
        try:
            self._cleanup(worktree, branch)
        except Exception as exc:
            detail = short_error(exc) or type(exc).__name__
            self.notifier.send_run_failed(
                RunFailedInfo(reason=f"preflight cleanup failed after {failed_after}: {detail}")
            )

    def _cleanup(self, worktree, branch) -> None:
        if worktree is not None:
            self.git.remove_worktree(self.settings.repo_dir, worktree, self.settings.worktrees_dir)
        if branch is not None and self.git.branch_exists(self.settings.repo_dir, branch):
            self.git.delete_branch(self.settings.repo_dir, branch)
