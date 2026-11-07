"""The night factory: pick ready tickets and run them, oldest first."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from .cleanup import cleanup_old
from .config import Settings
from .decisions import DECISIONS_HEADER, extract_decisions, extract_open_question, extract_summary
from .git import Git
from .github import GitHub
from .models import select_model
from .notify import Notifier, NullNotifier, PrReadyInfo, StuckInfo, TelegramNotifier
from .outcomes import build_issue_comment
from .pr_body import build_pr_body
from .prompt import compose_prompt
from .runner import AgentRunner
from .tickets import Ticket, branch_name, select_tickets

DECISIONS_FILE = "DECISIONS.md"
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
        prompt_template: str,
    ):
        self.settings = settings
        self.github = github
        self.git = git
        self.runner = runner
        self.notifier = notifier
        self.prompt_template = prompt_template

    def run(self) -> list[TicketResult]:
        cleanup_old(self.settings.worktrees_dir, keep_days=self.settings.keep_days)
        cleanup_old(self.settings.logs_dir, keep_days=self.settings.keep_days)
        tickets = select_tickets(self.github.list_tickets(), max_tickets=self.settings.max_tickets)
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
        prompt = compose_prompt(
            ticket,
            model=model,
            branch=branch,
            max_attempts=self.settings.attempts,
            template=self.prompt_template,
        )
        result = self.runner.run(
            worktree=worktree,
            model=model,
            prompt=prompt,
            timeout_seconds=self.settings.time_limit_seconds,
        )
        log_path = self._write_log(ticket, result)
        decisions = self.git.read_file(worktree, DECISIONS_FILE)
        open_question = extract_open_question(decisions)

        if open_question:
            return self._stuck(
                ticket,
                model=model,
                decisions=decisions,
                log_path=log_path,
                open_question=open_question,
                failing_check="decision needed",
            )
        if result.timed_out:
            return self._stuck(
                ticket,
                model=model,
                decisions=decisions,
                log_path=log_path,
                open_question=None,
                failing_check=f"timeout ({self.settings.time_limit_seconds}s)",
            )
        if not self.git.check_passed(worktree):
            return self._stuck(
                ticket,
                model=model,
                decisions=decisions,
                log_path=log_path,
                open_question=None,
                failing_check="scripts/check.sh",
            )
        return self._success(
            ticket, model=model, branch=branch, worktree=worktree, decisions=decisions
        )

    def _success(
        self,
        ticket: Ticket,
        *,
        model: str,
        branch: str,
        worktree: Path,
        decisions: str,
    ) -> TicketResult:
        self.git.commit_all(worktree, f"feat: implement #{ticket.number} ({ticket.title})")
        diff = self.git.diff_stats(worktree)
        self.git.push(worktree, branch)
        summary = extract_summary(decisions) or ticket.title
        body = build_pr_body(
            ticket_number=ticket.number,
            summary=summary,
            model=model,
            decisions=extract_decisions(decisions),
        )
        pr_number = self.github.create_draft_pr(
            branch=branch, title=f"#{ticket.number}: {ticket.title}", body=body
        )
        if diff.migrations_changed:
            self.github.add_pr_label(pr_number, MIGRATION_LABEL)
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
        open_question: str | None,
        failing_check: str,
    ) -> TicketResult:
        comment = build_issue_comment(
            open_question=open_question,
            decisions=extract_decisions(decisions),
            log_tail=_tail(log_path, LOG_TAIL_LINES),
            model=model,
            attempts=self.settings.attempts,
            failing_check=failing_check,
        )
        comment_url = self.github.comment(ticket.number, comment)
        self.github.add_issue_label(ticket.number, NEEDS_DECISION_LABEL)
        info = StuckInfo(
            ticket_number=ticket.number,
            ticket_title=ticket.title,
            model=model,
            attempts=self.settings.attempts,
            failing_check=failing_check,
            open_question=open_question,
            comment_url=comment_url,
            ticket_url=self._ticket_url(ticket.number),
            log_path=str(log_path),
        )
        self.notifier.send_stuck(info)
        return TicketResult(ticket=ticket, ok=False)

    def _write_log(self, ticket: Ticket, result) -> Path:
        self.settings.logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.settings.logs_dir / f"{ticket.number}.log"
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


def read_prompt_template() -> str:
    candidate = Path(__file__).resolve().parent.parent.parent / "prompt.md"
    return candidate.read_text()


def _build_notifier(settings: Settings) -> Notifier:
    if settings.telegram_bot_token and settings.telegram_chat_id:
        return TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
    return NullNotifier()


def main(argv: list[str] | None = None) -> int:
    settings = Settings.from_env()
    prompt_template = read_prompt_template()
    factory = Factory(
        settings,
        github=GitHub(settings.repo),
        git=Git(),
        runner=AgentRunner(),
        notifier=_build_notifier(settings),
        prompt_template=prompt_template,
    )
    results = factory.run()
    for result in results:
        outcome = "ok" if result.ok else "stuck"
        print(f"#{result.ticket.number}: {outcome}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
