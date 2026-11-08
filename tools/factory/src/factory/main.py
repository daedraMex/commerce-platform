"""The night factory: pick ready tickets and run them, oldest first."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .cleanup import cleanup_old
from .config import Settings
from .credentials import GithubAppTokenProvider, TokenProvider
from .decisions import DECISIONS_HEADER, extract_decisions, extract_open_question, extract_summary
from .diff import touches_protected_paths
from .git import Git
from .github import GitHub
from .isolation import sensitive_paths, verify_isolation, write_protected_paths
from .models import select_model
from .notify import (
    Notifier,
    NullNotifier,
    PrReadyInfo,
    StuckInfo,
    TelegramNotifier,
    build_handoff_command,
)
from .outcomes import build_issue_comment
from .pr_body import build_pr_body
from .prompt import compose_prompt, read_command_body
from .runner import AgentRunner
from .tickets import Ticket, branch_name, select_tickets

DECISIONS_FILE = "DECISIONS.md"
IMPLEMENT_COMMAND_PATH = ".opencode/commands/implement.md"
NEEDS_DECISION_LABEL = "needs-decision"
MIGRATION_LABEL = "migration"
LOG_TAIL_LINES = 30


@dataclass(frozen=True)
class TicketResult:
    ticket: Ticket
    ok: bool


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
    ):
        self.settings = settings
        self.github = github
        self.git = git
        self.runner = runner
        self.notifier = notifier
        self.token_provider = token_provider
        self.overlay = overlay

    def run(self) -> list[TicketResult]:
        cleanup_old(self.settings.worktrees_dir, keep_days=self.settings.keep_days)
        cleanup_old(self.settings.logs_dir, keep_days=self.settings.keep_days)
        token = self.token_provider.mint(self.settings.repo)
        tickets = select_tickets(
            self.github.list_tickets(token), max_tickets=self.settings.max_tickets
        )
        results: list[TicketResult] = []
        for ticket in tickets:
            result = self._run_ticket(ticket)
            results.append(result)
            if not result.ok:
                break
        return results

    def _run_ticket(self, ticket: Ticket) -> TicketResult:
        model = select_model(
            ticket.labels,
            default_model=self.settings.factory_model,
            strong_model=self.settings.factory_strong_model,
        )
        branch = branch_name(ticket)
        worktree = self.git.create_worktree(
            self.settings.repo_dir, self.settings.worktrees_dir / branch, branch
        )
        self.git.write_file(worktree, DECISIONS_FILE, DECISIONS_HEADER)
        command_template = read_command_body(self.git.read_file(worktree, IMPLEMENT_COMMAND_PATH))
        log_path = self._log_path(ticket)
        deadline = time.monotonic() + self.settings.time_limit_seconds
        made = 0
        decisions = ""
        feedback = ""
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
            )
            result = self.runner.run(
                worktree=worktree,
                model=model,
                prompt=prompt,
                timeout_seconds=int(remaining),
            )
            made += 1
            self._write_log(ticket, result)
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
            passed, check_output = self.git.check(worktree)
            if passed:
                return self._success(
                    ticket,
                    model=model,
                    branch=branch,
                    worktree=worktree,
                    decisions=decisions,
                    log_path=log_path,
                    attempts=made,
                )
            feedback = check_output
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
        self.git.commit_all(worktree, f"feat: implement #{ticket.number} ({ticket.title})")
        diff = self.git.diff_stats(worktree)
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
        pr_number = self.github.create_draft_pr(
            branch=branch, title=f"#{ticket.number}: {ticket.title}", body=body, token=token
        )
        if diff.migrations_changed:
            self.github.add_pr_label(pr_number, MIGRATION_LABEL, token)
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
        self.notifier.send_pr_ready(info)
        return TicketResult(ticket=ticket, ok=True)

    def _stuck(
        self,
        ticket: Ticket,
        *,
        model: str,
        decisions: str,
        log_path: Path,
        worktree: Path,
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
            worktree=str(worktree),
            handoff_command=build_handoff_command(
                host=self.settings.handoff_host, worktree=str(worktree)
            ),
        )
        self.notifier.send_stuck(info)
        return TicketResult(ticket=ticket, ok=False)

    def _log_path(self, ticket: Ticket) -> Path:
        self.settings.logs_dir.mkdir(parents=True, exist_ok=True)
        return self.settings.logs_dir / f"{ticket.number}.log"

    def _write_log(self, ticket: Ticket, result) -> Path:
        log_path = self._log_path(ticket)
        content = result.stdout or ""
        if result.stderr:
            content += ("\n" if content else "") + result.stderr
        log_path.write_text(content)
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


def main(argv: list[str] | None = None) -> int:
    settings = Settings.from_env()
    verify_isolation(
        agent_user=settings.agent_user,
        paths=sensitive_paths(settings),
        write_paths=write_protected_paths(settings),
    )
    overlay = read_overlay()
    factory = Factory(
        settings,
        github=GitHub(settings.repo),
        git=Git(
            agent_user=settings.agent_user,
            agent_home=settings.agent_home,
        ),
        runner=AgentRunner(
            agent_user=settings.agent_user,
            agent_home=settings.agent_home,
            provider_env_vars=settings.provider_env_vars,
        ),
        notifier=_build_notifier(settings),
        token_provider=_build_token_provider(settings),
        overlay=overlay,
    )
    results = factory.run()
    for result in results:
        outcome = "ok" if result.ok else "stuck"
        print(f"#{result.ticket.number}: {outcome}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
