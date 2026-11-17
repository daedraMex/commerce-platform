import json
from datetime import UTC, datetime, timedelta

import pytest

from factory.metrics import (
    MetricsGitHub,
    PrActivity,
    build_metrics_message,
    compute_window,
    pr_activity_from_rest,
    run_metrics,
)
from factory.shell import CommandResult

OWNER = "daedraMex"
BOT = "xolo-bot"
NOW = datetime(2026, 11, 23, 15, 0, tzinfo=UTC)


def at(hours_ago: float) -> datetime:
    return NOW - timedelta(hours=hours_ago)


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def activity(
    number,
    *,
    created,
    ready=None,
    merged=None,
    reviews=(),
    addressed=(),
    title="#1: ticket",
    is_open=None,
    draft=False,
):
    return PrActivity(
        number=number,
        title=title,
        created_at=created,
        ready_at=None if draft else (ready or created),
        merged_at=merged,
        owner_reviews=tuple(reviews),
        addressed_at=tuple(addressed),
        is_open=(merged is None) if is_open is None else is_open,
    )


# --- parsing REST payloads -------------------------------------------------


def test_pr_activity_takes_ready_time_from_the_timeline_and_only_owner_reviews():
    pr = {
        "number": 140,
        "title": "#99: Phase 4b / B1",
        "created_at": iso(at(50)),
        "merged_at": iso(at(10)),
    }
    timeline = [
        {"event": "labeled", "created_at": iso(at(49))},
        {"event": "ready_for_review", "created_at": iso(at(48))},
    ]
    reviews = [
        {"user": {"login": "xolo-bot[bot]"}, "state": "COMMENTED", "submitted_at": iso(at(47))},
        {"user": {"login": OWNER}, "state": "CHANGES_REQUESTED", "submitted_at": iso(at(40))},
        {"user": {"login": OWNER}, "state": "APPROVED", "submitted_at": iso(at(12))},
    ]
    comments = [
        {
            "user": {"login": "xolo-bot[bot]"},
            "body": "Addressed the review in abc; please re-review.",
            "created_at": iso(at(30)),
        },
        {"user": {"login": OWNER}, "body": "Addressed the review in x", "created_at": iso(at(29))},
        {"user": {"login": "xolo-bot[bot]"}, "body": "Something else", "created_at": iso(at(28))},
    ]

    pr_activity = pr_activity_from_rest(
        pr, timeline=timeline, reviews=reviews, comments=comments, owner=OWNER, bot=BOT
    )

    assert pr_activity.number == 140
    assert pr_activity.ready_at == at(48)
    assert pr_activity.merged_at == at(10)
    assert [r.state for r in pr_activity.owner_reviews] == ["CHANGES_REQUESTED", "APPROVED"]
    assert pr_activity.addressed_at == (at(30),)


def test_pr_activity_never_a_draft_is_ready_when_created():
    pr = {
        "number": 7,
        "title": "t",
        "created_at": iso(at(5)),
        "merged_at": None,
        "state": "open",
        "draft": False,
    }

    pr_activity = pr_activity_from_rest(
        pr, timeline=[], reviews=[], comments=[], owner=OWNER, bot=BOT
    )

    assert pr_activity.ready_at == at(5)
    assert pr_activity.merged_at is None
    assert pr_activity.is_open is True


def test_pr_activity_still_a_draft_has_no_ready_time():
    pr = {
        "number": 7,
        "title": "t",
        "created_at": iso(at(5)),
        "merged_at": None,
        "state": "open",
        "draft": True,
    }

    pr_activity = pr_activity_from_rest(
        pr, timeline=[], reviews=[], comments=[], owner=OWNER, bot=BOT
    )

    assert pr_activity.ready_at is None


# --- computing one window ---------------------------------------------------


def review(state, hours_ago):
    from factory.metrics import OwnerReview

    return OwnerReview(state=state, submitted_at=at(hours_ago))


def test_window_counts_merges_rounds_and_owner_wait():
    prs = [
        # ready 100h ago, first review 96h ago (4h wait), approved, merged 90h ago
        activity(
            1, created=at(101), ready=at(100), merged=at(90), reviews=[review("APPROVED", 96)]
        ),
        # change request 50h ago (10h wait), fix addressed 40h ago,
        # owner re-reviews 38h ago (2h wait), merged 37h ago
        activity(
            2,
            created=at(60),
            merged=at(37),
            reviews=[review("CHANGES_REQUESTED", 50), review("APPROVED", 38)],
            addressed=[at(40)],
        ),
        # open and never reviewed: opened, waiting, not part of the merged stats
        activity(3, created=at(20)),
    ]

    window = compute_window(prs, stuck_at=[at(30), at(400)], reverts=0, now=NOW, days=7)

    assert window.opened == 3
    assert window.merged == 2
    assert window.clean_merges == 1
    assert window.merged_without_review == 0
    assert window.mean_change_rounds == pytest.approx(0.5)
    assert window.median_hours_to_merge == pytest.approx((11 + 23) / 2)
    assert window.first_review_wait.median == pytest.approx((4 + 10) / 2)
    assert window.first_review_wait.count == 2
    assert window.after_fix_wait.median == pytest.approx(2)
    assert window.still_waiting == 1
    assert window.oldest_wait_hours == pytest.approx(20)
    assert window.stuck == 1


def test_open_unreviewed_prs_do_not_count_as_clean_merges():
    prs = [
        activity(
            1,
            created=at(30),
            merged=at(5),
            reviews=[
                review("CHANGES_REQUESTED", 20),
                review("CHANGES_REQUESTED", 10),
                review("APPROVED", 6),
            ],
        ),
        activity(2, created=at(10)),
        activity(3, created=at(9)),
        activity(4, created=at(8)),
    ]

    window = compute_window(prs, stuck_at=[], reverts=0, now=NOW, days=7)

    assert window.clean_merges == 0
    assert window.mean_change_rounds == pytest.approx(2)


def test_a_merge_with_no_owner_review_is_reported_not_clean():
    prs = [activity(1, created=at(10), merged=at(5))]

    window = compute_window(prs, stuck_at=[], reverts=0, now=NOW, days=7)

    assert window.merged_without_review == 1
    assert window.clean_merges == 0


def test_waits_are_windowed_by_review_date_not_creation_date():
    prs = [
        # created 10 days ago, ready then, reviewed 2 days ago: in the 7-day window
        activity(
            1, created=at(240), ready=at(240), reviews=[review("COMMENTED", 48)], is_open=True
        ),
        # created 10 days ago, fix addressed 3 days ago, re-reviewed 1 hour later
        activity(
            2,
            created=at(240),
            reviews=[review("CHANGES_REQUESTED", 200), review("APPROVED", 71)],
            addressed=[at(72)],
            merged=at(70),
        ),
    ]

    week = compute_window(prs, stuck_at=[], reverts=0, now=NOW, days=7)

    assert week.opened == 0
    assert week.first_review_wait.count == 1
    assert week.first_review_wait.median == pytest.approx(240 - 48)
    assert week.after_fix_wait.median == pytest.approx(1)


def test_a_pr_still_waiting_counts_with_its_oldest_wait():
    prs = [
        activity(1, created=at(64)),
        activity(2, created=at(10), reviews=[review("CHANGES_REQUESTED", 9)], addressed=[at(5)]),
        activity(3, created=at(3), reviews=[review("APPROVED", 2)]),
    ]

    window = compute_window(prs, stuck_at=[], reverts=0, now=NOW, days=7)

    assert window.still_waiting == 2
    assert window.oldest_wait_hours == pytest.approx(64)


def test_a_review_on_a_draft_never_makes_a_negative_wait():
    prs = [
        # still a draft: no ready time, not waiting, no first-review sample
        activity(1, created=at(10), draft=True, reviews=[review("COMMENTED", 9)]),
        # reviewed before it became ready: that review does not end the wait
        activity(
            2,
            created=at(20),
            ready=at(10),
            reviews=[review("COMMENTED", 15), review("APPROVED", 7)],
        ),
    ]

    window = compute_window(prs, stuck_at=[], reverts=0, now=NOW, days=7)

    assert window.first_review_wait.count == 1
    assert window.first_review_wait.median == pytest.approx(3)
    assert window.still_waiting == 0


def test_window_only_counts_prs_opened_inside_it():
    prs = [
        activity(1, created=at(24 * 3)),
        activity(2, created=at(24 * 10)),
    ]

    week = compute_window(prs, stuck_at=[], reverts=0, now=NOW, days=7)
    month = compute_window(prs, stuck_at=[], reverts=0, now=NOW, days=28)

    assert week.opened == 1
    assert month.opened == 2


def test_p90_uses_the_nearest_rank():
    prs = [
        activity(n, created=at(200), ready=at(200), reviews=[review("APPROVED", 200 - n)])
        for n in range(1, 11)
    ]

    window = compute_window(prs, stuck_at=[], reverts=0, now=NOW, days=28)

    assert window.first_review_wait.p90 == pytest.approx(9)


def test_empty_window_has_no_averages():
    window = compute_window([], stuck_at=[], reverts=0, now=NOW, days=7)

    assert window.opened == 0
    assert window.mean_change_rounds is None
    assert window.median_hours_to_merge is None
    assert window.first_review_wait.median is None
    assert window.still_waiting == 0


# --- message ----------------------------------------------------------------


def test_message_shows_both_windows_and_marks_missing_values():
    prs = [
        activity(1, created=at(10), ready=at(10), merged=at(2), reviews=[review("APPROVED", 6)]),
    ]
    week = compute_window(prs, stuck_at=[], reverts=0, now=NOW, days=7)
    month = compute_window([], stuck_at=[], reverts=1, now=NOW, days=28)

    text = build_metrics_message(week, month)

    assert "<b>Night factory metrics</b>" in text
    assert "Last 7 days" in text
    assert "Last 28 days" in text
    assert "Wait for first owner review: median 4.0 h" in text
    assert "n/a" in text
    assert "Reverts: 1" in text
    assert "Waiting for you now: none" in text


# --- GitHub adapter (REST only) ----------------------------------------------


class FakeRun:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, argv, cwd, *, timeout, env=None, replace_env=False):
        self.calls.append(argv)
        path = argv[-1]
        for prefix, payload in self.routes.items():
            if path.startswith(prefix):
                return CommandResult(0, json.dumps(payload), "")
        return CommandResult(0, "[]", "")


def test_github_adapter_collects_factory_prs_with_rest_only():
    repo = "daedraMex/commerce-platform"
    run = FakeRun(
        {
            f"repos/{repo}/pulls?state=all": [
                {
                    "number": 5,
                    "title": "#4: t",
                    "created_at": iso(at(30)),
                    "merged_at": None,
                    "user": {"login": "xolo-bot[bot]"},
                    "head": {"ref": "nf/4-t"},
                },
                {
                    "number": 6,
                    "title": "docs",
                    "created_at": iso(at(30)),
                    "merged_at": None,
                    "user": {"login": OWNER},
                    "head": {"ref": "docs/x"},
                },
                {
                    "number": 7,
                    "title": "old",
                    "created_at": iso(at(24 * 60)),
                    "merged_at": None,
                    "user": {"login": "xolo-bot[bot]"},
                    "head": {"ref": "nf/1-old"},
                },
                {
                    "number": 8,
                    "title": 'Revert "x"',
                    "created_at": iso(at(5)),
                    "merged_at": iso(at(4)),
                    "user": {"login": OWNER},
                    "head": {"ref": "revert-1"},
                },
            ],
            f"repos/{repo}/issues/comments": [
                {
                    "user": {"login": "xolo-bot[bot]"},
                    "created_at": iso(at(3)),
                    "body": "The night factory could not finish this ticket.\n...",
                },
                {
                    "user": {"login": OWNER},
                    "created_at": iso(at(3)),
                    "body": "The night factory could not finish this ticket.",
                },
            ],
        }
    )
    github = MetricsGitHub(repo, owner=OWNER, bot=BOT, run=run)

    data = github.collect(since=NOW - timedelta(days=28), token="TOKEN")

    assert [pr.number for pr in data.prs] == [5]
    assert data.stuck_at == [at(3)]
    assert data.revert_merges == [at(4)]
    assert all(argv[:2] == ["gh", "api"] for argv in run.calls)


def test_github_adapter_raises_when_gh_fails():
    def failing(argv, cwd, *, timeout, env=None, replace_env=False):
        return CommandResult(1, "", "HTTP 502")

    github = MetricsGitHub("o/r", owner=OWNER, bot=BOT, run=failing)

    with pytest.raises(RuntimeError, match="HTTP 502"):
        github.collect(since=NOW - timedelta(days=28), token="TOKEN")


# --- the command --------------------------------------------------------------


class FakeCollector:
    def __init__(self, data=None, error=None):
        self.data = data
        self.error = error
        self.tokens = []

    def collect(self, *, since, token):
        self.tokens.append(token)
        if self.error:
            raise self.error
        return self.data


class FakeTokens:
    def mint(self, repo):
        return "TOKEN"


class Messages:
    def __init__(self):
        self.metrics = []
        self.failures = []

    def send_metrics(self, text):
        self.metrics.append(text)

    def send_run_failed(self, info):
        self.failures.append(info.reason)


def test_run_metrics_sends_one_report_with_a_fresh_token():
    from factory.metrics import CollectedData

    collector = FakeCollector(CollectedData(prs=[], stuck_at=[], revert_merges=[]))
    messages = Messages()

    code = run_metrics(collector, messages, FakeTokens(), repo="o/r", now=NOW)

    assert code == 0
    assert collector.tokens == ["TOKEN"]
    assert len(messages.metrics) == 1
    assert messages.failures == []


def test_run_metrics_reports_a_failure_once_and_exits_non_zero():
    messages = Messages()

    code = run_metrics(
        FakeCollector(error=RuntimeError("HTTP 502")), messages, FakeTokens(), repo="o/r", now=NOW
    )

    assert code == 1
    assert messages.metrics == []
    assert len(messages.failures) == 1
    assert messages.failures[0].startswith("metrics failed:")


def test_run_metrics_exits_non_zero_when_the_report_is_not_delivered():
    from factory.metrics import CollectedData

    class Undeliverable(Messages):
        def send_metrics(self, text):
            raise RuntimeError("Telegram send failed: 400 can't parse entities")

    code = run_metrics(
        FakeCollector(CollectedData(prs=[], stuck_at=[], revert_merges=[])),
        Undeliverable(),
        FakeTokens(),
        repo="o/r",
        now=NOW,
    )

    assert code == 1
