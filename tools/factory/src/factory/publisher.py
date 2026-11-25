"""From green checks to a pushed branch: guard, commit, push, PR (#147).

New tickets and review fixes share the guard; then a new ticket opens a PR and
a review fix updates its PR's evidence. The publisher does the git and GitHub
side effects and returns what happened; the factory reports it.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from .areas import Area
from .diff import DiffStats, is_dependency_path, non_dependency_change, touches_protected_paths
from .git import CheckResult
from .pr_body import build_pr_body, replace_verification, verification_section
from .preflight import short_error
from .tickets import DEPS_CHANGE_LABEL, MIGRATION_LABEL, Ticket, assert_push_target

MAIN_BASE = "origin/main"


@dataclass(frozen=True)
class Guarded:
    """The committed change, or why it must not be pushed."""

    diff: DiffStats
    failing_check: str | None = None


def allows_dependencies(ticket: Ticket) -> bool:
    return DEPS_CHANGE_LABEL in ticket.labels


class Publisher:
    def __init__(self, *, git, github, step_budget: int):
        self.git = git
        self.github = github
        self.step_budget = step_budget

    def guard(
        self,
        ticket: Ticket,
        worktree: Path,
        *,
        branch: str,
        message: str,
        since: str | None,
        empty_check: str,
    ) -> Guarded:
        """Commit everything, then refuse an empty, protected or out-of-scope change.

        commit_all's result decides nothing: the agent may have committed on its
        own (commit_all then has nothing left). The diff since ``since`` (origin/main
        when None) decides (#137). The push target is asserted last, before any push.
        """
        self.git.commit_all(worktree, message)
        diff = (
            self.git.diff_stats(worktree, since=since) if since else self.git.diff_stats(worktree)
        )
        if not diff.files:
            return Guarded(diff, empty_check)
        if touches_protected_paths(
            (f.path for f in diff.files), allow_dependencies=allows_dependencies(ticket)
        ):
            return Guarded(diff, "protected path changed")
        violation = self.dependency_scope_violation(ticket, worktree, diff, since or MAIN_BASE)
        if violation is not None:
            return Guarded(diff, violation)
        assert_push_target(branch, ticket)
        return Guarded(diff)

    def dependency_scope_violation(
        self, ticket: Ticket, worktree: Path, diff: DiffStats, base: str
    ) -> str | None:
        """On a deps-change ticket, the reason a manifest changed beyond dependencies."""
        if not allows_dependencies(ticket):
            return None
        for change in diff.files:
            if not is_dependency_path(change.path):
                continue
            try:
                old = self.git.read_ref_file(worktree, base, change.path)
            except RuntimeError:
                old = None
            try:
                new = self.git.read_file(worktree, change.path)
            except (OSError, RuntimeError):
                new = None  # deleted by the change
            reason = non_dependency_change(change.path, old, new)
            if reason is not None:
                return f"dependency file changed beyond dependencies: {reason}"
        return None

    def open_pr(
        self,
        ticket: Ticket,
        *,
        branch: str,
        worktree: Path,
        diff: DiffStats,
        token: str,
        summary: str,
        model: str,
        decisions: str,
        attempts: int,
        checked_areas: tuple[Area, ...],
        skipped_areas: tuple[Area, ...],
        check_output: str,
        review_lines: tuple[str, ...],
        undeclared_contracts: tuple[tuple[str, str], ...],
    ) -> int | None:
        """Push the branch and open its PR ready for review; None when no PR opened."""
        # The checks ran on this tree before commit_all, so this commit is what they verified.
        verified_sha = self.git.head_sha(worktree)
        self.git.push(worktree, branch, token)
        body = build_pr_body(
            ticket_number=ticket.number,
            summary=summary,
            model=model,
            decisions=decisions,
            checked_areas=checked_areas,
            skipped_areas=skipped_areas,
            review_lines=review_lines,
            diff=diff,
            steps_used=attempts,
            step_budget=self.step_budget,
            verified_sha=verified_sha,
            check_output=check_output,
            undeclared_contracts=undeclared_contracts,
        )
        try:
            pr_number = self.github.create_draft_pr(
                branch=branch, title=f"#{ticket.number}: {ticket.title}", body=body, token=token
            )
        except Exception as exc:
            # The branch is already pushed. Without a PR the next run's push would be
            # non-fast-forward, so the caller reports the ticket stuck and the remote
            # branch is left for a human to delete.
            print(f"PR for {branch} was not created: {short_error(exc)}", file=sys.stderr)
            return None
        if diff.migrations_changed:
            self.github.add_pr_label(pr_number, MIGRATION_LABEL, token)
        if any(is_dependency_path(f.path) for f in diff.files):
            self.github.add_pr_label(pr_number, DEPS_CHANGE_LABEL, token)
        self._mark_pr_ready(pr_number, token)
        self._enable_auto_merge(pr_number, token)
        return pr_number

    def update_review_pr(
        self,
        *,
        pr_number: int,
        branch: str,
        worktree: Path,
        diff: DiffStats,
        token: str,
        attempts: int,
        check: CheckResult,
    ) -> str | None:
        """Refresh the PR's evidence, push the fix and ask for a re-review.

        Returns the pushed commit, or None when the evidence could not be updated
        (then nothing is pushed).
        """
        # Labeled before the push: auto-merge is already on for this PR, so a failed
        # label must leave nothing pushed (#160).
        if any(is_dependency_path(f.path) for f in diff.files):
            self.github.add_pr_label(pr_number, DEPS_CHANGE_LABEL, token)
        sha = self.git.head_sha(worktree)
        # The evidence names the new commit before it is pushed: a push with a stale
        # body would fail the Evidence check, and a failed edit leaves nothing pushed.
        try:
            body = self.github.pr_body(pr_number, token)
            self.github.edit_pr_body(
                pr_number,
                replace_verification(
                    body,
                    verification_section(
                        verified_sha=sha,
                        checked_areas=check.checked_areas,
                        skipped_areas=check.skipped_areas,
                        steps_used=attempts,
                        step_budget=self.step_budget,
                        check_output=check.output,
                    ),
                ),
                token,
            )
        except Exception as exc:
            print(f"PR #{pr_number} body not updated: {short_error(exc)}", file=sys.stderr)
            return None
        self.git.push(worktree, branch, token)
        self.github.comment(pr_number, f"Addressed the review in {sha}; please re-review.", token)
        return sha

    def _mark_pr_ready(self, pr_number: int, token: str) -> None:
        """Mark the PR ready; a failure leaves it a draft and never fails the ticket."""
        self._best_effort(
            lambda: self.github.mark_pr_ready(pr_number, token), f"PR #{pr_number} stays a draft"
        )

    def _enable_auto_merge(self, pr_number: int, token: str) -> None:
        """Ask GitHub to auto-merge; a repo setting that forbids it is not fatal."""
        self._best_effort(
            lambda: self.github.enable_auto_merge(pr_number, token),
            f"auto-merge not enabled for PR #{pr_number}",
        )

    @staticmethod
    def _best_effort(call, what: str) -> None:
        try:
            result = call()
        except Exception as exc:
            print(f"{what}: {short_error(exc)}", file=sys.stderr)
            return
        if result.exit_code != 0:
            reason = result.stderr.strip() or result.stdout.strip() or f"exit {result.exit_code}"
            print(f"{what}: {short_error(reason)}", file=sys.stderr)
