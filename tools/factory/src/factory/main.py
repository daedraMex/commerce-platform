"""The night factory: pick ready tickets and run them, oldest first."""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .cleanup import cleanup_old
from .config import Settings
from .credentials import GithubAppTokenProvider, TokenProvider
from .decisions import DECISIONS_HEADER, extract_decisions, extract_open_question, extract_summary
from .diff import touches_protected_paths
from .git import Git, verify_git_version
from .github import GitHub, GitHubError
from .isolation import verify_isolation
from .ledger import AttemptLedger
from .models import select_model
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
from .pr_body import build_pr_body
from .preflight import Preflight, PreflightError, short_error
from .prompt import compose_prompt, compose_review_prompt, read_command_body
from .review_attempts import ReviewAttemptLedger
from .reviews import ReviewFix
from .runner import AgentRunner
from .sudoers import verify_sudoers_logging
from .tickets import (
    Ticket,
    branch_from_worktree_dir_name,
    branch_name,
    select_tickets,
    worktree_path,
)

DECISIONS_FILE = "DECISIONS.md"
IMPLEMENT_COMMAND_PATH = ".opencode/commands/implement.md"
NEEDS_DECISION_LABEL = "needs-decision"
MIGRATION_LABEL = "migration"
LOG_TAIL_LINES = 30
FACTORY_BOT_LOGIN = "xolo-bot"
FACTORY_BRANCH_PREFIX = "nf/"
OWNER_LOGIN = "daedraMex"
MERGE_CONFLICT_CHECK = "branch conflicts with main; a human must merge main"


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
        for ticket in select_tickets(tickets, max_tickets=self.settings.max_tickets):
            result = self._execute(
                ticket,
                lambda t=ticket: self._run_ticket(t, token),
                f"#{ticket.number} {ticket.title}",
            )
            results.append(result)
            if not result.ok:
                break
        return results

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
        worktree = self.git.create_worktree(self.settings.repo_dir, worktree, branch)
        self.git.write_file(worktree, DECISIONS_FILE, DECISIONS_HEADER)
        command_template = read_command_body(self.git.read_file(worktree, IMPLEMENT_COMMAND_PATH))
        log_path = self._log_path(ticket)
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
            prompt = compose_prompt(
                ticket,
                model=model,
                branch=branch,
                command_template=command_template,
                overlay=self.overlay,
                feedback=feedback,
                failed_areas=failed_areas,
            )
            result = self.runner.run(
                worktree=worktree,
                model=model,
                prompt=prompt,
                timeout_seconds=int(remaining),
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
                return self._success(
                    ticket,
                    model=model,
                    branch=branch,
                    worktree=worktree,
                    decisions=decisions,
                    log_path=log_path,
                    attempts=made,
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
    ) -> TicketResult:
        ticket = fix.ticket
        if not self.git.commit_all(worktree, f"fix: address review on #{fix.pr_number}"):
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
        diff = self.git.diff_stats_since(worktree, base_sha)
        if touches_protected_paths(f.path for f in diff.files):
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
        self.git.push(worktree, fix.branch, token)
        sha = self.git.head_sha(worktree)
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
    ) -> TicketResult:
        if not self.git.commit_all(worktree, f"feat: implement #{ticket.number} ({ticket.title})"):
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
        if touches_protected_paths(f.path for f in diff.files):
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
        self.git.push(worktree, branch, token)
        summary = extract_summary(decisions) or ticket.title
        body = build_pr_body(
            ticket_number=ticket.number,
            summary=summary,
            model=model,
            decisions=extract_decisions(decisions),
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
        self._mark_pr_ready(pr_number, token)
        self._enable_auto_merge(pr_number, token)
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
        token = self.token_provider.mint(self.settings.repo)
        comment_url = self.github.comment(ticket.number, comment, token)
        self.github.add_issue_label(ticket.number, NEEDS_DECISION_LABEL, token)
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

    def _write_log(self, ticket: Ticket, result, *, step: int, model: str) -> Path:
        """Append one step's output under a header; step 1 starts a fresh file.

        The stuck comment shows the tail of this file, so a run must never show
        output left over from an older run of the same ticket.
        """
        log_path = self._log_path(ticket)
        content = result.stdout or ""
        if result.stderr:
            content += ("\n" if content else "") + result.stderr
        if content and not content.endswith("\n"):
            content += "\n"
        header = f"=== step {step} (model {model}) ===\n"
        with log_path.open("w" if step == 1 else "a") as log:
            log.write(header + content)
        return log_path

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


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] == "preflight":
        return preflight_main()
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


if __name__ == "__main__":
    sys.exit(main())
