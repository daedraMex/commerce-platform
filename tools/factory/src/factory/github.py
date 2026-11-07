"""GitHub operations, wrapped around the ``gh`` CLI and faked in tests."""

from __future__ import annotations

import json
import re

from .shell import RunCommand, run_command
from .tickets import Ticket, parse_blocked_by

_CLOSES_RE = re.compile(r"(?:Closes|Part of)\s+#(\d+)", re.IGNORECASE)


class GitHub:
    def __init__(self, repo: str, run: RunCommand = run_command):
        self.repo = repo
        self._run = run

    def list_tickets(self) -> list[Ticket]:
        raw = self._run(
            [
                "gh",
                "issue",
                "list",
                "--repo",
                self.repo,
                "--state",
                "open",
                "--label",
                "ready-for-agent",
                "--json",
                "number,title,body,labels",
            ],
            cwd="/",
            timeout=120,
        ).stdout
        tickets = [self._to_ticket(obj) for obj in json.loads(raw)]
        return self._resolve(tickets)

    def create_draft_pr(self, *, branch: str, title: str, body: str) -> int:
        result = self._run(
            [
                "gh",
                "pr",
                "create",
                "--repo",
                self.repo,
                "--base",
                "main",
                "--head",
                branch,
                "--draft",
                "--title",
                title,
                "--body",
                body,
            ],
            cwd="/",
            timeout=120,
        )
        if result.exit_code != 0:
            raise RuntimeError(f"gh pr create failed: {result.stderr.strip()}")
        # gh prints the PR URL on the last line; the number is its trailing segment.
        url = result.stdout.strip().splitlines()[-1].strip()
        return int(url.rstrip("/").rsplit("/", 1)[-1])

    def add_issue_label(self, number: int, label: str) -> None:
        self._run(
            ["gh", "issue", "edit", str(number), "--repo", self.repo, "--add-label", label],
            cwd="/",
            timeout=120,
        )

    def add_pr_label(self, number: int, label: str) -> None:
        self._run(
            ["gh", "pr", "edit", str(number), "--repo", self.repo, "--add-label", label],
            cwd="/",
            timeout=120,
        )

    def comment(self, number: int, body: str) -> str:
        """Post a comment and return its URL so it can be linked from a notification."""
        result = self._run(
            [
                "gh",
                "api",
                f"repos/{self.repo}/issues/{number}/comments",
                "--method",
                "POST",
                "-f",
                f"body={body}",
                "--jq",
                ".html_url",
            ],
            cwd="/",
            timeout=120,
        )
        return result.stdout.strip()

    def _to_ticket(self, obj: dict) -> Ticket:
        return Ticket(
            number=int(obj["number"]),
            title=obj.get("title", ""),
            body=obj.get("body", "") or "",
            labels=frozenset(obj.get("labels", [])),
        )

    def _resolve(self, tickets: list[Ticket]) -> list[Ticket]:
        """Resolve open blockers and existing PRs; keep only the resolved tickets."""
        open_pr_numbers = self._open_pr_ticket_numbers()
        resolved: list[Ticket] = []
        for ticket in tickets:
            blocked_by = tuple(n for n in self._open_blockers(ticket.body) if self._is_open(n))
            resolved.append(
                Ticket(
                    number=ticket.number,
                    title=ticket.title,
                    body=ticket.body,
                    labels=ticket.labels,
                    blocked_by=blocked_by,
                    has_open_pr=ticket.number in open_pr_numbers,
                )
            )
        return resolved

    def _open_blockers(self, body: str) -> list[int]:
        # Native dependencies are the live gate; the "Blocked by:" line is the fallback.
        return list(parse_blocked_by(body))

    def _is_open(self, number: int) -> bool:
        result = self._run(
            ["gh", "issue", "view", str(number), "--repo", self.repo, "--json", "state"],
            cwd="/",
            timeout=120,
        )
        try:
            return json.loads(result.stdout).get("state") == "OPEN"
        except (json.JSONDecodeError, AttributeError):
            return False

    def _open_pr_ticket_numbers(self) -> set[int]:
        result = self._run(
            ["gh", "pr", "list", "--repo", self.repo, "--state", "open", "--json", "body"],
            cwd="/",
            timeout=120,
        )
        numbers: set[int] = set()
        try:
            for obj in json.loads(result.stdout):
                for match in _CLOSES_RE.findall(obj.get("body", "") or ""):
                    numbers.add(int(match))
        except json.JSONDecodeError:
            pass
        return numbers
