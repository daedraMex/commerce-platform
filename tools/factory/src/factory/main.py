"""The night factory: pick ready tickets and run them, oldest first."""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from .areas import BACKEND, Area, select_areas
from .cleanup import cleanup_old
from .config import Settings
from .credentials import GithubAppTokenProvider, TokenProvider
from .decisions import DECISIONS_HEADER, extract_decisions, extract_open_question, extract_summary
from .diff import DiffStats, is_dependency_path, non_dependency_change, touches_protected_paths
from .git import CheckResult, Git, verify_git_version
from .github import GitHub, GitHubError
from .holds import LabelHolds
from .isolation import verify_isolation
from .ledger import AttemptLedger
from .metrics import MetricsGitHub, run_metrics
from .models import STRONG_MODEL_LABEL, select_model
from .notify import (
    Notifier,
    NullNotifier,
    PausedInfo,
    PrReadyInfo,
    ReviewAddressedInfo,
    ReviewSkippedInfo,
    RunFailedInfo,
    StuckInfo,
    TelegramNotifier,
    build_handoff_command,
)
from .outcomes import build_issue_comment
from .pause import PauseState
from .pr_body import build_pr_body, replace_verification, verification_section
from .preflight import Preflight, PreflightError, short_error
from .prompt import compose_prompt, compose_review_prompt, read_command_body
from .review_attempts import ReviewAttemptLedger
from .review_step import (
    REVIEW_RULES,
    REVIEWER_CONFIG_PATH,
    AttackRun,
    Finding,
    PrePrReview,
    attack_test_paths,
    build_reviewer_feedback,
    compose_reviewer_prompt,
    parse_review,
    stuck_reason,
    suggested_ticket_body,
    suggested_ticket_title,
)
from .reviews import ReviewFix
from .runner import OPENCODE_CONFIG_PATH, AgentRunner
from .sudoers import verify_sudoers_logging
from .tickets import (
    DEPS_CHANGE_LABEL,
    MIGRATION_LABEL,
    NEEDS_DECISION_LABEL,
    Ticket,
    assert_push_target,
    branch_from_worktree_dir_name,
    branch_name,
    is_ready,
    select_tickets,
    worktree_path,
)

DECISIONS_FILE = "DECISIONS.md"
IMPLEMENT_COMMAND_PATH = ".opencode/commands/implement.md"
LOG_TAIL_LINES = 30
FACTORY_BOT_LOGIN = "xolo-bot"
FACTORY_BRANCH_PREFIX = "nf/"
OWNER_LOGIN = "daedraMex"
MERGE_CONFLICT_CHECK = "branch conflicts with main; a human must merge main"
EVIDENCE_NOT_UPDATED_CHECK = "PR body evidence not updated; nothing was pushed"


def _orphan_branch_check(branch: str) -> str:
    return f"remote branch {branch} has no open PR; delete it by hand so the next run can retry"


@dataclass(frozen=True)
class TicketResult:
    ticket: Ticket
    ok: bool


class RunFailed(RuntimeError):
    """An unexpected failure while running the factory or a single ticket."""

    def __init__(self, phase: str, detail: str):
        self.phase = phase
        self.detail = detail
        super().__init__(f"{phase}: {detail}")


class Factory:
    def __init__(
        self,
        settings: Settings,
        *,
        github: GitHub,
        git: Git,
        runner: AgentRunner,
        notifier: Notifier,
        token_provider: TokenProvider,
        overlay: str,
        preflight_verify_isolation=verify_isolation,
        preflight_verify_git_version=verify_git_version,
        preflight_verify_sudoers_logging=verify_sudoers_logging,
        preflight_clock=None,
        ledger: AttemptLedger | None = None,
        review_attempts: ReviewAttemptLedger | None = None,
        pause_state: PauseState | None = None,
        label_holds: LabelHolds | None = None,
    ):
        self.settings = settings
        self.github = github
        self.git = git
        self.runner = runner
        self.notifier = notifier
        self.token_provider = token_provider
        self.overlay = overlay
        self._preflight_verify_isolation = preflight_verify_isolation
        self._preflight_verify_git_version = preflight_verify_git_version
        self._preflight_verify_sudoers_logging = preflight_verify_sudoers_logging
        self._preflight_clock = preflight_clock
        self.ledger = ledger or AttemptLedger(settings.state_dir)
        self.review_attempts = review_attempts or ReviewAttemptLedger(settings.state_dir)
        self.pause_state = pause_state or PauseState(settings.state_dir)
        self.label_holds = label_holds or LabelHolds(settings.state_dir)

    def run(self) -> list[TicketResult]:
        token, open_prs, paused_for = self._run_limits()
        if paused_for is not None:
            self._enter_pause(paused_for)
            return []
        review_fix = self._select_review_fix(token)
        if review_fix is None and open_prs >= self.settings.max_open_prs:
            self._enter_pause(self._open_pr_pause_reason(open_prs))
            return []
        self.pause_state.clear()
        cleanup_old(
            self.settings.worktrees_dir,
            keep_days=self.settings.keep_days,
            remove_dir=self._remove_expired_worktree,
        )
        cleanup_old(self.settings.logs_dir, keep_days=self.settings.keep_days)
        tickets = self.run_preflight(token=token)
        held = self._retry_held_labels(token)
        if review_fix is not None:
            self.review_attempts.record_attempted(review_fix.review_id)
            return [
                self._execute(
                    review_fix.ticket,
                    lambda: self._run_review_fix(review_fix),
                    f"#{review_fix.ticket.number} review on PR #{review_fix.pr_number}",
                )
            ]
        results: list[TicketResult] = []
        eligible = [t for t in tickets if t.number not in held]
        _log_contract_skips(eligible)
        for ticket in select_tickets(eligible, max_tickets=self.settings.max_tickets):
            result = self._execute(
                ticket,
                lambda t=ticket: self._run_ticket(t, token),
                f"#{ticket.number} {ticket.title}",
            )
            results.append(result)
            if not result.ok:
                break
        return results

    def _retry_held_labels(self, token: str | None) -> frozenset[int]:
        """Retry needs-decision on held tickets; return every ticket held at the start.

        A ticket released here is still skipped this run: the listing was read
        before its label landed.
        """
        held = self.label_holds.numbers()
        for number in sorted(held):
            try:
                self.github.add_issue_label(number, NEEDS_DECISION_LABEL, token)
            except Exception as exc:
                print(f"#{number} stays held: {short_error(exc)}", file=sys.stderr)
                continue
            self.label_holds.remove(number)
        return held

    def _run_limits(self) -> tuple[str | None, int, str | None]:
        """Mint a token, read the open-PR count and check the daily cap.

        The open-PR cap is not applied here: a review fix on an existing PR
        must still run when the cap is reached. It is checked before a new
        ticket is picked. The daily cap does apply to every attempt.
        """
        try:
            token = self.token_provider.mint(self.settings.repo)
            open_prs = self.github.count_open_factory_prs(
                author=FACTORY_BOT_LOGIN,
                branch_prefix=FACTORY_BRANCH_PREFIX,
                token=token,
            )
        except Exception:
            return None, 0, "GitHub unreachable"
        if self.ledger.count_today() >= self.settings.max_tickets_per_day:
            return token, open_prs, "daily limit reached"
        return token, open_prs, None

    def _open_pr_pause_reason(self, open_prs: int) -> str:
        noun = "PR" if open_prs == 1 else "PRs"
        return f"{open_prs} {noun} waiting for review"

    def _enter_pause(self, reason: str) -> None:
        if self.pause_state.enter(reason):
            self._notify(self.notifier.send_paused, PausedInfo(reason=reason))

    def _execute(self, ticket: Ticket, operation, phase: str) -> TicketResult:
        started_at = self.ledger.now()
        self.ledger.record_started(ticket.number, started_at=started_at)
        try:
            result = operation()
        except Exception as exc:
            self.ledger.record_outcome(ticket.number, "failed", finished_at=self.ledger.now())
            raise RunFailed(phase, short_error(exc)) from exc
        except BaseException:
            self.ledger.record_outcome(ticket.number, "failed", finished_at=self.ledger.now())
            raise
        self.ledger.record_outcome(
            ticket.number,
            "ok" if result.ok else "stuck",
            finished_at=self.ledger.now(),
        )
        return result

    def _select_review_fix(self, token: str | None) -> ReviewFix | None:
        """Pick the oldest review that asks for changes, or None.

        Listing failures are not fatal: review fixes are skipped for this run
        while the normal ticket flow continues. GitHub being unreachable is
        detected earlier, in ``_run_limits``.
        """
        attempted = self.review_attempts.attempted_ids()
        try:
            fixes = self.github.list_review_fixes(
                author=FACTORY_BOT_LOGIN,
                owner=OWNER_LOGIN,
                branch_prefix=FACTORY_BRANCH_PREFIX,
                attempted_review_ids=frozenset(attempted),
                token=token,
            )
        except GitHubError as exc:
            reason = short_error(exc)
            print(f"skipping review fixes: {reason}", file=sys.stderr)
            self._notify(self.notifier.send_review_skipped, ReviewSkippedInfo(reason=reason))
            return None
        except Exception as exc:
            print(f"skipping review fixes: {short_error(exc)}", file=sys.stderr)
            return None
        for fix in fixes:
            if fix.review_id not in attempted:
                return fix
        return None

    def run_preflight(self, token: str | None = None) -> list[Ticket]:
        """Run the real-tool preflight and return the tickets it listed."""
        return Preflight(
            self.settings,
            git=self.git,
            github=self.github,
            notifier=self.notifier,
            token_provider=self.token_provider,
            clock=self._preflight_clock,
            verify_isolation_fn=self._preflight_verify_isolation,
            verify_git_version_fn=self._preflight_verify_git_version,
            verify_sudoers_logging_fn=self._preflight_verify_sudoers_logging,
            runner=self.runner,
        ).run(token=token)

    def _remove_expired_worktree(self, worktree: Path) -> None:
        """Delete an expired worktree as its owner, then its local branch."""
        branch = branch_from_worktree_dir_name(worktree.name)
        self.git.remove_worktree(self.settings.repo_dir, worktree, self.settings.worktrees_dir)
        if self.git.branch_exists(self.settings.repo_dir, branch):
            self.git.delete_branch(self.settings.repo_dir, branch)

    def _remove_stale_ticket_worktree(self, worktree: Path, branch: str) -> None:
        """Drop a previous stuck run's worktree and local branch, never the remote."""
        if worktree.exists() or self.git.worktree_exists(self.settings.repo_dir, worktree):
            self.git.remove_worktree(self.settings.repo_dir, worktree, self.settings.worktrees_dir)
        if self.git.branch_exists(self.settings.repo_dir, branch):
            self.git.delete_branch(self.settings.repo_dir, branch)

    def _run_ticket(self, ticket: Ticket, token: str | None) -> TicketResult:
        model = select_model(
            ticket.labels,
            default_model=self.settings.factory_model,
            strong_model=self.settings.factory_strong_model,
        )
        branch = branch_name(ticket)
        assert_push_target(branch, ticket)  # before any model spend
        worktree = worktree_path(self.settings.worktrees_dir, branch)
        # A remote branch left by a run whose PR was never opened would make the push
        # non-fast-forward forever. Stop here; deleting it stays a manual step.
        if self.git.remote_branch_exists(
            self.settings.repo_dir, branch, token
        ) and not self.github.has_open_pr_for_branch(branch, token):
            return self._stuck(
                ticket,
                model=model,
                decisions="",
                log_path=self._log_path(ticket),
                worktree=None,
                open_question=None,
                failing_check=_orphan_branch_check(branch),
                attempts=0,
            )
        self._remove_stale_ticket_worktree(worktree, branch)
        # Each ticket fetches its own base; it must not depend on the preflight's fetch.
        self.git.fetch_main(self.settings.repo_dir)
        builder_config = self._builder_config()
        worktree = self.git.create_worktree(self.settings.repo_dir, worktree, branch)
        self.git.write_file(worktree, DECISIONS_FILE, DECISIONS_HEADER)
        command_template = read_command_body(self.git.read_file(worktree, IMPLEMENT_COMMAND_PATH))
        log_path = self._log_path(ticket)
        deadline = time.monotonic() + self.settings.time_limit_seconds
        made = 0
        decisions = ""
        feedback = ""
        failed_areas = ()
        review_feedback = ""
        previous_findings: tuple[Finding, ...] = ()
        for _step in range(1, self.settings.attempts + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return self._stuck(
                    ticket,
                    model=model,
                    decisions=decisions,
                    log_path=log_path,
                    worktree=worktree,
                    open_question=None,
                    failing_check="time budget exceeded",
                    attempts=made,
                )
            prompt = compose_prompt(
                ticket,
                model=model,
                branch=branch,
                command_template=command_template,
                overlay=self.overlay,
                feedback=feedback,
                failed_areas=failed_areas,
                review_feedback=review_feedback,
            )
            result = self.runner.run(
                worktree=worktree,
                model=model,
                prompt=prompt,
                timeout_seconds=int(remaining),
                config_content=builder_config,
            )
            made += 1
            self._write_log(ticket, result, step=_step, model=model)
            decisions = self.git.read_file(worktree, DECISIONS_FILE)
            open_question = extract_open_question(decisions)

            if open_question:
                return self._stuck(
                    ticket,
                    model=model,
                    decisions=decisions,
                    log_path=log_path,
                    worktree=worktree,
                    open_question=open_question,
                    failing_check="decision needed",
                    attempts=made,
                )
            if result.timed_out:
                return self._stuck(
                    ticket,
                    model=model,
                    decisions=decisions,
                    log_path=log_path,
                    worktree=worktree,
                    open_question=None,
                    failing_check="time budget exceeded",
                    attempts=made,
                )
            check = self.git.check(worktree)
            if check.passed:
                review = self._pre_pr_review(
                    ticket,
                    worktree=worktree,
                    step=_step,
                    previous=previous_findings,
                    deadline=deadline,
                )
                stuck_check = review.stuck_check(last_step=_step >= self.settings.attempts)
                if stuck_check is not None:
                    return self._stuck(
                        ticket,
                        model=model,
                        decisions=decisions,
                        log_path=log_path,
                        worktree=worktree,
                        open_question=None,
                        failing_check=stuck_check,
                        attempts=made,
                    )
                if review.blocking:
                    feedback = ""
                    failed_areas = ()
                    review_feedback = build_reviewer_feedback(review.findings, review.attack)
                    previous_findings = review.findings
                    continue
                return self._success(
                    ticket,
                    model=model,
                    branch=branch,
                    worktree=worktree,
                    decisions=decisions,
                    log_path=log_path,
                    attempts=made,
                    checked_areas=check.checked_areas,
                    skipped_areas=check.skipped_areas,
                    check_output=check.output,
                    review_lines=review.pr_lines(previous_findings),
                    suggested=review.result.suggested,
                )
            # The open review findings stay in the next prompt until a review passes.
            feedback = check.output
            failed_areas = check.failed_areas
        return self._stuck(
            ticket,
            model=model,
            decisions=decisions,
            log_path=log_path,
            worktree=worktree,
            open_question=None,
            failing_check=(
                f"check failed; {stuck_reason(open_findings[0])}"
                if (open_findings := [f for f in previous_findings if f.tag == "Important"])
                else f"step budget exceeded ({self.settings.attempts} attempts)"
            ),
            attempts=made,
        )

    def _open_suggested_tickets(
        self, ticket: Ticket, pr_number: int, suggested: tuple[Finding, ...], token: str
    ) -> None:
        """Write work the reviewer found outside the ticket's scope down as new tickets.

        The ticket is open, so a failed issue is logged and the run stays a success.
        The new tickets carry no triage label: the owner decides if they are real.
        """
        for finding in suggested:
            try:
                number = self.github.create_issue(
                    title=suggested_ticket_title(finding),
                    body=suggested_ticket_body(
                        finding, ticket_number=ticket.number, pr_number=pr_number
                    ),
                    token=token,
                )
            except Exception as exc:
                print(f"suggested ticket not opened: {short_error(exc)}", file=sys.stderr)
                continue
            print(f"#{ticket.number}: opened suggested ticket #{number}", file=sys.stderr)

    def _run_review_fix(self, fix: ReviewFix) -> TicketResult:
        ticket = fix.ticket
        model = select_model(
            ticket.labels,
            default_model=self.settings.factory_model,
            strong_model=self.settings.factory_strong_model,
        )
        branch = fix.branch
        worktree = worktree_path(self.settings.worktrees_dir, branch)
        self._remove_stale_ticket_worktree(worktree, branch)
        self.git.fetch_branch(self.settings.repo_dir, branch)
        worktree = self.git.create_worktree_from(
            self.settings.repo_dir, worktree, branch, f"origin/{branch}"
        )
        log_path = self._log_path(ticket)
        # The agent cannot run git, so the runner brings main in before the agent
        # starts. A conflict goes to a human instead of letting the agent imitate
        # a merge by editing files (PR #119).
        self.git.fetch_main(self.settings.repo_dir)
        builder_config = self._builder_config()
        if not self.git.merge_main(worktree):
            return self._stuck(
                ticket,
                model=model,
                decisions="",
                log_path=log_path,
                worktree=worktree,
                open_question=None,
                failing_check=MERGE_CONFLICT_CHECK,
                attempts=0,
            )
        # Measured after the merge, so files that main brought in are not
        # counted as the agent's changes by the protected-path check.
        base_sha = self.git.head_sha(worktree)
        self.git.write_file(worktree, DECISIONS_FILE, DECISIONS_HEADER)
        command_template = read_command_body(self.git.read_file(worktree, IMPLEMENT_COMMAND_PATH))
        deadline = time.monotonic() + self.settings.time_limit_seconds
        made = 0
        decisions = ""
        feedback = ""
        failed_areas = ()
        for _step in range(1, self.settings.attempts + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return self._stuck(
                    ticket,
                    model=model,
                    decisions=decisions,
                    log_path=log_path,
                    worktree=worktree,
                    open_question=None,
                    failing_check="time budget exceeded",
                    attempts=made,
                )
            prompt = compose_review_prompt(
                ticket,
                model=model,
                branch=branch,
                command_template=command_template,
                overlay=self.overlay,
                review_body=fix.review_body,
                comments=fix.comments,
                feedback=feedback,
                failed_areas=failed_areas,
            )
            result = self.runner.run(
                worktree=worktree,
                model=model,
                prompt=prompt,
                timeout_seconds=int(remaining),
                config_content=builder_config,
            )
            made += 1
            self._write_log(ticket, result, step=_step, model=model)
            decisions = self.git.read_file(worktree, DECISIONS_FILE)
            open_question = extract_open_question(decisions)

            if open_question:
                return self._stuck(
                    ticket,
                    model=model,
                    decisions=decisions,
                    log_path=log_path,
                    worktree=worktree,
                    open_question=open_question,
                    failing_check="decision needed",
                    attempts=made,
                )
            if result.timed_out:
                return self._stuck(
                    ticket,
                    model=model,
                    decisions=decisions,
                    log_path=log_path,
                    worktree=worktree,
                    open_question=None,
                    failing_check="time budget exceeded",
                    attempts=made,
                )
            check = self.git.check(worktree)
            if check.passed:
                return self._review_success(
                    fix,
                    model=model,
                    worktree=worktree,
                    decisions=decisions,
                    log_path=log_path,
                    base_sha=base_sha,
                    attempts=made,
                    check=check,
                )
            feedback = check.output
            failed_areas = check.failed_areas
        return self._stuck(
            ticket,
            model=model,
            decisions=decisions,
            log_path=log_path,
            worktree=worktree,
            open_question=None,
            failing_check=f"step budget exceeded ({self.settings.attempts} attempts)",
            attempts=made,
        )

    def _review_success(
        self,
        fix: ReviewFix,
        *,
        model: str,
        worktree: Path,
        decisions: str,
        log_path: Path,
        base_sha: str,
        attempts: int,
        check: CheckResult,
    ) -> TicketResult:
        ticket = fix.ticket
        # commit_all's result decides nothing: the agent may have committed on its own
        # (commit_all then has nothing left). The diff since the fix's base decides (#137).
        self.git.commit_all(worktree, f"fix: address review on #{fix.pr_number}")
        diff = self.git.diff_stats(worktree, since=base_sha)
        if not diff.files:
            return self._stuck(
                ticket,
                model=model,
                decisions=decisions,
                log_path=log_path,
                worktree=worktree,
                open_question=None,
                failing_check="no changes made for the review",
                attempts=attempts,
            )
        if touches_protected_paths(
            (f.path for f in diff.files), allow_dependencies=_allows_dependencies(ticket)
        ):
            return self._stuck(
                ticket,
                model=model,
                decisions=decisions,
                log_path=log_path,
                worktree=worktree,
                open_question=None,
                failing_check="protected path changed",
                attempts=attempts,
            )
        violation = self._dependency_scope_violation(ticket, worktree, diff, base_sha)
        if violation is not None:
            return self._stuck(
                ticket,
                model=model,
                decisions=decisions,
                log_path=log_path,
                worktree=worktree,
                open_question=None,
                failing_check=violation,
                attempts=attempts,
            )
        assert_push_target(fix.branch, ticket)
        token = self.token_provider.mint(self.settings.repo)
        # Labeled before the push: auto-merge is already on for this PR, so a failed
        # label must leave nothing pushed (#160).
        if any(is_dependency_path(f.path) for f in diff.files):
            self.github.add_pr_label(fix.pr_number, DEPS_CHANGE_LABEL, token)
        sha = self.git.head_sha(worktree)
        # The evidence names the new commit before it is pushed: a push with a stale
        # body would fail the Evidence check, and a failed edit leaves nothing pushed.
        try:
            body = self.github.pr_body(fix.pr_number, token)
            self.github.edit_pr_body(
                fix.pr_number,
                replace_verification(
                    body,
                    verification_section(
                        verified_sha=sha,
                        checked_areas=check.checked_areas,
                        skipped_areas=check.skipped_areas,
                        steps_used=attempts,
                        step_budget=self.settings.attempts,
                        check_output=check.output,
                    ),
                ),
                token,
            )
        except Exception as exc:
            print(f"PR #{fix.pr_number} body not updated: {short_error(exc)}", file=sys.stderr)
            return self._stuck(
                ticket,
                model=model,
                decisions=decisions,
                log_path=log_path,
                worktree=worktree,
                open_question=None,
                failing_check=EVIDENCE_NOT_UPDATED_CHECK,
                attempts=attempts,
            )
        self.git.push(worktree, fix.branch, token)
        self.github.comment(
            fix.pr_number,
            f"Addressed the review in {sha}; please re-review.",
            token,
        )
        info = ReviewAddressedInfo(
            pr_number=fix.pr_number,
            ticket_number=ticket.number,
            branch=fix.branch,
            model=model,
            commit_sha=sha,
            comments=len(fix.comments),
            pr_url=self._pr_url(fix.pr_number),
            ticket_url=self._ticket_url(ticket.number),
        )
        self._notify(self.notifier.send_review_addressed, info)
        return TicketResult(ticket=ticket, ok=True)

    def _success(
        self,
        ticket: Ticket,
        *,
        model: str,
        branch: str,
        worktree: Path,
        decisions: str,
        log_path: Path,
        attempts: int,
        checked_areas: tuple[Area, ...] = (),
        skipped_areas: tuple[Area, ...] = (),
        check_output: str = "",
        review_lines: tuple[str, ...] = (),
        suggested: tuple[Finding, ...] = (),
    ) -> TicketResult:
        # commit_all's result decides nothing: the agent may have committed on its own
        # (commit_all then has nothing left). The diff against origin/main decides.
        self.git.commit_all(worktree, f"feat: implement #{ticket.number} ({ticket.title})")
        diff = self.git.diff_stats(worktree)
        if not diff.files:
            return self._stuck(
                ticket,
                model=model,
                decisions=decisions,
                log_path=log_path,
                worktree=worktree,
                open_question=None,
                failing_check="no changes made for the ticket",
                attempts=attempts,
            )
        if touches_protected_paths(
            (f.path for f in diff.files), allow_dependencies=_allows_dependencies(ticket)
        ):
            return self._stuck(
                ticket,
                model=model,
                decisions=decisions,
                log_path=log_path,
                worktree=worktree,
                open_question=None,
                failing_check="protected path changed",
                attempts=attempts,
            )
        token = self.token_provider.mint(self.settings.repo)
        violation = self._dependency_scope_violation(ticket, worktree, diff, "origin/main")
        if violation is not None:
            return self._stuck(
                ticket,
                model=model,
                decisions=decisions,
                log_path=log_path,
                worktree=worktree,
                open_question=None,
                failing_check=violation,
                attempts=attempts,
            )
        assert_push_target(branch, ticket)
        # The checks ran on this tree before commit_all, so this commit is what they verified.
        verified_sha = self.git.head_sha(worktree)
        self.git.push(worktree, branch, token)
        summary = extract_summary(decisions) or ticket.title
        body = build_pr_body(
            ticket_number=ticket.number,
            summary=summary,
            model=model,
            decisions=extract_decisions(decisions),
            checked_areas=checked_areas,
            skipped_areas=skipped_areas,
            review_lines=review_lines,
            diff=diff,
            steps_used=attempts,
            step_budget=self.settings.attempts,
            verified_sha=verified_sha,
            check_output=check_output,
        )
        try:
            pr_number = self.github.create_draft_pr(
                branch=branch, title=f"#{ticket.number}: {ticket.title}", body=body, token=token
            )
        except Exception as exc:
            # The branch is already pushed. Without a PR the next run's push would be
            # non-fast-forward, so the ticket goes stuck and the remote branch is left
            # for a human to delete.
            print(f"PR for {branch} was not created: {short_error(exc)}", file=sys.stderr)
            return self._stuck(
                ticket,
                model=model,
                decisions=decisions,
                log_path=log_path,
                worktree=worktree,
                open_question=None,
                failing_check=_orphan_branch_check(branch),
                attempts=attempts,
            )
        if diff.migrations_changed:
            self.github.add_pr_label(pr_number, MIGRATION_LABEL, token)
        if any(is_dependency_path(f.path) for f in diff.files):
            self.github.add_pr_label(pr_number, DEPS_CHANGE_LABEL, token)
        self._mark_pr_ready(pr_number, token)
        self._enable_auto_merge(pr_number, token)
        self._open_suggested_tickets(ticket, pr_number, suggested, token)
        info = PrReadyInfo(
            ticket_number=ticket.number,
            ticket_title=ticket.title,
            branch=branch,
            model=model,
            files=tuple((f.path, f.added, f.deleted) for f in diff.files),
            new_tests=diff.new_tests,
            check_status="pass",
            migrations_changed=diff.migrations_changed,
            decisions=decisions,
            pr_url=self._pr_url(pr_number),
            diff_url=self._diff_url(pr_number),
            ticket_url=self._ticket_url(ticket.number),
        )
        self._notify(self.notifier.send_pr_ready, info)
        return TicketResult(ticket=ticket, ok=True)

    def _stuck(
        self,
        ticket: Ticket,
        *,
        model: str,
        decisions: str,
        log_path: Path,
        worktree: Path | None,
        open_question: str | None,
        failing_check: str,
        attempts: int,
    ) -> TicketResult:
        comment = build_issue_comment(
            open_question=open_question,
            decisions=extract_decisions(decisions),
            log_tail=_tail(log_path, LOG_TAIL_LINES),
            model=model,
            attempts=attempts,
            failing_check=failing_check,
        )
        # Held before any GitHub call: if the comment or the label fails, the ticket
        # still looks ready and must not be picked again (#160).
        self.label_holds.add(ticket.number)
        token = self.token_provider.mint(self.settings.repo)
        comment_url = self.github.comment(ticket.number, comment, token)
        label_error = None
        try:
            self.github.add_issue_label(ticket.number, NEEDS_DECISION_LABEL, token)
        except Exception as exc:
            label_error = short_error(exc)
        else:
            self.label_holds.remove(ticket.number)
        info = StuckInfo(
            ticket_number=ticket.number,
            ticket_title=ticket.title,
            model=model,
            attempts=attempts,
            failing_check=failing_check,
            open_question=open_question,
            comment_url=comment_url,
            ticket_url=self._ticket_url(ticket.number),
            log_path=str(log_path),
            label_error=label_error,
            worktree=None if worktree is None else str(worktree),
            handoff_command=(
                None
                if worktree is None
                else build_handoff_command(host=self.settings.handoff_host, worktree=str(worktree))
            ),
        )
        self._notify(self.notifier.send_stuck, info)
        return TicketResult(ticket=ticket, ok=False)

    def _mark_pr_ready(self, pr_number: int, token: str) -> None:
        """Mark the PR ready; a failure leaves it a draft and never fails the ticket."""
        try:
            result = self.github.mark_pr_ready(pr_number, token)
        except Exception as exc:
            print(
                f"PR #{pr_number} stays a draft: {short_error(exc)}",
                file=sys.stderr,
            )
            return
        if result.exit_code != 0:
            reason = result.stderr.strip() or result.stdout.strip() or f"exit {result.exit_code}"
            print(
                f"PR #{pr_number} stays a draft: {short_error(reason)}",
                file=sys.stderr,
            )

    def _enable_auto_merge(self, pr_number: int, token: str) -> None:
        """Ask GitHub to auto-merge; a repo setting that forbids it is not fatal."""
        try:
            result = self.github.enable_auto_merge(pr_number, token)
        except Exception as exc:
            print(
                f"auto-merge not enabled for PR #{pr_number}: {short_error(exc)}",
                file=sys.stderr,
            )
            return
        if result.exit_code != 0:
            reason = result.stderr.strip() or result.stdout.strip() or f"exit {result.exit_code}"
            print(
                f"auto-merge not enabled for PR #{pr_number}: {short_error(reason)}",
                file=sys.stderr,
            )

    def _notify(self, send, info) -> None:
        """Notifications are best effort; a delivery failure never changes the outcome."""
        try:
            send(info)
        except Exception as exc:
            print(f"notification failed: {type(exc).__name__}", file=sys.stderr)

    def _log_path(self, ticket: Ticket) -> Path:
        self.settings.logs_dir.mkdir(parents=True, exist_ok=True)
        return self.settings.logs_dir / f"{ticket.number}.log"

    def _write_log(
        self, ticket: Ticket, result, *, step: int, model: str, review: bool = False
    ) -> Path:
        """Append one step's output under a header; step 1 starts a fresh file.

        The stuck comment shows the tail of this file, so a run must never show
        output left over from an older run of the same ticket. A review always
        appends after the builder step it reviewed.
        """
        log_path = self._log_path(ticket)
        content = result.stdout or ""
        if result.stderr:
            content += ("\n" if content else "") + result.stderr
        if content and not content.endswith("\n"):
            content += "\n"
        label = f"review after step {step}" if review else f"step {step}"
        header = f"=== {label} (model {model}) ===\n"
        with log_path.open("w" if step == 1 and not review else "a") as log:
            log.write(header + content)
        return log_path

    def _dependency_scope_violation(
        self, ticket: Ticket, worktree: Path, diff: DiffStats, base: str
    ) -> str | None:
        """On a deps-change ticket, the reason a manifest changed beyond dependencies."""
        if not _allows_dependencies(ticket):
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

    def _builder_config(self) -> str:
        """Main's builder permissions, passed inline so the repo's opencode.json cannot
        override them (an OPENCODE_CONFIG file ranks below project config, #153)."""
        return self._inline_config(OPENCODE_CONFIG_PATH)

    def _inline_config(self, path: str) -> str:
        """An OpenCode config from origin/main, ready to pass inline.

        A blank or invalid file fails closed: OpenCode would silently skip it and run
        with the repo's own permissions. The top-level permissions are also set as the
        ``build`` agent's, because agent-level permissions are merged after top-level
        ones and the repo's opencode.json defines that agent.
        """
        text = self.git.read_ref_file(self.settings.repo_dir, "origin/main", path)
        try:
            config = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{path} on origin/main is not valid JSON") from exc
        if not isinstance(config, dict) or not isinstance(config.get("permission"), dict):
            raise RuntimeError(f"{path} on origin/main has no permission block")
        build = config.setdefault("agent", {}).setdefault("build", {})
        build["permission"] = config["permission"]
        # Pin the agent: a planted .opencode/opencode.json (project config, ranked
        # below inline) cannot switch the run to an agent with wider permissions.
        config["default_agent"] = "build"
        return json.dumps(config)

    def _pre_pr_review(
        self,
        ticket: Ticket,
        *,
        worktree: Path,
        step: int,
        previous: tuple[Finding, ...],
        deadline: float,
    ) -> PrePrReview:
        """Run the read-only reviewer once; never let it change what gets published."""
        reviewer = self.settings.factory_strong_model
        if not self.settings.pre_pr_review:
            return PrePrReview.off()
        if STRONG_MODEL_LABEL in ticket.labels:
            return PrePrReview.skipped()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return PrePrReview.failed(reviewer, "no time left in the ticket's budget")
        try:
            # The publish guard runs again later; running it here keeps the reviewer
            # off any change to protected paths, OpenCode configs included.
            changed = tuple(self.git.review_changed_files(worktree))
            if touches_protected_paths(changed, allow_dependencies=_allows_dependencies(ticket)):
                return PrePrReview.protected()
            rules = self.git.read_ref_file(self.settings.repo_dir, "origin/main", REVIEW_RULES)
            # Main's reviewer permissions, passed inline: they outrank the repo's own
            # opencode.json and .opencode/, and the worktree copy is never read.
            reviewer_config = self._inline_config(REVIEWER_CONFIG_PATH)
            diff = self.git.review_diff(worktree)
            before = self.git.worktree_fingerprint(worktree)
        except Exception as exc:
            return PrePrReview.failed(reviewer, short_error(exc))
        result = self.runner.run(
            worktree=worktree,
            model=reviewer,
            prompt=compose_reviewer_prompt(
                ticket, review_rules=rules, diff=diff, previous=previous
            ),
            timeout_seconds=int(remaining),
            config_content=reviewer_config,
            disable_project_config=True,
        )
        self._write_log(ticket, result, step=step, model=reviewer, review=True)
        if self.git.worktree_fingerprint(worktree) != before:
            return PrePrReview.tampered(reviewer)
        if result.timed_out:
            return PrePrReview.failed(reviewer, "the reviewer timed out")
        review = PrePrReview.done(reviewer, parse_review(result.stdout))
        if (
            not self.settings.review_tests
            or review.status != "done"
            or not review.result.tests
            or BACKEND not in select_areas(changed)
        ):
            return review
        attack = self._run_attack_tests(ticket, worktree, review.result.tests)
        if self.git.worktree_fingerprint(worktree) != before:
            # Fail closed: what gets published must be exactly what the builder made.
            return PrePrReview.leftover(reviewer)
        return review.with_attack(attack)

    def _run_attack_tests(
        self, ticket: Ticket, worktree: Path, tests: tuple[str, ...]
    ) -> AttackRun:
        """Place the reviewer's attack tests, run them as the agent, always remove them."""
        paths = attack_test_paths(ticket.number, len(tests))
        try:
            self.git.place_review_tests(worktree, dict(zip(paths, tests, strict=True)))
            status, output = self.git.run_review_tests(worktree, paths)
        except Exception as exc:
            status, output = "error", short_error(exc)
        finally:
            try:
                self.git.remove_review_tests(worktree, paths)
            except Exception as exc:
                # The fingerprint check right after this turns a leftover into a stuck run.
                print(f"attack tests not removed: {short_error(exc)}", file=sys.stderr)
        return AttackRun(status, output, tests)

    def _pr_url(self, pr_number: int) -> str:
        return f"https://github.com/{self.settings.repo}/pull/{pr_number}"

    def _diff_url(self, pr_number: int) -> str:
        return f"https://github.com/{self.settings.repo}/pull/{pr_number}.diff"

    def _ticket_url(self, number: int) -> str:
        return f"https://github.com/{self.settings.repo}/issues/{number}"


def _tail(path: Path, lines: int) -> str:
    if not path.exists():
        return ""
    return "\n".join(path.read_text().splitlines()[-lines:])


def read_overlay() -> str:
    candidate = Path(__file__).resolve().parent.parent.parent / "prompt.md"
    return candidate.read_text()


def _build_notifier(settings: Settings) -> Notifier:
    if settings.telegram_bot_token and settings.telegram_chat_id:
        return TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
    return NullNotifier()


def _build_token_provider(settings: Settings) -> TokenProvider:
    return GithubAppTokenProvider(
        app_id=settings.github_app_id,
        private_key=_load_private_key(settings.github_private_key),
        installation_id=settings.github_installation_id,
    )


def _load_private_key(value: str | None) -> str | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if path.is_file():
        return path.read_text()
    return value


def _build_factory(settings: Settings, *, notifier: Notifier | None = None) -> Factory:
    return Factory(
        settings,
        github=GitHub(settings.repo),
        git=Git(
            agent_user=settings.agent_user,
            agent_home=settings.agent_home,
            bot_user_id=settings.github_user_id,
        ),
        runner=AgentRunner(
            agent_user=settings.agent_user,
            agent_home=settings.agent_home,
            config_home=str(settings.agent_config_home),
        ),
        notifier=notifier or _build_notifier(settings),
        token_provider=_build_token_provider(settings),
        overlay=read_overlay(),
    )


def _startup_notifier() -> Notifier:
    """Best-effort notifier before Settings has been read successfully."""
    token = os.environ.get("FACTORY_TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("FACTORY_TELEGRAM_CHAT_ID")
    if token and chat_id:
        return TelegramNotifier(token, chat_id)
    return NullNotifier()


def _notify_failure(notifier: Notifier, reason: str) -> None:
    try:
        notifier.send_run_failed(RunFailedInfo(reason=reason))
    except Exception:
        pass


def _report_failure(notifier: Notifier, reason: str) -> int:
    _notify_failure(notifier, reason)
    print(reason)
    return 1


def preflight_main() -> int:
    """Run the real-tool preflight by hand and report the result."""
    notifier = _startup_notifier()
    try:
        settings = Settings.from_env()
        notifier = _build_notifier(settings)
        tickets = _build_factory(settings, notifier=notifier).run_preflight()
    except PreflightError as exc:
        print(f"preflight failed: {exc}")
        return 1
    except Exception as exc:
        return _report_failure(notifier, f"run failed: preflight: {short_error(exc)}")
    print(f"preflight ok ({len(tickets)} tickets listed)")
    return 0


def metrics_main() -> int:
    """Send the weekly review metrics over Telegram (``factory metrics``)."""
    notifier = _startup_notifier()
    try:
        settings = Settings.from_env()
        notifier = _build_notifier(settings)
        tokens = _build_token_provider(settings)
    except Exception as exc:
        return _report_failure(notifier, f"metrics failed: {short_error(exc)}")
    return run_metrics(
        MetricsGitHub(settings.repo, owner=OWNER_LOGIN, bot=FACTORY_BOT_LOGIN),
        notifier,
        tokens,
        repo=settings.repo,
        now=datetime.now(UTC),
    )


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] == "preflight":
        return preflight_main()
    if args and args[0] == "metrics":
        return metrics_main()
    notifier = _startup_notifier()
    phase = "startup"
    try:
        settings = Settings.from_env()
        notifier = _build_notifier(settings)
        factory = _build_factory(settings, notifier=notifier)
        phase = "run"
        results = factory.run()
    except PreflightError as exc:
        print(f"preflight failed: {exc}")
        return 1
    except RunFailed as exc:
        return _report_failure(notifier, f"run failed: {exc.phase}: {exc.detail}")
    except Exception as exc:
        return _report_failure(notifier, f"run failed: {phase}: {short_error(exc)}")
    for result in results:
        outcome = "ok" if result.ok else "stuck"
        print(f"#{result.ticket.number}: {outcome}")
    return 0


def _log_contract_skips(tickets: list[Ticket]) -> None:
    """Say once per run which ticket waits only because of an open PR's contract (#144)."""
    for ticket in tickets:
        if ticket.contract_conflicts and is_ready(replace(ticket, contract_conflicts=())):
            reasons = "; ".join(ticket.contract_conflicts)
            print(f"#{ticket.number} skipped: {reasons}", file=sys.stderr)


def _allows_dependencies(ticket: Ticket) -> bool:
    return DEPS_CHANGE_LABEL in ticket.labels


if __name__ == "__main__":
    sys.exit(main())
