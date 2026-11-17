"""Weekly review metrics for factory pull requests.

The numbers answer one question: is the owner spending less time per PR
without more reverts? They are computed from the GitHub REST API (never
GraphQL) and sent over Telegram by ``factory metrics``.

- PRs, merges and change-request rounds per PR.
- Open-to-merge hours.
- Wait for the owner: from the PR becoming ready to her first review, and
  from each "Addressed the review" factory comment to her next review. This
  separates her time from CI and from the factory's fix time.
- Stuck tickets and reverts as guardrails.
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from .github import _gh_env, _same_login
from .notify import RunFailedInfo, escape_html
from .preflight import short_error
from .shell import RunCommand, run_command

WEEK_DAYS = 7
MONTH_DAYS = 28
ADDRESSED_PREFIX = "Addressed the review"
STUCK_PREFIX = "The night factory could not finish this ticket."
FACTORY_BRANCH_PREFIX = "nf/"


@dataclass(frozen=True)
class OwnerReview:
    state: str
    submitted_at: datetime


@dataclass(frozen=True)
class PrActivity:
    number: int
    title: str
    created_at: datetime
    ready_at: datetime
    merged_at: datetime | None
    owner_reviews: tuple[OwnerReview, ...]
    addressed_at: tuple[datetime, ...]


@dataclass(frozen=True)
class WaitStats:
    count: int
    median: float | None
    p90: float | None


@dataclass(frozen=True)
class WindowMetrics:
    days: int
    prs: int
    merged: int
    no_changes_requested: int
    mean_change_rounds: float | None
    median_hours_to_merge: float | None
    first_review_wait: WaitStats
    after_fix_wait: WaitStats
    stuck: int
    reverts: int


@dataclass(frozen=True)
class CollectedData:
    prs: list[PrActivity]
    stuck_at: list[datetime]
    revert_merges: list[datetime]


# --- parsing ------------------------------------------------------------------


def _timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _login(obj: dict) -> str:
    return str((obj.get("user") or {}).get("login", ""))


def pr_activity_from_rest(
    pr: dict,
    *,
    timeline: list[dict],
    reviews: list[dict],
    comments: list[dict],
    owner: str,
    bot: str,
) -> PrActivity:
    """Build one PR's activity from the REST pull, timeline, reviews and comments."""
    created_at = _timestamp(pr["created_at"])
    ready_events = sorted(
        moment
        for event in timeline
        if event.get("event") == "ready_for_review"
        and (moment := _timestamp(event.get("created_at"))) is not None
    )
    owner_reviews = sorted(
        (
            OwnerReview(state=str(item.get("state", "")), submitted_at=moment)
            for item in reviews
            if _same_login(_login(item), owner)
            and item.get("state") != "PENDING"
            and (moment := _timestamp(item.get("submitted_at"))) is not None
        ),
        key=lambda item: item.submitted_at,
    )
    addressed = sorted(
        moment
        for item in comments
        if _same_login(_login(item), bot)
        and str(item.get("body", "")).startswith(ADDRESSED_PREFIX)
        and (moment := _timestamp(item.get("created_at"))) is not None
    )
    return PrActivity(
        number=int(pr["number"]),
        title=str(pr.get("title", "")),
        created_at=created_at,
        ready_at=ready_events[0] if ready_events else created_at,
        merged_at=_timestamp(pr.get("merged_at")),
        owner_reviews=tuple(owner_reviews),
        addressed_at=tuple(addressed),
    )


# --- computing ----------------------------------------------------------------


def _hours(delta: timedelta) -> float:
    return delta.total_seconds() / 3600


def _wait_stats(values: list[float]) -> WaitStats:
    if not values:
        return WaitStats(count=0, median=None, p90=None)
    ordered = sorted(values)
    rank = math.ceil(0.9 * len(ordered))
    return WaitStats(count=len(ordered), median=statistics.median(ordered), p90=ordered[rank - 1])


def compute_window(
    prs: Iterable[PrActivity],
    *,
    stuck_at: Iterable[datetime],
    reverts: int,
    now: datetime,
    days: int,
) -> WindowMetrics:
    """Metrics for factory PRs created in the last ``days`` days."""
    start = now - timedelta(days=days)
    window = [pr for pr in prs if pr.created_at >= start]
    rounds = [
        sum(1 for review in pr.owner_reviews if review.state == "CHANGES_REQUESTED")
        for pr in window
    ]
    merge_hours = [_hours(pr.merged_at - pr.created_at) for pr in window if pr.merged_at]
    first_waits = [
        _hours(pr.owner_reviews[0].submitted_at - pr.ready_at) for pr in window if pr.owner_reviews
    ]
    fix_waits: list[float] = []
    for pr in window:
        for addressed in pr.addressed_at:
            following = [r.submitted_at for r in pr.owner_reviews if r.submitted_at > addressed]
            if following:
                fix_waits.append(_hours(following[0] - addressed))
    return WindowMetrics(
        days=days,
        prs=len(window),
        merged=len(merge_hours),
        no_changes_requested=sum(1 for count in rounds if count == 0),
        mean_change_rounds=sum(rounds) / len(rounds) if rounds else None,
        median_hours_to_merge=statistics.median(merge_hours) if merge_hours else None,
        first_review_wait=_wait_stats(first_waits),
        after_fix_wait=_wait_stats(fix_waits),
        stuck=sum(1 for moment in stuck_at if moment >= start),
        reverts=reverts,
    )


# --- message ------------------------------------------------------------------


def _number(value: float | None, unit: str = "") -> str:
    return "n/a" if value is None else f"{value:.1f}{unit}"


def _wait_line(label: str, stats: WaitStats) -> str:
    if stats.count == 0:
        return f"{label}: n/a"
    return (
        f"{label}: median {_number(stats.median, ' h')}, "
        f"p90 {_number(stats.p90, ' h')} (n={stats.count})"
    )


def _window_lines(window: WindowMetrics) -> list[str]:
    rounds = "n/a" if window.mean_change_rounds is None else f"{window.mean_change_rounds:.2f}"
    return [
        f"<i>Last {window.days} days</i>",
        f"PRs: {window.prs} (merged {window.merged}, "
        f"no changes requested {window.no_changes_requested})",
        f"Change-request rounds per PR: {rounds}",
        f"Open to merge: median {_number(window.median_hours_to_merge, ' h')}",
        _wait_line("Wait for first owner review", window.first_review_wait),
        _wait_line("Wait after a review fix", window.after_fix_wait),
        f"Stuck tickets: {window.stuck}",
        f"Reverts: {window.reverts}",
    ]


def build_metrics_message(week: WindowMetrics, month: WindowMetrics) -> str:
    lines = ["<b>Night factory metrics</b>", "", *_window_lines(week), "", *_window_lines(month)]
    return "\n".join(escape_html(line) if not line.startswith("<") else line for line in lines)


# --- GitHub (REST only) ---------------------------------------------------------


def _pages(text: str) -> list[dict]:
    """Flatten a ``gh api --paginate`` stream of JSON arrays."""
    decoder = json.JSONDecoder()
    values: list[dict] = []
    index = 0
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        value, index = decoder.raw_decode(text, index)
        if not isinstance(value, list):
            raise RuntimeError("gh api returned an unexpected JSON shape")
        values.extend(value)
    return values


class MetricsGitHub:
    """Read what the metrics need through ``gh api`` (REST)."""

    def __init__(self, repo: str, *, owner: str, bot: str, run: RunCommand = run_command):
        self.repo = repo
        self.owner = owner
        self.bot = bot
        self._run = run

    def collect(self, *, since: datetime, token: str | None) -> CollectedData:
        pulls = self._get(f"repos/{self.repo}/pulls?state=all&sort=created&direction=desc", token)
        factory_prs = [
            pr
            for pr in pulls
            if _same_login(_login(pr), self.bot)
            and str((pr.get("head") or {}).get("ref", "")).startswith(FACTORY_BRANCH_PREFIX)
            and _timestamp(pr.get("created_at")) >= since
        ]
        prs = [
            pr_activity_from_rest(
                pr,
                timeline=self._get(f"repos/{self.repo}/issues/{pr['number']}/timeline", token),
                reviews=self._get(f"repos/{self.repo}/pulls/{pr['number']}/reviews", token),
                comments=self._get(f"repos/{self.repo}/issues/{pr['number']}/comments", token),
                owner=self.owner,
                bot=self.bot,
            )
            for pr in factory_prs
        ]
        revert_merges = sorted(
            merged
            for pr in pulls
            if str(pr.get("title", "")).startswith("Revert")
            and (merged := _timestamp(pr.get("merged_at"))) is not None
            and merged >= since
        )
        since_iso = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        comments = self._get(f"repos/{self.repo}/issues/comments?since={since_iso}", token)
        stuck_at = sorted(
            moment
            for comment in comments
            if _same_login(_login(comment), self.bot)
            and str(comment.get("body", "")).startswith(STUCK_PREFIX)
            and (moment := _timestamp(comment.get("created_at"))) is not None
        )
        return CollectedData(prs=prs, stuck_at=stuck_at, revert_merges=revert_merges)

    def _get(self, path: str, token: str | None) -> list[dict]:
        separator = "&" if "?" in path else "?"
        result = self._run(
            ["gh", "api", "--paginate", f"{path}{separator}per_page=100"],
            cwd="/",
            timeout=120,
            env=_gh_env(token),
        )
        if result.exit_code != 0:
            raise RuntimeError(f"gh api {path} failed: {result.stderr.strip() or result.exit_code}")
        return _pages(result.stdout)


# --- the command -----------------------------------------------------------------


class Collector(Protocol):
    def collect(self, *, since: datetime, token: str | None) -> CollectedData: ...


class MetricsNotifier(Protocol):
    def send_metrics(self, text: str) -> None: ...

    def send_run_failed(self, info: RunFailedInfo) -> None: ...


class Tokens(Protocol):
    def mint(self, repo: str) -> str: ...


def run_metrics(
    collector: Collector,
    notifier: MetricsNotifier,
    tokens: Tokens,
    *,
    repo: str,
    now: datetime,
) -> int:
    """Collect, compute both windows, send one message. Return the exit code."""
    try:
        token = tokens.mint(repo)
        data = collector.collect(since=now - timedelta(days=MONTH_DAYS), token=token)
        windows = [
            compute_window(
                data.prs,
                stuck_at=data.stuck_at,
                reverts=sum(1 for m in data.revert_merges if m >= now - timedelta(days=days)),
                now=now,
                days=days,
            )
            for days in (WEEK_DAYS, MONTH_DAYS)
        ]
        text = build_metrics_message(*windows)
    except Exception as exc:
        reason = f"metrics failed: {short_error(exc)}"
        try:
            notifier.send_run_failed(RunFailedInfo(reason=reason))
        except Exception:
            pass
        print(reason, file=sys.stderr)
        return 1
    notifier.send_metrics(text)
    print(text)
    return 0
