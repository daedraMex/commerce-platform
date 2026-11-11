from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from factory.config import Settings
from factory.diff import DiffStats, FileChange
from factory.ledger import AttemptLedger
from factory.main import Factory, RunFailed
from factory.preflight import PreflightError
from factory.runner import AgentResult
from factory.tickets import Ticket, worktree_path

MEXICO_CITY = ZoneInfo("America/Mexico_City")

OVERLAY = "Model: {{MODEL}}. Branch: {{BRANCH}}."

COMMAND_BODY = "Read .agents/skills/implement/SKILL.md and follow it.\n\n$ARGUMENTS"

DECISIONS_DOC = "# Summary\nBuilt the thing.\n\n# Decisions\n\n- Chose A.\n"


class FakeGit:
    def __init__(
        self,
        *,
        check_passed=True,
        check_output="",
        decisions="",
        diff=None,
        command_body=COMMAND_BODY,
        fetch_error=None,
        preflight_check_passed=True,
    ):
        self.check_result = check_passed
        self.check_output = check_output
        self.decisions = decisions
        self.diff = diff or DiffStats()
        self.command_body = command_body
        self.fetch_error = fetch_error
        self.preflight_check_passed = preflight_check_passed
        self.committed = []
        self.pushed = []
        self.worktrees = []
        self.removed_worktrees = []
        self.deleted_branches = []
        self.events = []
        self.operations = []
        self.existing_worktrees = set()
        self.existing_branches = set()

    def fetch_main(self, repo_dir):
        self.events.append("fetch_main")
        if self.fetch_error is not None:
            raise self.fetch_error

    def verify_commit_identity(self, repo_dir):
        self.events.append("verify_commit_identity")

    def verify_no_leaked_worktrees(self, repo_dir, worktrees_dir):
        self.events.append("verify_no_leaked_worktrees")

    def worktree_exists(self, repo_dir, worktree):
        self.operations.append(("worktree_exists", str(worktree)))
        return str(worktree) in self.existing_worktrees

    def branch_exists(self, repo_dir, branch):
        self.operations.append(("branch_exists", branch))
        return branch in self.existing_branches or branch.startswith("preflight-")

    def create_worktree(self, repo_dir, worktree, branch):
        self.events.append("create_worktree")
        self.operations.append(("create_worktree", branch))
        self.worktrees.append((branch, worktree))
        return worktree

    def remove_worktree(self, repo_dir, worktree, worktrees_dir):
        self.events.append("remove_worktree")
        self.operations.append(("remove_worktree", str(worktree)))
        self.removed_worktrees.append(worktree)

    def delete_branch(self, repo_dir, branch):
        self.events.append("delete_branch")
        self.operations.append(("delete_branch", branch))
        self.deleted_branches.append(branch)

    def create_agent_cleanup_probe(self, worktree):
        self.events.append("create_agent_cleanup_probe")
        return worktree / "backend" / ".cleanup-probe"

    def write_file(self, worktree, relpath, content):
        return None

    def read_file(self, worktree, relpath):
        if relpath == "DECISIONS.md":
            return self.decisions
        if relpath == ".opencode/commands/implement.md":
            return self.command_body
        return ""

    def check(self, worktree):
        self.events.append("check")
        if "preflight" in str(worktree):
            return (self.preflight_check_passed, "")
        return (self.check_result, self.check_output)

    def commit_all(self, worktree, message):
        self.committed.append(message)
        return True

    def diff_stats(self, worktree):
        return self.diff

    def push(self, worktree, branch, token):
        self.pushed.append((branch, token))


class FakeGitHub:
    def __init__(
        self,
        tickets=None,
        pr_number=101,
        open_factory_prs=0,
        open_factory_prs_error=None,
    ):
        self.tickets = tickets or []
        self.pr_number = pr_number
        self.open_factory_prs = open_factory_prs
        self.open_factory_prs_error = open_factory_prs_error
        self.created_prs = []
        self.comments = []
        self.issue_labels = []
        self.pr_labels = []
        self.listed_with = None
        self.pr_counts = []

    def list_tickets(self, token=None):
        self.listed_with = token
        return list(self.tickets)

    def count_open_factory_prs(self, *, author, branch_prefix="nf/", token=None):
        self.pr_counts.append((author, branch_prefix, token))
        if self.open_factory_prs_error is not None:
            raise self.open_factory_prs_error
        return self.open_factory_prs

    def create_draft_pr(self, *, branch, title, body, token):
        self.created_prs.append((branch, title, body, token))
        return self.pr_number

    def add_pr_label(self, number, label, token):
        self.pr_labels.append((number, label, token))

    def add_issue_label(self, number, label, token):
        self.issue_labels.append((number, label, token))

    def comment(self, number, body, token):
        self.comments.append((number, body, token))
        return f"https://github.com/r/issues/{number}#comment-1"


class FakeTokenProvider:
    def __init__(self, token="TOKEN"):
        self.token = token
        self.calls = []

    def mint(self, repo):
        self.calls.append(repo)
        return self.token


class FailingTokenProvider:
    def __init__(self, error=None):
        self.error = error or RuntimeError("github api down")
        self.calls = []

    def mint(self, repo):
        self.calls.append(repo)
        raise self.error


class FakeRunner:
    def __init__(self, result=None):
        self.result = result or AgentResult(exit_code=0, stdout="", stderr="", timed_out=False)
        self.calls = []

    def run(self, *, worktree, model, prompt, timeout_seconds):
        self.calls.append({"model": model, "prompt": prompt, "worktree": worktree})
        return self.result


class ExplodingRunner:
    def __init__(self, error):
        self.error = error

    def run(self, *, worktree, model, prompt, timeout_seconds):
        raise self.error


class BaseExceptionRunner:
    def __init__(self, error):
        self.error = error

    def run(self, *, worktree, model, prompt, timeout_seconds):
        raise self.error


class RecordingNotifier:
    def __init__(self):
        self.pr_ready = []
        self.stuck = []
        self.run_failed = []
        self.paused = []

    def send_pr_ready(self, info):
        self.pr_ready.append(info)

    def send_stuck(self, info):
        self.stuck.append(info)

    def send_run_failed(self, info):
        self.run_failed.append(info)

    def send_paused(self, info):
        self.paused.append(info)


def make_settings(tmp_path):
    return Settings(
        factory_model="deepseek/deepseek-flash",
        factory_strong_model="deepseek/deepseek-v4-pro",
        repo="daedraMex/commerce-platform",
        max_tickets=1,
        attempts=5,
        repo_dir=tmp_path / "repo",
        worktrees_dir=tmp_path / "worktrees",
        logs_dir=tmp_path / "logs",
        state_dir=tmp_path / "state",
        time_limit_seconds=60,
        keep_days=14,
        telegram_bot_token=None,
        telegram_chat_id=None,
        github_app_id="12345",
        github_private_key="fake-key",
        github_installation_id="67890",
    )


def make_ticket(number, *, labels=()):
    return Ticket(
        number=number,
        title=f"Ticket {number}",
        labels=frozenset(labels),
    )


def _noop_verify_isolation(**_kwargs):
    return None


def _noop_verify_git_version():
    return None


def _noop_verify_sudoers_logging():
    return None


def build_factory(
    tmp_path,
    *,
    git,
    github,
    runner,
    notifier,
    settings=None,
    token_provider=None,
    ledger=None,
    pause_state=None,
):
    return Factory(
        settings or make_settings(tmp_path),
        github=github,
        git=git,
        runner=runner,
        notifier=notifier,
        token_provider=token_provider or FakeTokenProvider(),
        overlay=OVERLAY,
        preflight_verify_isolation=_noop_verify_isolation,
        preflight_verify_git_version=_noop_verify_git_version,
        preflight_verify_sudoers_logging=_noop_verify_sudoers_logging,
        preflight_clock=lambda: 42,
        ledger=ledger,
        pause_state=pause_state,
    )


def test_success_opens_draft_pr_and_notifies(tmp_path):
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})], pr_number=101)
    runner = FakeRunner()
    notifier = RecordingNotifier()
    factory = build_factory(tmp_path, git=git, github=github, runner=runner, notifier=notifier)

    results = factory.run()

    assert len(results) == 1 and results[0].ok
    assert len(github.created_prs) == 1
    branch, title, body, token = github.created_prs[0]
    assert branch == "nf/7-ticket-7"
    assert "Closes #7" in body
    assert "Built the thing." in body
    assert "Model: deepseek/deepseek-flash" in body
    assert "Chose A." in body
    assert git.pushed == [("nf/7-ticket-7", "TOKEN")]
    assert len(notifier.pr_ready) == 1


def test_fetch_main_runs_before_any_worktree_is_created(tmp_path):
    git = FakeGit(check_passed=True)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=RecordingNotifier()
    )

    factory.run()

    assert "fetch_main" in git.events
    assert git.events.index("fetch_main") < git.events.index("create_worktree")


def test_fetch_failure_aborts_the_run_and_notifies(tmp_path):
    git = FakeGit(fetch_error=RuntimeError("git fetch failed: no network"))
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=notifier
    )

    with pytest.raises(RuntimeError, match="git fetch failed"):
        factory.run()

    assert git.worktrees == []
    assert github.listed_with is None
    assert len(notifier.run_failed) == 1
    assert notifier.run_failed[0].reason.startswith("preflight failed: fetch origin/main:")
    assert "git fetch failed" in notifier.run_failed[0].reason


def test_unexpected_ticket_exception_becomes_a_run_failure_with_the_ticket(tmp_path):
    git = FakeGit(check_passed=True)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    factory = build_factory(
        tmp_path,
        git=git,
        github=github,
        runner=ExplodingRunner(RuntimeError("agent process exploded")),
        notifier=RecordingNotifier(),
    )

    with pytest.raises(RunFailed) as caught:
        factory.run()

    assert caught.value.phase == "#7 Ticket 7"
    assert caught.value.detail == "agent process exploded"


def test_preflight_check_failure_aborts_before_running_a_ticket(tmp_path):
    git = FakeGit(preflight_check_passed=False)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    runner = FakeRunner()
    notifier = RecordingNotifier()
    factory = build_factory(tmp_path, git=git, github=github, runner=runner, notifier=notifier)

    with pytest.raises(PreflightError, match="check.sh"):
        factory.run()

    assert runner.calls == []
    assert git.committed == []
    assert len(notifier.run_failed) == 1
    assert notifier.run_failed[0].reason.startswith("preflight failed: check.sh:")
    assert git.removed_worktrees
    assert git.deleted_branches


def test_preflight_cleans_up_its_throwaway_worktree_and_branch(tmp_path):
    git = FakeGit(check_passed=True)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=RecordingNotifier()
    )

    factory.run()

    assert git.removed_worktrees[0] == git.worktrees[0][1]
    assert git.deleted_branches == ["preflight-42"]


def test_retry_removes_existing_ticket_worktree_and_branch(tmp_path):
    branch = "nf/7-ticket-7"
    worktree = worktree_path(tmp_path / "worktrees", branch)
    git = FakeGit(check_passed=True)
    git.existing_worktrees = {str(worktree)}
    git.existing_branches = {branch}
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=RecordingNotifier()
    )

    factory.run()

    create = git.operations.index(("create_worktree", branch))
    assert git.operations.index(("remove_worktree", str(worktree))) < create
    assert git.operations.index(("delete_branch", branch)) < create


def test_retry_removes_only_the_existing_branch(tmp_path):
    branch = "nf/7-ticket-7"
    worktree = worktree_path(tmp_path / "worktrees", branch)
    git = FakeGit(check_passed=True)
    git.existing_branches = {branch}
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=RecordingNotifier()
    )

    factory.run()

    assert ("remove_worktree", str(worktree)) not in git.operations
    assert git.operations.index(("delete_branch", branch)) < git.operations.index(
        ("create_worktree", branch)
    )


def test_success_labels_migration_when_migrations_changed(tmp_path):
    diff = DiffStats(
        files=(FileChange(path="backend/apps/orders/migrations/0002_x.py", added=1, deleted=0),),
        migrations_changed=True,
    )
    git = FakeGit(check_passed=True, diff=diff)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=notifier
    )

    factory.run()

    assert github.pr_labels == [(101, "migration", "TOKEN")]


def test_protected_path_change_goes_stuck_without_push_or_pr(tmp_path):
    diff = DiffStats(
        files=(FileChange(path=".github/workflows/ci.yml", added=3, deleted=0),),
    )
    git = FakeGit(check_passed=True, diff=diff)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=notifier
    )

    results = factory.run()

    assert len(results) == 1 and not results[0].ok
    assert git.pushed == []
    assert github.created_prs == []
    assert notifier.stuck[0].failing_check == "protected path changed"


def test_failure_comments_and_labels_needs_decision(tmp_path):
    git = FakeGit(check_passed=False, decisions="- Tried X.")
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=notifier
    )

    results = factory.run()

    assert len(results) == 1 and not results[0].ok
    assert github.issue_labels == [(7, "needs-decision", "TOKEN")]
    assert len(github.comments) == 1
    assert len(notifier.stuck) == 1
    assert github.created_prs == []


def test_timeout_is_stuck(tmp_path):
    git = FakeGit(check_passed=False)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    runner = FakeRunner(AgentResult(exit_code=None, stdout="", stderr="", timed_out=True))
    notifier = RecordingNotifier()
    factory = build_factory(tmp_path, git=git, github=github, runner=runner, notifier=notifier)

    results = factory.run()

    assert not results[0].ok
    assert notifier.stuck[0].failing_check == "time budget exceeded"


def test_open_question_is_stuck(tmp_path):
    git = FakeGit(check_passed=True, decisions="OPEN QUESTION: POST or PUT?\n\n- Chose X.")
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=notifier
    )

    results = factory.run()

    assert not results[0].ok
    assert notifier.stuck[0].open_question == "POST or PUT?"
    assert github.created_prs == []


def test_stops_at_first_failure(tmp_path):
    settings = make_settings(tmp_path)
    settings = Settings(
        factory_model=settings.factory_model,
        factory_strong_model=settings.factory_strong_model,
        repo=settings.repo,
        max_tickets=2,
        attempts=settings.attempts,
        repo_dir=settings.repo_dir,
        worktrees_dir=settings.worktrees_dir,
        logs_dir=settings.logs_dir,
        state_dir=settings.state_dir,
        time_limit_seconds=settings.time_limit_seconds,
        keep_days=settings.keep_days,
        telegram_bot_token=None,
        telegram_chat_id=None,
        github_app_id="12345",
        github_private_key="fake-key",
        github_installation_id="67890",
    )
    git = FakeGit(check_passed=False)
    github = FakeGitHub(
        tickets=[
            make_ticket(7, labels={"ready-for-agent"}),
            make_ticket(8, labels={"ready-for-agent"}),
        ]
    )
    runner = FakeRunner()
    factory = build_factory(
        tmp_path,
        git=git,
        github=github,
        runner=runner,
        notifier=RecordingNotifier(),
        settings=settings,
    )

    results = factory.run()

    assert [r.ticket.number for r in results] == [7]
    assert len(runner.calls) == 5


def test_strong_model_ticket_runs_with_strong_model(tmp_path):
    git = FakeGit(check_passed=True)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent", "strong-model"})])
    runner = FakeRunner()
    factory = build_factory(
        tmp_path, git=git, github=github, runner=runner, notifier=RecordingNotifier()
    )

    factory.run()

    assert runner.calls[0]["model"] == "deepseek/deepseek-v4-pro"
    assert "deepseek/deepseek-v4-pro" in runner.calls[0]["prompt"]


def test_success_mints_token_and_scopes_it_to_push_and_pr(tmp_path):
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})], pr_number=101)
    token_provider = FakeTokenProvider(token="MINTED-TOKEN")
    factory = build_factory(
        tmp_path,
        git=git,
        github=github,
        runner=FakeRunner(),
        notifier=RecordingNotifier(),
        token_provider=token_provider,
    )

    factory.run()

    assert token_provider.calls == [
        "daedraMex/commerce-platform",
        "daedraMex/commerce-platform",
    ]
    assert github.listed_with == "MINTED-TOKEN"
    assert git.pushed == [("nf/7-ticket-7", "MINTED-TOKEN")]
    assert github.created_prs[0][3] == "MINTED-TOKEN"


def test_stuck_mints_token_and_scopes_it_to_comment_and_label(tmp_path):
    git = FakeGit(check_passed=False, decisions="- Tried X.")
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    token_provider = FakeTokenProvider(token="MINTED-TOKEN")
    factory = build_factory(
        tmp_path,
        git=git,
        github=github,
        runner=FakeRunner(),
        notifier=RecordingNotifier(),
        token_provider=token_provider,
    )

    factory.run()

    assert github.comments[0][2] == "MINTED-TOKEN"
    assert github.issue_labels[0][2] == "MINTED-TOKEN"


def test_open_pr_cap_reached_picks_no_ticket(tmp_path):
    settings = replace(make_settings(tmp_path), max_open_prs=2)
    git = FakeGit(check_passed=True)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})], open_factory_prs=2)
    runner = FakeRunner()
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path,
        git=git,
        github=github,
        runner=runner,
        notifier=notifier,
        settings=settings,
    )

    results = factory.run()

    assert results == []
    assert runner.calls == []
    assert github.listed_with is None
    assert git.worktrees == []
    assert [info.reason for info in notifier.paused] == ["2 PRs waiting for review"]


def test_daily_attempt_cap_reached_picks_no_ticket(tmp_path):
    now = datetime(2026, 11, 10, 10, 0, tzinfo=MEXICO_CITY)
    settings = replace(make_settings(tmp_path), max_tickets_per_day=2)
    ledger = AttemptLedger(settings.state_dir, clock=lambda: now)
    ledger.record_started(1, started_at=now)
    ledger.record_outcome(1, "stuck", finished_at=now)
    ledger.record_started(2, started_at=now)
    ledger.record_outcome(2, "ok", finished_at=now)
    git = FakeGit(check_passed=True)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    runner = FakeRunner()
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path,
        git=git,
        github=github,
        runner=runner,
        notifier=notifier,
        settings=settings,
        ledger=ledger,
    )

    results = factory.run()

    assert results == []
    assert runner.calls == []
    assert github.listed_with is None
    assert git.worktrees == []
    assert [info.reason for info in notifier.paused] == ["daily limit reached"]


def test_failed_attempts_count_toward_the_daily_cap(tmp_path):
    now = datetime(2026, 11, 10, 10, 0, tzinfo=MEXICO_CITY)
    settings = replace(make_settings(tmp_path), max_tickets_per_day=1)
    ledger = AttemptLedger(settings.state_dir, clock=lambda: now)
    git = FakeGit(check_passed=False)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    runner = FakeRunner()
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path,
        git=git,
        github=github,
        runner=runner,
        notifier=notifier,
        settings=settings,
        ledger=ledger,
    )

    first = factory.run()
    second = factory.run()

    assert len(first) == 1 and not first[0].ok
    assert second == []
    assert len(runner.calls) == settings.attempts
    assert ledger.count_today() == 1
    assert [info.reason for info in notifier.paused] == ["daily limit reached"]


def test_pause_notification_is_sent_once_per_transition(tmp_path):
    settings = replace(make_settings(tmp_path), max_open_prs=1)
    github = FakeGitHub(tickets=[], open_factory_prs=1)
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path,
        git=FakeGit(check_passed=True),
        github=github,
        runner=FakeRunner(),
        notifier=notifier,
        settings=settings,
    )

    factory.run()
    factory.run()
    assert [info.reason for info in notifier.paused] == ["1 PR waiting for review"]

    github.open_factory_prs = 0
    factory.run()
    assert len(notifier.paused) == 1

    github.open_factory_prs = 1
    factory.run()
    assert [info.reason for info in notifier.paused] == [
        "1 PR waiting for review",
        "1 PR waiting for review",
    ]


def test_counting_open_prs_failure_pauses_with_github_unreachable(tmp_path):
    settings = replace(make_settings(tmp_path), max_open_prs=2)
    github = FakeGitHub(
        tickets=[make_ticket(7, labels={"ready-for-agent"})],
        open_factory_prs_error=RuntimeError("network down"),
    )
    runner = FakeRunner()
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path,
        git=FakeGit(check_passed=True),
        github=github,
        runner=runner,
        notifier=notifier,
        settings=settings,
    )

    assert factory.run() == []
    assert factory.run() == []

    assert runner.calls == []
    assert github.listed_with is None
    assert [info.reason for info in notifier.paused] == ["GitHub unreachable"]


def test_token_mint_failure_pauses_with_github_unreachable_once(tmp_path):
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    token_provider = FailingTokenProvider()
    runner = FakeRunner()
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path,
        git=FakeGit(check_passed=True),
        github=github,
        runner=runner,
        notifier=notifier,
        token_provider=token_provider,
    )

    assert factory.run() == []
    assert factory.run() == []

    assert runner.calls == []
    assert github.listed_with is None
    assert [info.reason for info in notifier.paused] == ["GitHub unreachable"]


def test_base_exception_still_leaves_a_started_ledger_line(tmp_path):
    ledger = AttemptLedger(tmp_path / "state")
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    factory = build_factory(
        tmp_path,
        git=FakeGit(check_passed=True),
        github=github,
        runner=BaseExceptionRunner(KeyboardInterrupt()),
        notifier=RecordingNotifier(),
        ledger=ledger,
    )

    with pytest.raises(KeyboardInterrupt):
        factory.run()

    lines = ledger.path.read_text().splitlines()
    assert lines[0].split("\t")[2] == "started"
    assert ledger.count_today() == 1


def test_step_budget_exhausted_sticks_and_notifies(tmp_path):
    git = FakeGit(check_passed=False, decisions="- Tried X.")
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    runner = FakeRunner()
    notifier = RecordingNotifier()
    factory = build_factory(tmp_path, git=git, github=github, runner=runner, notifier=notifier)

    results = factory.run()

    assert not results[0].ok
    assert len(runner.calls) == 5
    assert notifier.stuck[0].failing_check == "step budget exceeded (5 attempts)"
    assert notifier.stuck[0].attempts == 5


def test_time_budget_exceeded_sticks_without_running(tmp_path):
    settings = replace(make_settings(tmp_path), time_limit_seconds=0)
    git = FakeGit(check_passed=True)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    runner = FakeRunner()
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path, git=git, github=github, runner=runner, notifier=notifier, settings=settings
    )

    results = factory.run()

    assert not results[0].ok
    assert len(runner.calls) == 0
    assert notifier.stuck[0].failing_check == "time budget exceeded"
    assert notifier.stuck[0].attempts == 0


def test_fix_loop_feeds_check_output_back_to_agent(tmp_path):
    git = FakeGit(check_passed=False, check_output="E   AssertionError")
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    runner = FakeRunner()
    factory = build_factory(
        tmp_path, git=git, github=github, runner=runner, notifier=RecordingNotifier()
    )

    factory.run()

    assert len(runner.calls) == 5
    assert "E   AssertionError" not in runner.calls[0]["prompt"]
    assert "E   AssertionError" in runner.calls[1]["prompt"]


class FakePreflightFactory:
    def __init__(self, *, tickets=None, error=None, run_error=None):
        self.tickets = tickets or []
        self.error = error
        self.run_error = run_error

    def run_preflight(self):
        if self.error is not None:
            raise self.error
        return self.tickets

    def run(self):
        if self.run_error is not None:
            raise self.run_error
        raise AssertionError("the preflight CLI must not run tickets")


def test_preflight_cli_reports_success(monkeypatch, capsys, tmp_path):
    import factory.main as main_module

    fake = FakePreflightFactory(tickets=[make_ticket(7)])
    monkeypatch.setattr(main_module, "_build_factory", lambda settings, notifier=None: fake)
    monkeypatch.setattr(
        main_module.Settings, "from_env", classmethod(lambda cls: make_settings(tmp_path))
    )

    assert main_module.main(["preflight"]) == 0
    assert "preflight ok (1 tickets listed)" in capsys.readouterr().out


def test_preflight_cli_reports_failure_and_exits_nonzero(monkeypatch, capsys, tmp_path):
    import factory.main as main_module

    fake = FakePreflightFactory(error=PreflightError("check.sh", "check.sh failed"))
    monkeypatch.setattr(main_module, "_build_factory", lambda settings, notifier=None: fake)
    monkeypatch.setattr(
        main_module.Settings, "from_env", classmethod(lambda cls: make_settings(tmp_path))
    )

    assert main_module.main(["preflight"]) == 1
    assert "preflight failed: check.sh: check.sh failed" in capsys.readouterr().out


def test_main_reports_an_unexpected_run_error_and_notifies(monkeypatch, capsys, tmp_path):
    import factory.main as main_module

    notifier = RecordingNotifier()
    fake = FakePreflightFactory(run_error=RuntimeError("kaboom"))
    monkeypatch.setattr(main_module, "_build_factory", lambda settings, notifier=None: fake)
    monkeypatch.setattr(main_module, "_build_notifier", lambda settings: notifier)
    monkeypatch.setattr(
        main_module.Settings, "from_env", classmethod(lambda cls: make_settings(tmp_path))
    )

    assert main_module.main([]) == 1
    assert notifier.run_failed[0].reason == "run failed: run: kaboom"
    assert "run failed: run: kaboom" in capsys.readouterr().out


def test_main_reports_a_settings_failure_and_notifies(monkeypatch, capsys):
    import factory.main as main_module

    notifier = RecordingNotifier()

    def fail(_cls):
        raise RuntimeError("FACTORY_MODEL is not set")

    monkeypatch.setattr(main_module.Settings, "from_env", classmethod(fail))
    monkeypatch.setattr(main_module, "_startup_notifier", lambda: notifier)

    assert main_module.main([]) == 1
    assert notifier.run_failed[0].reason == "run failed: startup: FACTORY_MODEL is not set"
    assert "run failed: startup: FACTORY_MODEL is not set" in capsys.readouterr().out


def test_stuck_keeps_worktree_and_includes_handoff(tmp_path):
    settings = replace(make_settings(tmp_path), handoff_host="factory@host")
    git = FakeGit(check_passed=False)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=notifier, settings=settings
    )

    factory.run()

    info = notifier.stuck[0]
    assert info.worktree.endswith("nf-7-ticket-7")
    assert Path(info.worktree).parent == settings.worktrees_dir
    assert info.handoff_command == f"ssh factory@host && cd {info.worktree}"
