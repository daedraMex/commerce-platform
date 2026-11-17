"""Weekly review metrics for factory pull requests.

The numbers answer one question: is the owner spending less time per PR
without more reverts? They are computed from the GitHub REST API (never
GraphQL) and sent over Telegram by ``factory metrics``.

Every number is windowed by the date of its own event:

- PRs opened (by creation) and merged (by merge) in the window.
- Of the merged ones: how many had owner reviews and no change request
  ("clean"), how many were merged with no owner review at all, the mean
  change-request rounds and the open-to-merge hours.
- Wait for the owner, by review date: from the PR becoming ready to her first
  review, and from each "Addressed the review" factory comment to her next
  review. This separates her time from CI and from the factory's fix time.
  PRs still waiting at report time are counted, with the oldest wait.
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
    ready_at: datetime | None
    merged_at: datetime | None
    owner_reviews: tuple[OwnerReview, ...]
    addressed_at: tuple[datetime, ...]
    is_open: bool = False


@dataclass(frozen=True)
class WaitStats:
    count: int
    median: float | None
    p90: float | None


@dataclass(frozen=True)
class WindowMetrics:
    days: int
    opened: int
    merged: int
    clean_merges: int
    merged_without_review: int
    mean_change_rounds: float | None
    median_hours_to_merge: float | None
    first_review_wait: WaitStats
    after_fix_wait: WaitStats
    still_waiting: int
    oldest_wait_hours: float | None
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
    if pr.get("draft"):
        ready_at = None
    else:
        ready_at = ready_events[0] if ready_events else created_at
    return PrActivity(
        number=int(pr["number"]),
        title=str(pr.get("title", "")),
        created_at=created_at,
        ready_at=ready_at,
        merged_at=_timestamp(pr.get("merged_at")),
        owner_reviews=tuple(owner_reviews),
        addressed_at=tuple(addressed),
        is_open=pr.get("state") == "open",
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


def _first_review_after(pr: PrActivity, moment: datetime) -> datetime | None:
    for review in pr.owner_reviews:
        if review.submitted_at >= moment:
            return review.submitted_at
    return None


def _waits(pr: PrActivity) -> tuple[list[tuple[datetime, float]], list[tuple[datetime, float]]]:
    """(review time, hours waited) for the first review and for each fix round.

    Reviews before the PR became ready (a draft the owner looked at early) do
    not end a wait, so no wait is negative.
    """
    first: list[tuple[datetime, float]] = []
    after_fix: list[tuple[datetime, float]] = []
    if pr.ready_at is not None:
        reviewed = _first_review_after(pr, pr.ready_at)
        if reviewed is not None:
            first.append((reviewed, _hours(reviewed - pr.ready_at)))
    for addressed in pr.addressed_at:
        reviewed = _first_review_after(pr, addressed)
        if reviewed is not None:
            after_fix.append((reviewed, _hours(reviewed - addressed)))
    return first, after_fix


def _waiting_since(pr: PrActivity) -> datetime | None:
    """When an open PR started waiting for the owner, or None if it is not waiting."""
    if not pr.is_open or pr.ready_at is None:
        return None
    if _first_review_after(pr, pr.ready_at) is None:
        return pr.ready_at
    for addressed in reversed(pr.addressed_at):
        if _first_review_after(pr, addressed) is None:
            return addressed
    return None


def compute_window(
    prs: Iterable[PrActivity],
    *,
    stuck_at: Iterable[datetime],
    reverts: int,
    now: datetime,
    days: int,
) -> WindowMetrics:
    """Metrics for the last ``days`` days, each windowed by its own event date."""
    start = now - timedelta(days=days)
    prs = list(prs)
    merged = [pr for pr in prs if pr.merged_at is not None and pr.merged_at >= start]
    rounds = [
        sum(1 for review in pr.owner_reviews if review.state == "CHANGES_REQUESTED")
        for pr in merged
    ]
    first_waits: list[float] = []
    fix_waits: list[float] = []
    for pr in prs:
        first, after_fix = _waits(pr)
        first_waits += [hours for reviewed, hours in first if reviewed >= start]
        fix_waits += [hours for reviewed, hours in after_fix if reviewed >= start]
    waiting = [since for pr in prs if (since := _waiting_since(pr)) is not None]
    return WindowMetrics(
        days=days,
        opened=sum(1 for pr in prs if pr.created_at >= start),
        merged=len(merged),
        clean_merges=sum(
            1 for pr, count in zip(merged, rounds, strict=True) if pr.owner_reviews and count == 0
        ),
        merged_without_review=sum(1 for pr in merged if not pr.owner_reviews),
        mean_change_rounds=sum(rounds) / len(rounds) if rounds else None,
        median_hours_to_merge=(
            statistics.median(_hours(pr.merged_at - pr.created_at) for pr in merged)
            if merged
            else None
        ),
        first_review_wait=_wait_stats(first_waits),
        after_fix_wait=_wait_stats(fix_waits),
        still_waiting=len(waiting),
        oldest_wait_hours=_hours(now - min(waiting)) if waiting else None,
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
        f"PRs opened: {window.opened}, merged: {window.merged}",
        f"Merged clean (reviewed, no changes requested): {window.clean_merges} of "
        f"{window.merged}; merged with no owner review: {window.merged_without_review}",
        f"Change-request rounds per merged PR: {rounds}",
        f"Open to merge: median {_number(window.median_hours_to_merge, ' h')}",
        _wait_line("Wait for first owner review", window.first_review_wait),
        _wait_line("Wait after a review fix", window.after_fix_wait),
        f"Stuck tickets: {window.stuck}",
        f"Reverts: {window.reverts}",
    ]


def build_metrics_message(week: WindowMetrics, month: WindowMetrics) -> str:
    waiting = (
        f"Waiting for you now: {week.still_waiting} PR(s), "
        f"oldest {_number(week.oldest_wait_hours, ' h')}"
        if week.still_waiting
        else "Waiting for you now: none"
    )
    lines = [
        "<b>Night factory metrics</b>",
        waiting,
        "",
        *_window_lines(week),
        "",
        *_window_lines(month),
    ]
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
        pulls = self._get(f"repos/{self.repo}/pulls?state=all&sort=updated&direction=desc", token)
        # Updated, not created, since the window: a PR opened earlier can still be
        # reviewed, fixed or merged inside it.
        factory_prs = [
            pr
            for pr in pulls
            if _same_login(_login(pr), self.bot)
            and str((pr.get("head") or {}).get("ref", "")).startswith(FACTORY_BRANCH_PREFIX)
            and (_timestamp(pr.get("updated_at")) or _timestamp(pr.get("created_at"))) >= since
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
    def send_metrics(self, text: str) -> None:
        """Deliver the report; raise when it could not be delivered."""
        ...

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
    print(text)
    try:
        notifier.send_metrics(text)
    except Exception as exc:
        print(f"metrics not delivered: {short_error(exc)}", file=sys.stderr)
        return 1
    return 0
