"""The night factory: pick ready tickets and run them, oldest first."""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from .areas import BACKEND, Area, select_areas
from .attempt_loop import DECISIONS_FILE, Attempt, AttemptLoop
from .cleanup import cleanup_old
from .config import Settings
from .contract_diff import touched_contract_ids, undeclared_contracts
from .credentials import GithubAppTokenProvider, TokenProvider
from .decisions import DECISIONS_HEADER, extract_decisions, extract_summary
from .diff import touches_protected_paths
from .git import CheckResult, Git, verify_git_version
from .github import GitHub, GitHubError
from .holds import LabelHolds
from .isolation import verify_isolation
from .ledger import AttemptLedger
from .limit_gate import FACTORY_BOT_LOGIN, FACTORY_BRANCH_PREFIX, LimitGate
from .metrics import MetricsGitHub, run_metrics
from .model_health import REVIEWER_FAILURE_ALERT_AT, ReviewerFailures
from .models import STRONG_MODEL_LABEL, select_model
from .notify import (
    Notifier,
    NullNotifier,
    PrReadyInfo,
    ReviewAddressedInfo,
    ReviewerFailingInfo,
    ReviewSkippedInfo,
    RunFailedInfo,
    StuckInfo,
    TelegramNotifier,
    build_handoff_command,
)
from .outcomes import build_issue_comment
from .pause import PauseState
from .preflight import Preflight, PreflightError, short_error
from .prompt import compose_prompt, compose_review_prompt, read_command_body
from .publisher import Publisher, allows_dependencies
from .review_attempts import ReviewAttemptLedger
from .review_step import (
    REVIEW_RULES,
    REVIEWER_CONFIG_PATH,
    AttackRun,
    Finding,
    PrePrReview,
    attack_test_paths,
    compose_reviewer_prompt,
    inline_opencode_config,
    parse_review,
    suggested_ticket_body,
    suggested_ticket_title,
)
from .reviews import ReviewFix
from .run_home import RunHomes
from .runner import OPENCODE_CONFIG_PATH, AgentRunner
from .self_update import SelfUpdate
from .sudoers import verify_sudoers_logging
from .tickets import (
    NEEDS_DECISION_LABEL,
    Ticket,
    assert_push_target,
    branch_from_worktree_dir_name,
    branch_name,
    is_ready,
    parse_contracts,
    select_tickets,
    worktree_path,
)

IMPLEMENT_COMMAND_PATH = ".opencode/commands/implement.md"
LOG_TAIL_LINES = 30
OWNER_LOGIN = "daedraMex"
MERGE_CONFLICT_CHECK = "branch conflicts with main; a human must merge main"
EVIDENCE_NOT_UPDATED_CHECK = "PR body evidence not updated; nothing was pushed"


def _orphan_branch_check(branch: str) -> str:
    return f"remote branch {branch} has no open PR; delete it by hand so the next run can retry"


@dataclass(frozen=True)
class TicketResult:
    ticket: Ticket
    ok: bool
    # Closed mid-run by someone else (usually its own PR): not a failure (#194).
    closed: bool = False


def _outcome(result: TicketResult) -> str:
    if result.ok:
        return "ok"
    return "closed" if result.closed else "stuck"


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
        preflight_verify_cleanup_probe=None,
        preflight_clock=None,
        ledger: AttemptLedger | None = None,
        review_attempts: ReviewAttemptLedger | None = None,
        pause_state: PauseState | None = None,
        label_holds: LabelHolds | None = None,
        reviewer_failures: ReviewerFailures | None = None,
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
        self._preflight_verify_cleanup_probe = preflight_verify_cleanup_probe
        self._preflight_clock = preflight_clock
        self.ledger = ledger or AttemptLedger(settings.state_dir)
        self.review_attempts = review_attempts or ReviewAttemptLedger(settings.state_dir)
        self.pause_state = pause_state or PauseState(settings.state_dir)
        self.label_holds = label_holds or LabelHolds(settings.state_dir)
        self.reviewer_failures = reviewer_failures or ReviewerFailures(settings.state_dir)

    def run(self) -> list[TicketResult]:
        gate = self.limit_gate
        limits = gate.limits()
        if limits.paused_for is not None:
            gate.pause(limits.paused_for)
            return []
        token = limits.token
        review_fix = self._select_review_fix(token)
        capped = None if review_fix is not None else gate.open_pr_cap(limits.open_prs)
        if capped is not None:
            gate.pause(capped)
            return []
        gate.resume()
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
            if not result.ok and not result.closed:
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
            _outcome(result),
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

    def run_preflight(
        self, token: str | None = None, *, recheck_models: bool = False
    ) -> list[Ticket]:
        """Run the real-tool preflight and return the tickets it listed.

        ``factory preflight`` by hand asks every model again (``recheck_models``),
        so it proves a rotated key; hourly runs use the daily cache.
        """
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
            verify_cleanup_probe_fn=self._preflight_verify_cleanup_probe,
            runner=self.runner,
            recheck_models=recheck_models,
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
            return self._stuck_after(
                ticket,
                Attempt(0, "", failing_check=_orphan_branch_check(branch)),
                model=model,
                log_path=self._log_path(ticket),
                worktree=None,
            )
        self._remove_stale_ticket_worktree(worktree, branch)
        # Each ticket fetches its own base; it must not depend on the preflight's fetch.
        self.git.fetch_main(self.settings.repo_dir)
        builder_config = self._builder_config()
        worktree = self.git.create_worktree(self.settings.repo_dir, worktree, branch)
        self.git.write_file(worktree, DECISIONS_FILE, DECISIONS_HEADER)
        command_template = read_command_body(self.git.read_file(worktree, IMPLEMENT_COMMAND_PATH))
        log_path = self._log_path(ticket)
        attempt = self._attempt_loop().run(
            worktree=worktree,
            model=model,
            builder_config=builder_config,
            compose=lambda feedback: compose_prompt(
                ticket,
                model=model,
                branch=branch,
                command_template=command_template,
                overlay=self.overlay,
                feedback=feedback.check_output,
                failed_areas=feedback.failed_areas,
                review_feedback=feedback.review,
            ),
            write_log=lambda step, result: self._write_log(ticket, result, step=step, model=model),
            review=lambda step, previous, deadline: self._pre_pr_review(
                ticket, worktree=worktree, step=step, previous=previous, deadline=deadline
            ),
        )
        if not attempt.passed:
            return self._stuck_after(
                ticket, attempt, model=model, log_path=log_path, worktree=worktree
            )
        return self._success(
            ticket,
            model=model,
            branch=branch,
            worktree=worktree,
            decisions=attempt.decisions,
            log_path=log_path,
            attempts=attempt.attempts,
            checked_areas=attempt.check.checked_areas,
            skipped_areas=attempt.check.skipped_areas,
            check_output=attempt.check.output,
            review_lines=attempt.review.pr_lines(attempt.previous_findings),
            suggested=attempt.review.result.suggested,
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
            return self._stuck_after(
                ticket,
                Attempt(0, "", failing_check=MERGE_CONFLICT_CHECK),
                model=model,
                log_path=log_path,
                worktree=worktree,
                skip_if_closed=False,
            )
        # Measured after the merge, so files that main brought in are not
        # counted as the agent's changes by the protected-path check.
        base_sha = self.git.head_sha(worktree)
        self.git.write_file(worktree, DECISIONS_FILE, DECISIONS_HEADER)
        command_template = read_command_body(self.git.read_file(worktree, IMPLEMENT_COMMAND_PATH))
        attempt = self._attempt_loop().run(
            worktree=worktree,
            model=model,
            builder_config=builder_config,
            compose=lambda feedback: compose_review_prompt(
                ticket,
                model=model,
                branch=branch,
                command_template=command_template,
                overlay=self.overlay,
                review_body=fix.review_body,
                comments=fix.comments,
                feedback=feedback.check_output,
                failed_areas=feedback.failed_areas,
            ),
            write_log=lambda step, result: self._write_log(
                ticket, result, step=step, model=model, review_fix=True
            ),
        )
        if not attempt.passed:
            return self._stuck_after(
                ticket,
                attempt,
                model=model,
                log_path=log_path,
                worktree=worktree,
                skip_if_closed=False,
            )
        return self._review_success(
            fix,
            model=model,
            worktree=worktree,
            decisions=attempt.decisions,
            log_path=log_path,
            base_sha=base_sha,
            attempts=attempt.attempts,
            check=attempt.check,
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

        def stuck(failing_check: str) -> TicketResult:
            return self._stuck_after(
                ticket,
                Attempt(attempts, decisions, failing_check=failing_check),
                model=model,
                log_path=log_path,
                worktree=worktree,
                skip_if_closed=False,
            )

        guarded = self.publisher.guard(
            ticket,
            worktree,
            branch=fix.branch,
            message=f"fix: address review on #{fix.pr_number}",
            since=base_sha,
            empty_check="no changes made for the review",
        )
        if guarded.failing_check is not None:
            return stuck(guarded.failing_check)
        token = self.token_provider.mint(self.settings.repo)
        sha = self.publisher.update_review_pr(
            pr_number=fix.pr_number,
            branch=fix.branch,
            worktree=worktree,
            diff=guarded.diff,
            token=token,
            attempts=attempts,
            check=check,
        )
        if sha is None:
            return stuck(EVIDENCE_NOT_UPDATED_CHECK)
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
        def stuck(failing_check: str) -> TicketResult:
            return self._stuck_after(
                ticket,
                Attempt(attempts, decisions, failing_check=failing_check),
                model=model,
                log_path=log_path,
                worktree=worktree,
            )

        guarded = self.publisher.guard(
            ticket,
            worktree,
            branch=branch,
            message=f"feat: implement #{ticket.number} ({ticket.title})",
            since=None,
            empty_check="no changes made for the ticket",
        )
        if guarded.failing_check is not None:
            return stuck(guarded.failing_check)
        token = self.token_provider.mint(self.settings.repo)
        if self._closed_during_run(ticket, token):
            return TicketResult(ticket=ticket, ok=False, closed=True)
        diff = guarded.diff
        pr_number = self.publisher.open_pr(
            ticket,
            branch=branch,
            worktree=worktree,
            diff=diff,
            token=token,
            summary=extract_summary(decisions) or ticket.title,
            model=model,
            decisions=extract_decisions(decisions),
            attempts=attempts,
            checked_areas=checked_areas,
            skipped_areas=skipped_areas,
            check_output=check_output,
            review_lines=review_lines,
            undeclared_contracts=self._undeclared_contracts_for_risk(ticket, worktree),
        )
        if pr_number is None:
            return stuck(_orphan_branch_check(branch))
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

    @property
    def limit_gate(self) -> LimitGate:
        return LimitGate(
            settings=self.settings,
            github=self.github,
            token_provider=self.token_provider,
            ledger=self.ledger,
            pause_state=self.pause_state,
            notify_paused=lambda info: self._notify(self.notifier.send_paused, info),
        )

    @property
    def publisher(self) -> Publisher:
        # Built from the current git and github, which tests may swap after init.
        return Publisher(git=self.git, github=self.github, step_budget=self.settings.attempts)

    def _attempt_loop(self) -> AttemptLoop:
        return AttemptLoop(
            runner=self.runner,
            git=self.git,
            attempts=self.settings.attempts,
            time_limit_seconds=self.settings.time_limit_seconds,
        )

    def _stuck_after(
        self,
        ticket: Ticket,
        attempt: Attempt,
        *,
        model: str,
        log_path: Path,
        worktree: Path | None,
        skip_if_closed: bool = True,
    ) -> TicketResult:
        """The one stuck flow for every way a ticket or review fix stops."""
        return self._stuck(
            ticket,
            model=model,
            decisions=attempt.decisions,
            log_path=log_path,
            worktree=worktree,
            open_question=attempt.open_question,
            failing_check=attempt.failing_check or "",
            attempts=attempt.attempts,
            skip_if_closed=skip_if_closed,
        )

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
        skip_if_closed: bool = True,
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
        if skip_if_closed and self._closed_during_run(ticket, token):
            self.label_holds.remove(ticket.number)
            return TicketResult(ticket=ticket, ok=False, closed=True)
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

    def _closed_during_run(self, ticket: Ticket, token: str) -> bool:
        """A ticket its PR closed mid-run gets no comment, label or push (#194).

        An unreadable state, a timeout included, counts as open: the run goes on
        as it did before this check existed.
        """
        try:
            if self.github.is_open(ticket.number, token):
                return False
        except Exception as exc:
            print(
                f"#{ticket.number}: state unreadable, treated as open: {short_error(exc)}",
                file=sys.stderr,
            )
            return False
        print(
            f"#{ticket.number} was closed during the run; nothing was posted or pushed",
            file=sys.stderr,
        )
        return True

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
        self,
        ticket: Ticket,
        result,
        *,
        step: int,
        model: str,
        review: bool = False,
        review_fix: bool = False,
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
        if review:
            label = f"review after step {step}"
        elif review_fix:
            label = f"review fix step {step}"
        else:
            label = f"step {step}"
        header = f"=== {label} (model {model}) ===\n"
        # A review fix keeps the run it fixes: the #195 fix erased the original
        # reviewer output of 134.log (#202).
        fresh = step == 1 and not review and not review_fix
        with log_path.open("w" if fresh else "a") as log:
            log.write(header + content)
        return log_path

    def _builder_config(self) -> str:
        """Main's builder permissions, passed inline so the repo's opencode.json cannot
        override them (an OPENCODE_CONFIG file ranks below project config, #153)."""
        return self._inline_config(OPENCODE_CONFIG_PATH)

    def _inline_config(self, path: str) -> str:
        """An OpenCode config from origin/main, ready to pass inline (fails closed)."""
        text = self.git.read_ref_file(self.settings.repo_dir, "origin/main", path)
        return inline_opencode_config(text, path)

    def _undeclared_contracts(self, ticket: Ticket, worktree: Path) -> tuple[tuple[str, str], ...]:
        """Contracts the change edits that the ticket does not declare as changed (#203)."""
        touched = touched_contract_ids(self.git.contract_diff(worktree))
        return undeclared_contracts(touched, parse_contracts(ticket.body))

    def _undeclared_contracts_for_risk(
        self, ticket: Ticket, worktree: Path
    ) -> tuple[tuple[str, str], ...]:
        """The same list for the PR body; an unreadable diff is flagged, never fatal."""
        try:
            return self._undeclared_contracts(ticket, worktree)
        except Exception as exc:
            reason = f"could not read the docs/contracts/ diff ({short_error(exc)})"
            return (("docs/contracts/", f"{reason}: read it in full"),)

    def _pre_pr_review(self, ticket: Ticket, **kwargs) -> PrePrReview:
        review = self._run_pre_pr_review(ticket, **kwargs)
        self._track_reviewer(review)
        return review

    def _track_reviewer(self, review: PrePrReview) -> None:
        """Alert once when the reviewer fails twice in a row (#202).

        A failed review still opens the PR, flagged; without this, a reviewer that
        never works again looks the same as one hiccup.
        """
        if not review.from_model:
            return
        if review.status == "done":
            self.reviewer_failures.succeeded()
            return
        if self.reviewer_failures.failed() == REVIEWER_FAILURE_ALERT_AT:
            self._notify(
                self.notifier.send_reviewer_failing,
                ReviewerFailingInfo(model=review.reviewer, reason=review.reason),
            )

    def _run_pre_pr_review(
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
            if touches_protected_paths(changed, allow_dependencies=allows_dependencies(ticket)):
                return PrePrReview.protected()
            rules = self.git.read_ref_file(self.settings.repo_dir, "origin/main", REVIEW_RULES)
            # Main's reviewer permissions, passed inline: they outrank the repo's own
            # opencode.json and .opencode/, and the worktree copy is never read.
            reviewer_config = self._inline_config(REVIEWER_CONFIG_PATH)
            diff = self.git.review_diff(worktree)
            undeclared = self._undeclared_contracts(ticket, worktree)
            before = self.git.worktree_fingerprint(worktree)
        except Exception as exc:
            return PrePrReview.failed(reviewer, short_error(exc))
        result = self.runner.run(
            worktree=worktree,
            model=reviewer,
            prompt=compose_reviewer_prompt(
                ticket,
                review_rules=rules,
                diff=diff,
                previous=previous,
                undeclared_contracts=undeclared,
            ),
            timeout_seconds=int(remaining),
            config_content=reviewer_config,
            disable_project_config=True,
        )
        self._write_log(ticket, result, step=step, model=reviewer, review=True)
        if self.git.worktree_fingerprint(worktree) != before:
            return PrePrReview.tampered(reviewer)
        if result.timed_out:
            return PrePrReview.model_failed(reviewer, "the reviewer timed out")
        if not result.stdout.strip():
            # A model without a provider login prints nothing at all (#202).
            said = " ".join(result.stderr.split())[:200]
            reason = f"the reviewer produced no output (exit {result.exit_code})"
            return PrePrReview.model_failed(reviewer, f"{reason}: {said}" if said else reason)
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
            run_homes=_build_run_homes(settings),
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


def _build_run_homes(settings: Settings) -> RunHomes | None:
    """Fresh OpenCode homes (#158) whenever the agent is its own user."""
    if not settings.agent_user:
        return None
    return RunHomes(
        homes_dir=settings.agent_homes_dir,
        auth_file=settings.agent_auth_file,
        agent_user=settings.agent_user,
        worktrees_dir=settings.worktrees_dir,
    )


def _build_self_update(settings: Settings) -> SelfUpdate:
    return SelfUpdate(repo_dir=settings.repo_dir, tools_dir=settings.repo_dir / "tools" / "factory")


def _start(settings: Settings, notifier: Notifier) -> tuple[str, int | None]:
    """Move the factory's checkout to origin/main (#215); may re-exec this process.

    Returns the short commit the factory runs ("" with self-update off), and an
    exit code when the run must stop.
    """
    updater = _build_self_update(settings)
    if not settings.self_update:
        try:
            commit = updater.head()[:7]  # still named: testing a branch is when it matters
        except Exception:
            commit = ""
        if hasattr(notifier, "commit"):
            notifier.commit = commit
        return commit, None
    outcome = updater.run()
    commit = outcome.head[:7]
    if hasattr(notifier, "commit"):
        notifier.commit = commit
    if outcome.status == "blocked":
        return commit, _report_failure(notifier, outcome.reason)
    return commit, None


def preflight_main(settings: Settings, notifier: Notifier, commit: str = "") -> int:
    """Run the real-tool preflight by hand and report the result."""
    try:
        tickets = _build_factory(settings, notifier=notifier).run_preflight(recheck_models=True)
    except PreflightError as exc:
        print(f"preflight failed: {exc}")
        return 1
    except Exception as exc:
        return _report_failure(notifier, f"run failed: preflight: {short_error(exc)}")
    where = f" at {commit}" if commit else ""
    print(f"preflight ok{where} ({len(tickets)} tickets listed)")
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
    if args and args[0] == "metrics":
        return metrics_main()
    notifier = _startup_notifier()
    try:
        settings = Settings.from_env()
        notifier = _build_notifier(settings)
        commit, stop = _start(settings, notifier)
    except Exception as exc:
        return _report_failure(notifier, f"run failed: startup: {short_error(exc)}")
    if stop is not None:
        return stop
    if args and args[0] == "preflight":
        return preflight_main(settings, notifier, commit)
    phase = "startup"
    try:
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
        outcome = _outcome(result)
        print(f"#{result.ticket.number}: {outcome}")
    return 0


def _log_contract_skips(tickets: list[Ticket]) -> None:
    """Say once per run which ticket waits only because of an open PR's contract (#144)."""
    for ticket in tickets:
        if ticket.contract_conflicts and is_ready(replace(ticket, contract_conflicts=())):
            reasons = "; ".join(ticket.contract_conflicts)
            print(f"#{ticket.number} skipped: {reasons}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
