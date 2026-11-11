"""GitHub operations, wrapped around the ``gh`` CLI and faked in tests."""

from __future__ import annotations

import json
import re
from datetime import datetime

from .git import BOT_COMMIT_NAME
from .reviews import CHANGES_REQUESTED, ReviewComment, ReviewFix
from .shell import CommandResult, RunCommand, run_command
from .tickets import Ticket, parse_blocked_by

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
        token: str | None = None,
    ) -> list[ReviewFix]:
        """Return open factory PRs whose latest owner review asks for changes.

        A PR is a candidate only when its latest review by ``owner`` is
        ``CHANGES_REQUESTED`` and no commit by ``author`` landed after that
        review. Results are ordered oldest review first. Any failed ``gh`` call
        raises, so the caller can skip review fixes and continue.
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
            if review.get("state") != CHANGES_REQUESTED:
                continue
            if _factory_commit_after(detail.get("commits") or [], author, submitted_at):
                continue
            ticket_number = _ticket_number(pr.get("body", "") or "")
            if ticket_number is None:
                continue
            ticket = self.get_ticket(ticket_number, token)
            comments = self._review_comments(number, review.get("id"), token)
            fixes.append(
                ReviewFix(
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
        result = self._run(
            [
                "gh",
                "pr",
                "view",
                str(number),
                "--repo",
                self.repo,
                "--json",
                "reviews,commits",
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
        return detail

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

    def add_issue_label(self, number: int, label: str, token: str) -> None:
        self._run(
            ["gh", "issue", "edit", str(number), "--repo", self.repo, "--add-label", label],
            cwd="/",
            timeout=120,
            env={"GH_TOKEN": token},
        )

    def add_pr_label(self, number: int, label: str, token: str) -> None:
        self._run(
            ["gh", "pr", "edit", str(number), "--repo", self.repo, "--add-label", label],
            cwd="/",
            timeout=120,
            env={"GH_TOKEN": token},
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
        """Resolve open blockers and existing PRs; keep only the resolved tickets."""
        open_pr_numbers = self._open_pr_ticket_numbers(token)
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
                )
            )
        return resolved

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
                "body",
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
        numbers: set[int] = set()
        for obj in prs:
            for match in _CLOSES_RE.findall(obj.get("body", "") or ""):
                numbers.add(int(match))
        return numbers


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
        login = (review.get("author") or {}).get("login", "")
        if not _same_login(login, owner):
            continue
        submitted_at = _parse_timestamp(review.get("submittedAt", ""))
        if submitted_at is None:
            continue
        if latest is None or submitted_at > latest[0]:
            latest = (submitted_at, review)
    if latest is None:
        return None, None
    return latest[1], latest[0]


def _factory_commit_after(commits: list[dict], author: str, review_time: datetime) -> bool:
    """True when the factory pushed a commit after the review was submitted."""
    for commit in commits:
        commit_time = _parse_timestamp(
            commit.get("committedDate") or commit.get("authoredDate") or ""
        )
        if commit_time is None or commit_time <= review_time:
            continue
        for commit_author in commit.get("authors") or []:
            login = (commit_author or {}).get("login", "")
            name = (commit_author or {}).get("name", "")
            if _same_login(login, author) or name == BOT_COMMIT_NAME:
                return True
    return False


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
