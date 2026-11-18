"""GitHub operations, wrapped around the ``gh`` CLI and faked in tests."""

from __future__ import annotations

import json
import re
from datetime import datetime

from .reviews import CHANGES_REQUESTED, ReviewComment, ReviewFix
from .shell import CommandResult, RunCommand, run_command
from .tickets import Contracts, Ticket, parse_blocked_by, parse_contracts

_CLOSES_RE = re.compile(r"(?:Closes|Part of)\s+#(\d+)", re.IGNORECASE)


class GitHubError(RuntimeError):
    """Raised when a gh call cannot be trusted to report the repo state."""


class GitHub:
    def __init__(self, repo: str, run: RunCommand = run_command):
        self.repo = repo
        self._run = run

    def list_tickets(self, token: str | None = None) -> list[Ticket]:
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
            env=_gh_env(token),
        ).stdout
        tickets = [self._to_ticket(obj) for obj in json.loads(raw)]
        return self._resolve(tickets, token)

    def create_draft_pr(self, *, branch: str, title: str, body: str, token: str) -> int:
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
            env={"GH_TOKEN": token},
        )
        if result.exit_code != 0:
            raise RuntimeError(f"gh pr create failed: {result.stderr.strip()}")
        # gh prints the PR URL on the last line; the number is its trailing segment.
        url = result.stdout.strip().splitlines()[-1].strip()
        return int(url.rstrip("/").rsplit("/", 1)[-1])

    def has_open_pr_for_branch(self, branch: str, token: str) -> bool:
        """Return True when an open PR has ``branch`` as its head branch."""
        result = self._run(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                self.repo,
                "--head",
                branch,
                "--state",
                "open",
                "--json",
                "number",
            ],
            cwd="/",
            timeout=120,
            env=_gh_env(token),
        )
        if result.exit_code != 0:
            raise GitHubError(f"gh pr list failed: {result.stderr.strip() or result.exit_code}")
        try:
            prs = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise GitHubError("gh pr list returned invalid JSON") from exc
        if not isinstance(prs, list):
            raise GitHubError("gh pr list returned an unexpected JSON shape")
        return bool(prs)

    def mark_pr_ready(self, number: int, token: str) -> CommandResult:
        """Mark the PR ready for review.

        Returns the raw result instead of raising: a failed ``gh pr ready``
        leaves the PR as a draft, which is not a factory failure because the
        pull request already exists.
        """
        return self._run(
            ["gh", "pr", "ready", str(number), "--repo", self.repo],
            cwd="/",
            timeout=120,
            env={"GH_TOKEN": token},
        )

    def enable_auto_merge(self, number: int, token: str) -> CommandResult:
        """Ask GitHub to merge once checks pass and the owner approves.

        Returns the raw result instead of raising: a repository without
        auto-merge enabled is not a factory failure, so the caller logs why
        and keeps the successful run.
        """
        return self._run(
            [
                "gh",
                "pr",
                "merge",
                str(number),
                "--repo",
                self.repo,
                "--auto",
                "--merge",
            ],
            cwd="/",
            timeout=120,
            env={"GH_TOKEN": token},
        )

    def count_open_factory_prs(
        self,
        *,
        author: str,
        branch_prefix: str = "nf/",
        token: str | None = None,
    ) -> int:
        """Count open PRs by ``author`` whose branch starts with ``branch_prefix``.

        Draft and ready PRs both count. ``gh`` reports app logins as
        ``app/<slug>`` (and some bot logins with a ``[bot]`` suffix), so
        normalize both forms before comparing. A failed call or unparseable
        output raises instead of reporting zero, because a wrong zero would
        silently bypass the cap.
        """
        result = self._run(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                self.repo,
                "--state",
                "open",
                "--limit",
                "1000",
                "--json",
                "number,isDraft,headRefName,author",
            ],
            cwd="/",
            timeout=120,
            env=_gh_env(token),
        )
        if result.exit_code != 0:
            raise GitHubError(f"gh pr list failed: {result.stderr.strip() or result.exit_code}")
        try:
            prs = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise GitHubError("gh pr list returned invalid JSON") from exc
        if not isinstance(prs, list):
            raise GitHubError("gh pr list returned an unexpected JSON shape")
        return sum(
            1
            for pr in prs
            if _same_login((pr.get("author") or {}).get("login", ""), author)
            and str(pr.get("headRefName", "")).startswith(branch_prefix)
        )

    def list_review_fixes(
        self,
        *,
        author: str,
        owner: str,
        branch_prefix: str = "nf/",
        attempted_review_ids: frozenset[str] = frozenset(),
        token: str | None = None,
    ) -> list[ReviewFix]:
        """Return open factory PRs whose latest owner review asks for changes.

        A PR is a candidate only when its latest review by ``owner`` is
        ``CHANGES_REQUESTED`` and no commit landed after that review. Reviews
        in ``attempted_review_ids`` are never retried. Results are ordered
        oldest review first. Any failed ``gh`` call raises, so the caller can
        skip review fixes and continue.
        """
        result = self._run(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                self.repo,
                "--state",
                "open",
                "--limit",
                "1000",
                "--json",
                "number,headRefName,author,body",
            ],
            cwd="/",
            timeout=120,
            env=_gh_env(token),
        )
        if result.exit_code != 0:
            raise GitHubError(f"gh pr list failed: {result.stderr.strip() or result.exit_code}")
        prs = self._json_list(result.stdout, "gh pr list")

        fixes: list[ReviewFix] = []
        for pr in prs:
            if not _same_login((pr.get("author") or {}).get("login", ""), author):
                continue
            branch = str(pr.get("headRefName", ""))
            if not branch.startswith(branch_prefix):
                continue
            number = int(pr["number"])
            detail = self._reviews_and_commits(number, token)
            review, submitted_at = _latest_owner_review(detail.get("reviews") or [], owner)
            if review is None or submitted_at is None:
                continue
            review_id = str(review.get("id") or "")
            if not review_id or review_id in attempted_review_ids:
                continue
            if review.get("state") != CHANGES_REQUESTED:
                continue
            if _commit_after(detail.get("commits") or [], submitted_at):
                continue
            ticket_number = _ticket_number(pr.get("body", "") or "")
            if ticket_number is None:
                continue
            ticket = self.get_ticket(ticket_number, token)
            comments = self._review_comments(number, review_id, token)
            fixes.append(
                ReviewFix(
                    review_id=review_id,
                    pr_number=number,
                    branch=branch,
                    ticket=ticket,
                    review_body=review.get("body", "") or "",
                    comments=comments,
                    submitted_at=submitted_at,
                )
            )
        fixes.sort(key=lambda fix: fix.submitted_at)
        return fixes

    def get_ticket(self, number: int, token: str | None = None) -> Ticket:
        """Read one issue, for a review fix that is not a fresh ticket."""
        result = self._run(
            [
                "gh",
                "issue",
                "view",
                str(number),
                "--repo",
                self.repo,
                "--json",
                "number,title,body,labels",
            ],
            cwd="/",
            timeout=120,
            env=_gh_env(token),
        )
        if result.exit_code != 0:
            raise GitHubError(f"gh issue view failed: {result.stderr.strip() or result.exit_code}")
        try:
            obj = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise GitHubError("gh issue view returned invalid JSON") from exc
        if not isinstance(obj, dict):
            raise GitHubError("gh issue view returned an unexpected JSON shape")
        return self._to_ticket(obj)

    def _reviews_and_commits(self, number: int, token: str | None) -> dict:
        return {
            "reviews": self._reviews(number, token),
            "commits": self._commits(number, token),
        }

    def _reviews(self, number: int, token: str | None) -> list[dict]:
        """Read reviews from REST, whose ``id`` is the database id comments need.

        The GraphQL ``id`` is a node id (``PRR_...``), which the REST comments
        route rejects with a 404, so reviews must come from the REST API.
        """
        result = self._run(
            [
                "gh",
                "api",
                "--paginate",
                f"repos/{self.repo}/pulls/{number}/reviews",
            ],
            cwd="/",
            timeout=120,
            env=_gh_env(token),
        )
        if result.exit_code != 0:
            raise GitHubError(f"gh api reviews failed: {result.stderr.strip() or result.exit_code}")
        return self._json_pages(result.stdout, "gh api reviews")

    def _commits(self, number: int, token: str | None) -> list[dict]:
        result = self._run(
            [
                "gh",
                "pr",
                "view",
                str(number),
                "--repo",
                self.repo,
                "--json",
                "commits",
            ],
            cwd="/",
            timeout=120,
            env=_gh_env(token),
        )
        if result.exit_code != 0:
            raise GitHubError(f"gh pr view failed: {result.stderr.strip() or result.exit_code}")
        try:
            detail = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise GitHubError("gh pr view returned invalid JSON") from exc
        if not isinstance(detail, dict):
            raise GitHubError("gh pr view returned an unexpected JSON shape")
        commits = detail.get("commits") or []
        if not isinstance(commits, list):
            raise GitHubError("gh pr view returned an unexpected commits shape")
        return commits

    def _review_comments(
        self,
        number: int,
        review_id: str | None,
        token: str | None,
    ) -> tuple[ReviewComment, ...]:
        if not review_id:
            return ()
        result = self._run(
            [
                "gh",
                "api",
                "--paginate",
                f"repos/{self.repo}/pulls/{number}/reviews/{review_id}/comments",
                "--jq",
                ".[] | {path, line, original_line, body}",
            ],
            cwd="/",
            timeout=120,
            env=_gh_env(token),
        )
        if result.exit_code != 0:
            raise GitHubError(
                f"gh api review comments failed: {result.stderr.strip() or result.exit_code}"
            )
        comments: list[ReviewComment] = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise GitHubError("gh api review comments returned invalid JSON") from exc
            line_number = obj.get("line")
            if line_number is None:
                line_number = obj.get("original_line")
            comments.append(
                ReviewComment(
                    path=obj.get("path", "") or "",
                    line=line_number,
                    body=obj.get("body", "") or "",
                )
            )
        return tuple(comments)

    def _json_list(self, text: str, source: str) -> list[dict]:
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise GitHubError(f"{source} returned invalid JSON") from exc
        if not isinstance(value, list):
            raise GitHubError(f"{source} returned an unexpected JSON shape")
        return value

    def _json_pages(self, text: str, source: str) -> list[dict]:
        """Flatten a ``gh api --paginate`` stream of JSON arrays."""
        decoder = json.JSONDecoder()
        values: list[dict] = []
        index = 0
        length = len(text)
        while index < length:
            while index < length and text[index].isspace():
                index += 1
            if index >= length:
                break
            try:
                value, index = decoder.raw_decode(text, index)
            except json.JSONDecodeError as exc:
                raise GitHubError(f"{source} returned invalid JSON") from exc
            if not isinstance(value, list):
                raise GitHubError(f"{source} returned an unexpected JSON shape")
            values.extend(value)
        return values

    def add_issue_label(self, number: int, label: str, token: str) -> None:
        self._add_label("issue", number, label, token)

    def add_pr_label(self, number: int, label: str, token: str) -> None:
        self._add_label("pr", number, label, token)

    def _add_label(self, kind: str, number: int, label: str, token: str) -> None:
        """Add a label, or raise: a missing label must never pass silently (#160)."""
        result = self._run(
            ["gh", kind, "edit", str(number), "--repo", self.repo, "--add-label", label],
            cwd="/",
            timeout=120,
            env={"GH_TOKEN": token},
        )
        if result.exit_code != 0:
            reason = result.stderr.strip() or result.stdout.strip() or f"exit {result.exit_code}"
            raise GitHubError(f"could not add label {label} to {kind} #{number}: {reason}")

    def list_label_names(self, token: str | None = None) -> frozenset[str]:
        result = self._run(
            [
                "gh",
                "label",
                "list",
                "--repo",
                self.repo,
                "--limit",
                "1000",
                "--json",
                "name",
            ],
            cwd="/",
            timeout=120,
            env=_gh_env(token),
        )
        if result.exit_code != 0:
            reason = result.stderr.strip() or f"exit {result.exit_code}"
            raise GitHubError(f"gh label list failed: {reason}")
        return frozenset(
            str(obj.get("name", "")) for obj in self._json_list(result.stdout, "gh label list")
        )

    def comment(self, number: int, body: str, token: str) -> str:
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
            env={"GH_TOKEN": token},
        )
        return result.stdout.strip()

    def _to_ticket(self, obj: dict) -> Ticket:
        return Ticket(
            number=int(obj["number"]),
            title=obj.get("title", ""),
            body=obj.get("body", "") or "",
            labels=frozenset(label["name"] for label in obj.get("labels", [])),
        )

    def _resolve(self, tickets: list[Ticket], token: str | None) -> list[Ticket]:
        """Resolve open blockers, existing PRs and contract holds (#144)."""
        pr_tickets = self._open_pr_tickets(token)
        open_pr_numbers = {n for _pr, numbers in pr_tickets for n in numbers}
        holds = self._contract_holds(tickets, pr_tickets, token)
        resolved: list[Ticket] = []
        for ticket in tickets:
            blocked_by = tuple(
                n for n in self._open_blockers(ticket.body) if self._is_open(n, token)
            )
            resolved.append(
                Ticket(
                    number=ticket.number,
                    title=ticket.title,
                    body=ticket.body,
                    labels=ticket.labels,
                    blocked_by=blocked_by,
                    has_open_pr=ticket.number in open_pr_numbers,
                    contract_conflicts=_conflicts(ticket, holds),
                )
            )
        return resolved

    def _contract_holds(
        self,
        tickets: list[Ticket],
        pr_tickets: list[tuple[int | None, list[int]]],
        token: str | None,
    ) -> list[tuple[int | None, int, Contracts]]:
        """(PR, ticket, contracts) for every open PR's ticket that declares contracts.

        Bodies are read only when a listed ticket declares contracts. An unreadable
        body raises: guessing "no contracts" would let two tickets race on one.
        """
        if not any(_declares(parse_contracts(t.body)) for t in tickets):
            return []
        bodies: dict[int, str] = {}
        holds = []
        for pr_number, numbers in pr_tickets:
            for number in numbers:
                if number not in bodies:
                    bodies[number] = self._issue_body(number, token)
                contracts = parse_contracts(bodies[number])
                if _declares(contracts):
                    holds.append((pr_number, number, contracts))
        return holds

    def _issue_body(self, number: int, token: str | None) -> str:
        result = self._run(
            ["gh", "issue", "view", str(number), "--repo", self.repo, "--json", "body"],
            cwd="/",
            timeout=120,
            env=_gh_env(token),
        )
        if result.exit_code != 0:
            reason = result.stderr.strip() or f"exit {result.exit_code}"
            raise GitHubError(f"gh issue view #{number} failed: {reason}")
        try:
            return str(json.loads(result.stdout).get("body") or "")
        except (json.JSONDecodeError, AttributeError) as exc:
            raise GitHubError(f"gh issue view #{number} returned invalid JSON") from exc

    def _open_blockers(self, body: str) -> list[int]:
        # Native dependencies are the live gate; the "Blocked by:" line is the fallback.
        return list(parse_blocked_by(body))

    def _is_open(self, number: int, token: str | None) -> bool:
        result = self._run(
            ["gh", "issue", "view", str(number), "--repo", self.repo, "--json", "state"],
            cwd="/",
            timeout=120,
            env=_gh_env(token),
        )
        if result.exit_code != 0:
            return True
        try:
            return json.loads(result.stdout).get("state") == "OPEN"
        except (json.JSONDecodeError, AttributeError):
            return True

    def _open_pr_ticket_numbers(self, token: str | None) -> set[int]:
        return {n for _pr, numbers in self._open_pr_tickets(token) for n in numbers}

    def _open_pr_tickets(self, token: str | None) -> list[tuple[int | None, list[int]]]:
        """Every open PR (any author), mapped to the issues its body closes or is part of."""
        result = self._run(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                self.repo,
                "--state",
                "open",
                "--limit",
                "1000",
                "--json",
                "number,body",
            ],
            cwd="/",
            timeout=120,
            env=_gh_env(token),
        )
        if result.exit_code != 0:
            raise GitHubError(f"gh pr list failed: {result.stderr.strip() or result.exit_code}")
        try:
            prs = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise GitHubError("gh pr list returned invalid JSON") from exc
        if not isinstance(prs, list):
            raise GitHubError("gh pr list returned an unexpected JSON shape")
        tickets: list[tuple[int | None, list[int]]] = []
        for obj in prs:
            numbers = [int(match) for match in _CLOSES_RE.findall(obj.get("body", "") or "")]
            pr_number = obj.get("number")
            tickets.append((None if pr_number is None else int(pr_number), numbers))
        return tickets


def _declares(contracts: Contracts) -> bool:
    return bool(contracts.held or contracts.consumed)


def _conflicts(ticket: Ticket, holds: list[tuple[int | None, int, Contracts]]) -> tuple[str, ...]:
    mine = parse_contracts(ticket.body)
    lines = []
    for pr_number, number, theirs in holds:
        if number == ticket.number:
            continue
        for contract in sorted(mine.conflicts_with(theirs)):
            pr = "an open PR" if pr_number is None else f"PR #{pr_number}"
            lines.append(f"{contract} held by {pr} (#{number})")
    return tuple(lines)


def _gh_env(token: str | None) -> dict[str, str] | None:
    return {"GH_TOKEN": token} if token else None


def _same_login(login: str, author: str) -> bool:
    return _normalize_login(login) == _normalize_login(author)


def _normalize_login(login: str) -> str:
    return login.removesuffix("[bot]").removeprefix("app/")


def _latest_owner_review(reviews: list[dict], owner: str) -> tuple[dict | None, datetime | None]:
    """Return the owner's most recent review and when it was submitted."""
    latest: tuple[datetime, dict] | None = None
    for review in reviews:
        login = (review.get("user") or {}).get("login", "")
        if not _same_login(login, owner):
            continue
        submitted_at = _parse_timestamp(review.get("submitted_at", ""))
        if submitted_at is None:
            continue
        if latest is None or submitted_at > latest[0]:
            latest = (submitted_at, review)
    if latest is None:
        return None, None
    return latest[1], latest[0]


def _commit_after(commits: list[dict], review_time: datetime) -> bool:
    """True when the branch head moved after the review was submitted."""
    commit_times = [
        _parse_timestamp(commit.get("committedDate") or commit.get("authoredDate") or "")
        for commit in commits
    ]
    times = [commit_time for commit_time in commit_times if commit_time is not None]
    if not times:
        return False
    return max(times) > review_time


def _ticket_number(pr_body: str) -> int | None:
    match = _CLOSES_RE.search(pr_body)
    return int(match.group(1)) if match else None


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
