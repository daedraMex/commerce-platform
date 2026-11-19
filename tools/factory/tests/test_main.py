import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from factory.areas import CONSOLE
from factory.config import Settings
from factory.diff import DiffStats, FileChange
from factory.git import CheckResult
from factory.github import GitHubError
from factory.holds import LabelHolds
from factory.ledger import AttemptLedger
from factory.main import Factory, RunFailed
from factory.preflight import PreflightError
from factory.review_attempts import ReviewAttemptLedger
from factory.reviews import ReviewComment, ReviewFix
from factory.runner import AgentResult
from factory.shell import CommandResult
from factory.tickets import REQUIRED_LABELS, Ticket, worktree_path

MEXICO_CITY = ZoneInfo("America/Mexico_City")

OVERLAY = "Model: {{MODEL}}. Branch: {{BRANCH}}."

COMMAND_BODY = "Read .agents/skills/implement/SKILL.md and follow it.\n\n$ARGUMENTS"

DECISIONS_DOC = "# Summary\nBuilt the thing.\n\n# Decisions\n\n- Chose A.\n"


DEFAULT_DIFF = DiffStats(files=(FileChange(path="backend/apps/x/views.py", added=3, deleted=1),))


class FakeGit:
    def __init__(
        self,
        *,
        check_passed=True,
        check_output="",
        failed_areas=(),
        decisions="",
        diff=None,
        command_body=COMMAND_BODY,
        fetch_error=None,
        preflight_check_passed=True,
        merge_conflict=False,
        commit_changed=True,
        remote_branches=(),
    ):
        self.check_result = check_passed
        self.check_output = check_output
        self.failed_areas = failed_areas
        self.decisions = decisions
        self.diff = diff if diff is not None else DEFAULT_DIFF
        self.command_body = command_body
        self.fetch_error = fetch_error
        self.preflight_check_passed = preflight_check_passed
        self.merge_conflict = merge_conflict
        self.commit_changed = commit_changed
        self.remote_branches = set(remote_branches)
        self.remote_checks = []
        self.merged = []
        self.committed = []
        self.pushed = []
        self.worktrees = []
        self.created_from = []
        self.fetched_branches = []
        self.diff_since = []
        self.ref_reads = []
        self.review_rules = "## Rules\n\n### 1. Multi-step writes commit together"
        self.fingerprints = []
        self.reviewer_config = '{"permission": {"edit": {"*": "deny"}}}'
        self.builder_config = '{"permission": {"edit": {"AGENTS.md": "deny"}}}'
        self.worktree_reviewer_config = None
        self.review_files = ["backend/apps/x.py"]
        self.dependency_old = {}
        self.dependency_new = {}
        self.check_script = []
        self.removed_worktrees = []
        self.deleted_branches = []
        self.events = []
        self.operations = []
        self.existing_worktrees = set()
        self.existing_branches = set()
        self.head_sha_value = "a" * 40
        self.placed_tests = []
        self.attack_runs = []
        self.attack_results = []
        self.removed_tests = []

    def fetch_main(self, repo_dir):
        self.events.append("fetch_main")
        if self.fetch_error is not None:
            raise self.fetch_error

    def merge_main(self, worktree):
        self.events.append("merge_main")
        self.merged.append(str(worktree))
        return not self.merge_conflict

    def fetch_branch(self, repo_dir, branch):
        self.events.append("fetch_branch")
        if self.fetch_error is not None:
            raise self.fetch_error
        self.fetched_branches.append(branch)

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

    def create_worktree_from(self, repo_dir, worktree, branch, base):
        self.events.append("create_worktree")
        self.operations.append(("create_worktree", branch))
        self.worktrees.append((branch, worktree))
        self.created_from.append((branch, base))
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
        if relpath in self.dependency_new:
            return self.dependency_new[relpath]
        if relpath == "DECISIONS.md":
            return self.decisions
        if relpath == ".opencode/commands/implement.md":
            return self.command_body
        if relpath == "tools/factory/opencode.reviewer.json":
            if self.worktree_reviewer_config is not None:
                return self.worktree_reviewer_config
            return self.reviewer_config
        return ""

    def read_ref_file(self, repo_dir, ref, path):
        self.ref_reads.append((str(repo_dir), ref, path))
        if path in self.dependency_old:
            old = self.dependency_old[path]
            if old is None:
                raise RuntimeError(f"git show {ref}:{path} failed: does not exist")
            return old
        if path == "tools/factory/opencode.reviewer.json":
            return self.reviewer_config
        if path == "tools/factory/opencode.factory.json":
            return self.builder_config
        return self.review_rules

    def review_diff(self, worktree):
        return "diff --git a/x.py b/x.py\n+x = 1\n"

    def review_changed_files(self, worktree):
        return list(self.review_files)

    def place_review_tests(self, worktree, tests):
        self.placed_tests.append(dict(tests))

    def run_review_tests(self, worktree, files):
        self.attack_runs.append(tuple(files))
        return self.attack_results.pop(0) if self.attack_results else ("held", "1 passed")

    def remove_review_tests(self, worktree, relpaths):
        self.removed_tests.append(tuple(relpaths))

    def worktree_fingerprint(self, worktree):
        if self.fingerprints:
            return self.fingerprints.pop(0)
        return "same"

    def check(self, worktree, *, areas=None):
        self.events.append("check")
        if "preflight" in str(worktree):
            return CheckResult(self.preflight_check_passed, "")
        if self.check_script:
            passed = self.check_script.pop(0)
            return CheckResult(passed, "" if passed else "1 failed", ())
        return CheckResult(self.check_result, self.check_output, self.failed_areas)

    def commit_all(self, worktree, message):
        self.committed.append(message)
        return self.commit_changed

    def diff_stats(self, worktree, *, since=None):
        if since is not None:
            self.diff_since.append((str(worktree), since))
        return self.diff

    def head_sha(self, worktree):
        return self.head_sha_value

    def remote_branch_exists(self, repo_dir, branch, token):
        self.remote_checks.append((branch, token))
        return branch in self.remote_branches

    def push(self, worktree, branch, token):
        self.pushed.append((branch, token))


class FakeGitHub:
    def __init__(
        self,
        tickets=None,
        pr_number=101,
        open_factory_prs=0,
        open_factory_prs_error=None,
        ready_exit=0,
        ready_stderr="",
        auto_merge_exit=0,
        auto_merge_stderr="",
        review_fixes=None,
        review_fixes_error=None,
        pr_error=None,
        open_pr_branches=(),
        issue_label_errors=0,
        pr_label_error=None,
        pr_bodies=None,
        pr_body_error=None,
    ):
        self.pr_bodies = dict(pr_bodies or {})
        self.created_issues = []
        self.issue_error = None
        self.pr_body_error = pr_body_error
        self.edited_bodies = []
        self.tickets = tickets or []
        # How many add_issue_label calls fail before one succeeds.
        self.issue_label_errors = issue_label_errors
        self.pr_label_error = pr_label_error
        self.issue_label_attempts = []
        self.pr_number = pr_number
        self.open_factory_prs = open_factory_prs
        self.open_factory_prs_error = open_factory_prs_error
        self.ready_exit = ready_exit
        self.ready_stderr = ready_stderr
        self.auto_merge_exit = auto_merge_exit
        self.auto_merge_stderr = auto_merge_stderr
        self.review_fixes = review_fixes or []
        self.review_fixes_error = review_fixes_error
        self.pr_error = pr_error
        self.open_pr_branches = set(open_pr_branches)
        self.open_pr_checks = []
        self.created_prs = []
        self.ready_prs = []
        self.auto_merges = []
        self.comments = []
        self.issue_labels = []
        self.pr_labels = []
        self.listed_with = None
        self.pr_counts = []
        self.review_fix_calls = []
        self.attempted_review_ids = set()

    def list_tickets(self, token=None):
        self.listed_with = token
        return list(self.tickets)

    def list_review_fixes(
        self,
        *,
        author,
        owner,
        branch_prefix="nf/",
        attempted_review_ids=frozenset(),
        token=None,
    ):
        self.review_fix_calls.append((author, owner, branch_prefix, token))
        self.attempted_review_ids = set(attempted_review_ids)
        if self.review_fixes_error is not None:
            raise self.review_fixes_error
        return list(self.review_fixes)

    def count_open_factory_prs(self, *, author, branch_prefix="nf/", token=None):
        self.pr_counts.append((author, branch_prefix, token))
        if self.open_factory_prs_error is not None:
            raise self.open_factory_prs_error
        return self.open_factory_prs

    def create_draft_pr(self, *, branch, title, body, token):
        if self.pr_error is not None:
            raise self.pr_error
        self.created_prs.append((branch, title, body, token))
        return self.pr_number

    def has_open_pr_for_branch(self, branch, token):
        self.open_pr_checks.append((branch, token))
        return branch in self.open_pr_branches

    def mark_pr_ready(self, number, token):
        self.ready_prs.append((number, token))
        return CommandResult(exit_code=self.ready_exit, stdout="", stderr=self.ready_stderr)

    def enable_auto_merge(self, number, token):
        self.auto_merges.append((number, token))
        return CommandResult(
            exit_code=self.auto_merge_exit, stdout="", stderr=self.auto_merge_stderr
        )

    def add_pr_label(self, number, label, token):
        if self.pr_label_error is not None:
            raise self.pr_label_error
        self.pr_labels.append((number, label, token))

    def add_issue_label(self, number, label, token):
        self.issue_label_attempts.append((number, label))
        if self.issue_label_errors > 0:
            self.issue_label_errors -= 1
            raise GitHubError(f"could not add label {label} to issue #{number}: not found")
        self.issue_labels.append((number, label, token))

    def list_label_names(self, token=None):
        return REQUIRED_LABELS

    def comment(self, number, body, token):
        self.comments.append((number, body, token))
        return f"https://github.com/r/issues/{number}#comment-1"

    def create_issue(self, *, title, body, token):
        if self.issue_error is not None:
            raise self.issue_error
        self.created_issues.append((title, body, token))
        return 200 + len(self.created_issues)

    def pr_body(self, number, token):
        if self.pr_body_error is not None:
            raise self.pr_body_error
        return self.pr_bodies.get(number, "Closes #7\n")

    def edit_pr_body(self, number, body, token):
        self.edited_bodies.append((number, body, token))
        self.pr_bodies[number] = body


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
    def ensure_clean(self):
        pass

    def verify_home_is_clean(self):
        pass

    def smoke_check(self, worktree):
        pass

    def __init__(self, result=None):
        self.result = result or AgentResult(exit_code=0, stdout="", stderr="", timed_out=False)
        self.calls = []

    def run(
        self,
        *,
        worktree,
        model,
        prompt,
        timeout_seconds,
        config_path=None,
        config_content=None,
        disable_project_config=False,
    ):
        self.calls.append(
            {
                "model": model,
                "prompt": prompt,
                "worktree": worktree,
                "config_path": config_path,
                "config_content": config_content,
                "disable_project_config": disable_project_config,
            }
        )
        return self.result


class ExplodingRunner:
    def ensure_clean(self):
        pass

    def verify_home_is_clean(self):
        pass

    def smoke_check(self, worktree):
        pass

    def __init__(self, error):
        self.error = error

    def run(self, *, worktree, model, prompt, timeout_seconds, **_options):
        raise self.error


class BaseExceptionRunner:
    def ensure_clean(self):
        pass

    def verify_home_is_clean(self):
        pass

    def smoke_check(self, worktree):
        pass

    def __init__(self, error):
        self.error = error

    def run(self, *, worktree, model, prompt, timeout_seconds, **_options):
        raise self.error


class RecordingNotifier:
    def __init__(self):
        self.pr_ready = []
        self.stuck = []
        self.run_failed = []
        self.paused = []
        self.review_addressed = []
        self.review_skipped = []

    def send_pr_ready(self, info):
        self.pr_ready.append(info)

    def send_stuck(self, info):
        self.stuck.append(info)

    def send_run_failed(self, info):
        self.run_failed.append(info)

    def send_paused(self, info):
        self.paused.append(info)

    def send_review_addressed(self, info):
        self.review_addressed.append(info)

    def send_review_skipped(self, info):
        self.review_skipped.append(info)


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


def make_review_fix(
    *, review_id="5866656710", pr_number=101, ticket_number=7, branch="nf/7-ticket-7"
):
    return ReviewFix(
        review_id=review_id,
        pr_number=pr_number,
        branch=branch,
        ticket=Ticket(number=ticket_number, title=f"Ticket {ticket_number}"),
        review_body="Please rename this.",
        comments=(
            ReviewComment(path="backend/apps/x/views.py", line=42, body="Use a better name."),
        ),
        submitted_at=datetime(2026, 11, 10, 10, 0, tzinfo=MEXICO_CITY),
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
    review_attempts=None,
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
        review_attempts=review_attempts,
        pause_state=pause_state,
    )


def test_success_opens_ready_pr_enables_auto_merge_and_notifies(tmp_path, capsys):
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
    assert github.ready_prs == [(101, "TOKEN")]
    assert github.auto_merges == [(101, "TOKEN")]
    assert capsys.readouterr().err == ""
    assert len(notifier.pr_ready) == 1


def test_auto_merge_failure_keeps_the_run_successful_and_logs_why(tmp_path, capsys):
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    github = FakeGitHub(
        tickets=[make_ticket(7, labels={"ready-for-agent"})],
        pr_number=101,
        auto_merge_exit=1,
        auto_merge_stderr="Auto-merge is not allowed for this repository",
    )
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=notifier
    )

    results = factory.run()

    assert len(results) == 1 and results[0].ok
    assert github.ready_prs == [(101, "TOKEN")]
    assert github.auto_merges == [(101, "TOKEN")]
    assert len(notifier.pr_ready) == 1
    err = capsys.readouterr().err
    assert "auto-merge not enabled for PR #101" in err
    assert "Auto-merge is not allowed for this repository" in err


def test_ready_failure_keeps_the_run_successful_and_logs_why(tmp_path, capsys):
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    github = FakeGitHub(
        tickets=[make_ticket(7, labels={"ready-for-agent"})],
        pr_number=101,
        ready_exit=1,
        ready_stderr="Pull request is not a draft",
    )
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=notifier
    )

    results = factory.run()

    assert len(results) == 1 and results[0].ok
    assert len(github.created_prs) == 1
    assert github.ready_prs == [(101, "TOKEN")]
    assert github.auto_merges == [(101, "TOKEN")]
    assert len(notifier.pr_ready) == 1
    err = capsys.readouterr().err
    assert "PR #101 stays a draft" in err
    assert "Pull request is not a draft" in err


def test_fetch_main_runs_before_any_worktree_is_created(tmp_path):
    git = FakeGit(check_passed=True)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=RecordingNotifier()
    )

    factory.run()

    assert "fetch_main" in git.events
    assert git.events.index("fetch_main") < git.events.index("create_worktree")


def test_ticket_fetches_main_itself_after_the_preflight(tmp_path):
    git = FakeGit(check_passed=True)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=RecordingNotifier()
    )

    factory.run()

    after_preflight = git.events[git.events.index("create_agent_cleanup_probe") + 1 :]
    ticket_worktree = after_preflight.index("create_worktree")
    assert "fetch_main" in after_preflight[:ticket_worktree]


def test_success_pr_body_carries_verification_risk_and_revert(tmp_path):
    git = FakeGit(check_passed=True)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=RecordingNotifier()
    )

    factory.run()

    body = github.created_prs[0][2]
    assert "## Verification" in body
    assert "Agent steps: 1 of 5" in body
    assert "## Risk" in body
    assert "## How to revert" in body


def test_success_pr_body_names_the_checked_commit_and_the_check_output(tmp_path):
    git = FakeGit(check_passed=True, check_output="=== backend ===\n512 passed in 3.0s")
    git.head_sha_value = "b" * 40
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=RecordingNotifier()
    )

    factory.run()

    body = github.created_prs[0][2]
    assert f"<!-- factory:verification sha={'b' * 40} -->" in body
    assert "512 passed in 3.0s" in body


def test_review_fix_updates_the_evidence_before_pushing(tmp_path):
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    git.head_sha_value = "e" * 40
    old_body = (
        "Closes #7\n\n<!-- factory:verification sha=" + "c" * 40 + " -->\n"
        "## Verification\n\nold\n<!-- /factory:verification -->\n\n## Risk\n"
    )
    github = FakeGitHub(review_fixes=[make_review_fix()], pr_bodies={101: old_body})
    pushed_when_edited = []
    record_edit = github.edit_pr_body

    def edit(number, body, token):
        pushed_when_edited.append(list(git.pushed))
        record_edit(number, body, token)

    github.edit_pr_body = edit
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=RecordingNotifier()
    )

    factory.run()

    assert pushed_when_edited == [[]]
    number, body, _token = github.edited_bodies[0]
    assert number == 101
    assert f"sha={'e' * 40}" in body
    assert f"sha={'c' * 40}" not in body
    assert "## Risk" in body
    assert git.pushed == [("nf/7-ticket-7", "TOKEN")]


def test_review_fix_whose_body_cannot_be_read_goes_stuck_without_push(tmp_path):
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    github = FakeGitHub(
        review_fixes=[make_review_fix()],
        pr_body_error=GitHubError("gh api pulls/101 failed: HTTP 502"),
    )
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=notifier
    )

    results = factory.run()

    assert git.pushed == []
    assert github.edited_bodies == []
    assert results[0].ok is False
    assert [number for number, _body, _token in github.comments] == [7]
    assert "PR body evidence not updated" in github.comments[0][1]


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


def test_fix_loop_names_the_real_failing_area_and_script(tmp_path):
    git = FakeGit(
        check_passed=False,
        check_output="console failed",
        failed_areas=(CONSOLE,),
    )
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    runner = FakeRunner()
    factory = build_factory(
        tmp_path, git=git, github=github, runner=runner, notifier=RecordingNotifier()
    )

    factory.run()

    prompt = runner.calls[1]["prompt"]
    assert "`console`" in prompt
    assert "`web/console/scripts/check.sh`" in prompt


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


def test_metrics_cli_routes_to_the_metrics_command(monkeypatch, tmp_path):
    import factory.main as main_module

    calls = []
    monkeypatch.setattr(
        main_module.Settings, "from_env", classmethod(lambda cls: make_settings(tmp_path))
    )
    monkeypatch.setattr(main_module, "_build_notifier", lambda settings: RecordingNotifier())
    monkeypatch.setattr(main_module, "_build_token_provider", lambda settings: FakeTokenProvider())
    monkeypatch.setattr(
        main_module,
        "run_metrics",
        lambda collector, notifier, tokens, *, repo, now: calls.append((collector.repo, repo)) or 0,
    )

    assert main_module.main(["metrics"]) == 0
    assert calls == [(make_settings(tmp_path).repo, make_settings(tmp_path).repo)]


def test_metrics_cli_reports_bad_settings_and_exits_nonzero(monkeypatch, capsys):
    import factory.main as main_module

    def broken(cls):
        raise RuntimeError("FACTORY_MODEL is not set")

    monkeypatch.setattr(main_module.Settings, "from_env", classmethod(broken))

    assert main_module.main(["metrics"]) == 1
    assert "metrics failed: FACTORY_MODEL is not set" in capsys.readouterr().out


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


def test_notification_failure_keeps_the_pr_success_and_ledger_outcome(tmp_path, capsys):
    from factory.notify import TelegramNotifier

    def post(url, payload):
        raise RuntimeError(f"telegram is down: {url} {payload['chat_id']}")

    notifier = TelegramNotifier("token123", "chat456", post=post)
    ledger = AttemptLedger(tmp_path / "state")
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})], pr_number=101)
    factory = build_factory(
        tmp_path,
        git=git,
        github=github,
        runner=FakeRunner(),
        notifier=notifier,
        ledger=ledger,
    )

    results = factory.run()

    assert len(results) == 1 and results[0].ok
    assert len(github.created_prs) == 1
    lines = ledger.path.read_text().splitlines()
    assert [line.split("\t")[2] for line in lines] == ["started", "ok"]
    err = capsys.readouterr().err
    assert "token123" not in err
    assert "chat456" not in err


def test_review_fix_runs_before_a_new_ticket_and_records_one_attempt(tmp_path):
    fix = make_review_fix()
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    github = FakeGitHub(
        tickets=[make_ticket(8, labels={"ready-for-agent"})],
        review_fixes=[fix],
    )
    runner = FakeRunner()
    notifier = RecordingNotifier()
    ledger = AttemptLedger(tmp_path / "state")
    factory = build_factory(
        tmp_path,
        git=git,
        github=github,
        runner=runner,
        notifier=notifier,
        ledger=ledger,
    )

    results = factory.run()

    assert [result.ticket.number for result in results] == [7]
    assert len(runner.calls) == 1
    assert "Please rename this." in runner.calls[0]["prompt"]
    assert "Use a better name." in runner.calls[0]["prompt"]
    assert "untrusted data" in runner.calls[0]["prompt"]
    assert git.fetched_branches == ["nf/7-ticket-7"]
    assert git.created_from == [("nf/7-ticket-7", "origin/nf/7-ticket-7")]
    assert git.committed == ["fix: address review on #101"]
    assert git.pushed == [("nf/7-ticket-7", "TOKEN")]
    assert github.created_prs == []
    assert github.comments == [
        (
            101,
            f"Addressed the review in {'a' * 40}; please re-review.",
            "TOKEN",
        )
    ]
    assert len(notifier.review_addressed) == 1
    assert notifier.review_addressed[0].pr_number == 101
    assert ledger.count_today() == 1
    assert factory.review_attempts.attempted_ids() == {"5866656710"}
    lines = ledger.path.read_text().splitlines()
    assert [(line.split("\t")[1], line.split("\t")[2]) for line in lines] == [
        ("#7", "started"),
        ("#7", "ok"),
    ]


def test_review_fix_takes_only_the_first_candidate_per_run(tmp_path):
    first = make_review_fix(pr_number=101, ticket_number=7, branch="nf/7-ticket-7")
    second = make_review_fix(pr_number=102, ticket_number=9, branch="nf/9-ticket-9")
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    github = FakeGitHub(review_fixes=[first, second])
    runner = FakeRunner()
    factory = build_factory(
        tmp_path,
        git=git,
        github=github,
        runner=runner,
        notifier=RecordingNotifier(),
    )

    results = factory.run()

    assert [result.ticket.number for result in results] == [7]
    assert git.fetched_branches == ["nf/7-ticket-7"]
    assert len(runner.calls) == 1


def test_review_fix_failure_uses_the_stuck_flow(tmp_path):
    fix = make_review_fix()
    git = FakeGit(check_passed=False, decisions="- Tried X.")
    github = FakeGitHub(review_fixes=[fix])
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path,
        git=git,
        github=github,
        runner=FakeRunner(),
        notifier=notifier,
    )

    results = factory.run()

    assert len(results) == 1 and not results[0].ok
    assert git.pushed == []
    assert len(github.comments) == 1
    assert github.comments[0][0] == 7
    assert github.comments[0][1].startswith("The night factory could not finish")
    assert github.issue_labels == [(7, "needs-decision", "TOKEN")]
    assert "protected" not in notifier.stuck[0].failing_check


def test_review_fix_protected_path_goes_stuck_without_push(tmp_path):
    diff = DiffStats(
        files=(FileChange(path=".github/workflows/ci.yml", added=3, deleted=0),),
    )
    git = FakeGit(check_passed=True, diff=diff, decisions=DECISIONS_DOC)
    github = FakeGitHub(review_fixes=[make_review_fix()])
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path,
        git=git,
        github=github,
        runner=FakeRunner(),
        notifier=notifier,
    )

    results = factory.run()

    assert len(results) == 1 and not results[0].ok
    assert git.pushed == []
    assert notifier.stuck[0].failing_check == "protected path changed"


def test_review_fix_already_committed_by_the_agent_is_pushed_not_stuck(tmp_path):
    # The agent ran `git commit` itself: commit_all has nothing left (False),
    # but the diff since the fix's base carries its work (#137).
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC, commit_changed=False)
    github = FakeGitHub(review_fixes=[make_review_fix()])
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=notifier
    )

    results = factory.run()

    assert len(results) == 1 and results[0].ok
    assert git.pushed == [("nf/7-ticket-7", "TOKEN")]
    assert notifier.stuck == []
    assert github.comments[0][1].startswith("Addressed the review in ")


def test_review_fix_with_no_diff_since_its_base_goes_stuck_without_push(tmp_path):
    git = FakeGit(
        check_passed=True, decisions=DECISIONS_DOC, commit_changed=False, diff=DiffStats()
    )
    github = FakeGitHub(review_fixes=[make_review_fix()])
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=notifier
    )

    results = factory.run()

    assert len(results) == 1 and not results[0].ok
    assert git.pushed == []
    assert notifier.stuck[0].failing_check == "no changes made for the review"


def test_review_fix_listing_failure_is_skipped_and_a_ticket_still_runs(tmp_path, capsys):
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    github = FakeGitHub(
        tickets=[make_ticket(8, labels={"ready-for-agent"})],
        review_fixes_error=RuntimeError("reviews unavailable"),
    )
    runner = FakeRunner()
    factory = build_factory(
        tmp_path,
        git=git,
        github=github,
        runner=runner,
        notifier=RecordingNotifier(),
    )

    results = factory.run()

    assert [result.ticket.number for result in results] == [8]
    assert git.fetched_branches == []
    assert "skipping review fixes: reviews unavailable" in capsys.readouterr().err


def test_review_fix_github_error_sends_one_notice_and_a_ticket_still_runs(tmp_path, capsys):
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    github = FakeGitHub(
        tickets=[make_ticket(8, labels={"ready-for-agent"})],
        review_fixes_error=GitHubError("gh api reviews failed: HTTP 404"),
    )
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path,
        git=git,
        github=github,
        runner=FakeRunner(),
        notifier=notifier,
    )

    results = factory.run()

    assert [result.ticket.number for result in results] == [8]
    assert "skipping review fixes: gh api reviews failed: HTTP 404" in capsys.readouterr().err
    assert len(notifier.review_skipped) == 1
    assert notifier.review_skipped[0].reason == "gh api reviews failed: HTTP 404"


def test_review_fix_listing_failure_that_is_not_a_github_error_sends_no_notice(tmp_path):
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    github = FakeGitHub(
        tickets=[make_ticket(8, labels={"ready-for-agent"})],
        review_fixes_error=RuntimeError("reviews unavailable"),
    )
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path,
        git=git,
        github=github,
        runner=FakeRunner(),
        notifier=notifier,
    )

    factory.run()

    assert notifier.review_skipped == []


def test_review_fix_runs_even_when_the_open_pr_cap_is_reached(tmp_path):
    settings = replace(make_settings(tmp_path), max_open_prs=1)
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    github = FakeGitHub(
        review_fixes=[make_review_fix()],
        open_factory_prs=1,
    )
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path,
        git=git,
        github=github,
        runner=FakeRunner(),
        notifier=notifier,
        settings=settings,
    )

    results = factory.run()

    assert len(results) == 1 and results[0].ok
    assert notifier.paused == []
    assert git.pushed == [("nf/7-ticket-7", "TOKEN")]


def test_daily_cap_still_blocks_review_fixes(tmp_path):
    now = datetime(2026, 11, 10, 10, 0, tzinfo=MEXICO_CITY)
    settings = replace(make_settings(tmp_path), max_tickets_per_day=1)
    ledger = AttemptLedger(settings.state_dir, clock=lambda: now)
    ledger.record_started(1, started_at=now)
    git = FakeGit(check_passed=True)
    github = FakeGitHub(review_fixes=[make_review_fix()])
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
    assert git.fetched_branches == []
    assert [info.reason for info in notifier.paused] == ["daily limit reached"]


def test_a_stuck_review_fix_is_not_picked_on_the_next_run(tmp_path):
    fix = make_review_fix(review_id="5866656710")
    git = FakeGit(check_passed=False)
    github = FakeGitHub(review_fixes=[fix])
    runner = FakeRunner()
    review_attempts = ReviewAttemptLedger(tmp_path / "state")
    factory = build_factory(
        tmp_path,
        git=git,
        github=github,
        runner=runner,
        notifier=RecordingNotifier(),
        review_attempts=review_attempts,
    )

    first = factory.run()
    second = factory.run()

    assert len(first) == 1 and not first[0].ok
    assert second == []
    assert len(runner.calls) == 5
    assert review_attempts.attempted_ids() == {"5866656710"}
    assert github.attempted_review_ids == {"5866656710"}


def test_a_newer_review_on_the_same_pr_is_picked_up_again(tmp_path):
    first_fix = make_review_fix(review_id="5866656710")
    newer_fix = make_review_fix(review_id="5866656711")
    git = FakeGit(check_passed=False)
    github = FakeGitHub(review_fixes=[first_fix])
    runner = FakeRunner()
    review_attempts = ReviewAttemptLedger(tmp_path / "state")
    factory = build_factory(
        tmp_path,
        git=git,
        github=github,
        runner=runner,
        notifier=RecordingNotifier(),
        review_attempts=review_attempts,
    )

    factory.run()
    github.review_fixes = [newer_fix]
    factory.run()

    assert len(runner.calls) == 10
    assert github.attempted_review_ids == {"5866656710"}
    assert review_attempts.attempted_ids() == {"5866656710", "5866656711"}


def test_review_fix_merges_main_before_the_agent_runs(tmp_path):
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    github = FakeGitHub(review_fixes=[make_review_fix()])
    runner = FakeRunner()
    factory = build_factory(
        tmp_path,
        git=git,
        github=github,
        runner=runner,
        notifier=RecordingNotifier(),
    )

    results = factory.run()

    assert len(results) == 1 and results[0].ok
    assert len(git.merged) == 1 and git.merged[0].endswith("nf-7-ticket-7")
    events = git.events
    merge_at = events.index("merge_main")
    before = events[:merge_at]
    # The review worktree exists and main was fetched right before the merge,
    # and the agent's check runs only after it.
    assert before[-2:] == ["create_worktree", "fetch_main"]
    assert "check" in events[merge_at:]
    assert git.pushed == [("nf/7-ticket-7", "TOKEN")]


def test_review_fix_measures_protected_paths_after_the_merge(tmp_path):
    # Changes that main brings in (for example to tools/factory) must not count
    # as the agent's changes: the base is taken after the merge.
    class MergingGit(FakeGit):
        def merge_main(self, worktree):
            self.head_sha_value = "m" * 40
            return super().merge_main(worktree)

    git = MergingGit(check_passed=True, decisions=DECISIONS_DOC)
    github = FakeGitHub(review_fixes=[make_review_fix()])
    factory = build_factory(
        tmp_path,
        git=git,
        github=github,
        runner=FakeRunner(),
        notifier=RecordingNotifier(),
    )

    factory.run()

    assert [base for _worktree, base in git.diff_since] == ["m" * 40]


def test_review_fix_on_a_branch_that_conflicts_with_main_goes_stuck_without_the_agent(tmp_path):
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC, merge_conflict=True)
    github = FakeGitHub(review_fixes=[make_review_fix()])
    runner = FakeRunner()
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path,
        git=git,
        github=github,
        runner=runner,
        notifier=notifier,
    )

    results = factory.run()

    assert len(results) == 1 and not results[0].ok
    assert runner.calls == []
    assert git.committed == []
    assert git.pushed == []
    assert notifier.stuck[0].failing_check == (
        "branch conflicts with main; a human must merge main"
    )
    assert github.issue_labels == [(7, "needs-decision", "TOKEN")]


ORPHAN_CHECK = "remote branch nf/7-ticket-7 has no open PR"


def test_pr_creation_failure_after_push_goes_stuck_and_names_the_orphan_branch(tmp_path):
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    github = FakeGitHub(
        tickets=[make_ticket(7, labels={"ready-for-agent"})],
        pr_error=GitHubError("gh pr create failed: HTTP 422"),
    )
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=RecordingNotifier()
    )

    results = factory.run()

    assert len(results) == 1 and not results[0].ok
    assert git.pushed == [("nf/7-ticket-7", "TOKEN")]
    assert github.ready_prs == []
    assert github.issue_labels[0][1] == "needs-decision"
    assert ORPHAN_CHECK in github.comments[0][1]
    assert "delete it by hand" in github.comments[0][1]


def test_remote_branch_without_a_pr_goes_stuck_before_any_worktree_is_created(tmp_path):
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC, remote_branches={"nf/7-ticket-7"})
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=RecordingNotifier()
    )

    results = factory.run()

    assert len(results) == 1 and not results[0].ok
    assert git.remote_checks == [("nf/7-ticket-7", "TOKEN")]
    assert github.open_pr_checks == [("nf/7-ticket-7", "TOKEN")]
    assert not [w for w in git.worktrees if w[0] == "nf/7-ticket-7"]
    assert git.pushed == []
    assert github.created_prs == []
    assert ORPHAN_CHECK in github.comments[0][1]


def test_orphan_branch_stuck_before_worktree_has_no_handoff_to_a_missing_worktree(tmp_path):
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC, remote_branches={"nf/7-ticket-7"})
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=notifier
    )

    factory.run()

    assert len(notifier.stuck) == 1
    assert notifier.stuck[0].worktree is None
    assert notifier.stuck[0].handoff_command is None


def test_nothing_to_commit_goes_stuck_without_push_or_pr(tmp_path):
    # No agent commit and no diff against origin/main: the fake returns an empty diff.
    git = FakeGit(
        check_passed=True, decisions=DECISIONS_DOC, commit_changed=False, diff=DiffStats()
    )
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=RecordingNotifier()
    )

    results = factory.run()

    assert len(results) == 1 and not results[0].ok
    assert git.pushed == []
    assert github.created_prs == []
    assert "no changes made for the ticket" in github.comments[0][1]


def test_empty_diff_against_main_goes_stuck_without_push_or_pr(tmp_path):
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC, diff=DiffStats())
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=RecordingNotifier()
    )

    results = factory.run()

    assert len(results) == 1 and not results[0].ok
    assert git.pushed == []
    assert github.created_prs == []
    assert "no changes made for the ticket" in github.comments[0][1]


def test_log_gets_one_header_per_step_and_a_new_run_starts_a_fresh_file(tmp_path):
    settings = make_settings(tmp_path)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    (settings.logs_dir / "7.log").write_text("OUTPUT OF AN OLDER RUN\n")
    git = FakeGit(check_passed=False, decisions="- Tried X.")
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    factory = build_factory(
        tmp_path,
        git=git,
        github=github,
        runner=FakeRunner(),
        notifier=RecordingNotifier(),
        settings=settings,
    )

    factory.run()

    log = (settings.logs_dir / "7.log").read_text()
    assert "OUTPUT OF AN OLDER RUN" not in log
    for step in range(1, settings.attempts + 1):
        assert f"=== step {step} (model deepseek/deepseek-flash) ===" in log
    assert log.count("=== step ") == settings.attempts


def test_agent_committed_on_its_own_still_opens_the_pr(tmp_path):
    # The agent ran `git commit` itself: commit_all has nothing left to commit
    # (False), but the diff against origin/main carries its changes.
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC, commit_changed=False)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=RecordingNotifier()
    )

    results = factory.run()

    assert len(results) == 1 and results[0].ok
    assert git.pushed != []
    assert len(github.created_prs) == 1
    assert "no changes made for the ticket" not in str(github.comments)


# --- pre-PR reviewer (#141) -------------------------------------------------

NO_FINDINGS = AgentResult(
    exit_code=0,
    stdout="REVIEW-FINDINGS-BEGIN\nNO FINDINGS\nREVIEW-FINDINGS-END\n",
    stderr="",
    timed_out=False,
)
IMPORTANT = AgentResult(
    exit_code=0,
    stdout=(
        "REVIEW-FINDINGS-BEGIN\n"
        "[Important] backend/apps/x/use_case.py:12 | link and save are not atomic | "
        "save raises -> partial state\n"
        "[Nit] backend/apps/x/views.py:3 | duplicated helper | none\n"
        "REVIEW-FINDINGS-END\n"
    ),
    stderr="",
    timed_out=False,
)
BUILDER_OK = AgentResult(exit_code=0, stdout="built", stderr="", timed_out=False)


class ScriptedRunner:
    def ensure_clean(self):
        pass

    def verify_home_is_clean(self):
        pass

    def smoke_check(self, worktree):
        pass

    """Builder calls always succeed; reviewer calls (with a config path) follow a script."""

    def __init__(self, reviews):
        self.reviews = list(reviews)
        self.builder_prompts = []
        self.review_calls = []

    def run(
        self,
        *,
        worktree,
        model,
        prompt,
        timeout_seconds,
        config_path=None,
        config_content=None,
        disable_project_config=False,
    ):
        if not disable_project_config:
            self.builder_prompts.append(prompt)
            return BUILDER_OK
        self.review_calls.append(
            {"model": model, "prompt": prompt, "config_content": config_content}
        )
        return self.reviews.pop(0)


def review_settings(tmp_path, **overrides):
    from dataclasses import replace

    return replace(make_settings(tmp_path), **{"pre_pr_review": True, **overrides})


def run_with_reviewer(
    tmp_path, reviews, *, labels=("ready-for-agent",), git=None, setup_github=None, **settings
):
    git = git or FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    github = FakeGitHub(tickets=[make_ticket(7, labels=set(labels))], pr_number=101)
    if setup_github is not None:
        setup_github(github)
    runner = ScriptedRunner(reviews)
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path,
        git=git,
        github=github,
        runner=runner,
        notifier=notifier,
        settings=review_settings(tmp_path, **settings),
    )
    results = factory.run()
    return results, git, github, runner, notifier


def test_reviewer_runs_with_the_strong_model_and_rules_from_origin_main(tmp_path):
    results, git, github, runner, _ = run_with_reviewer(tmp_path, [NO_FINDINGS])

    assert results[0].ok
    assert len(runner.review_calls) == 1
    call = runner.review_calls[0]
    assert call["model"] == "deepseek/deepseek-v4-pro"
    assert (
        json.loads(call["config_content"])["permission"]
        == (json.loads(git.reviewer_config)["permission"])
    )
    assert (str(tmp_path / "repo"), "origin/main", "tools/factory/opencode.reviewer.json") in (
        git.ref_reads
    )
    assert "### 1. Multi-step writes commit together" in call["prompt"]
    assert (str(tmp_path / "repo"), "origin/main", "REVIEW.md") in git.ref_reads
    body = github.created_prs[0][2]
    assert "## Review" in body
    assert "No blocking findings" in body


def test_important_finding_goes_back_to_the_builder_then_the_pr_opens(tmp_path):
    results, _, github, runner, _ = run_with_reviewer(tmp_path, [IMPORTANT, NO_FINDINGS])

    assert results[0].ok
    assert len(runner.builder_prompts) == 2
    assert "link and save are not atomic" in runner.builder_prompts[1]
    assert "untrusted" in runner.builder_prompts[1]
    assert "Findings from your previous round" in runner.review_calls[1]["prompt"]
    assert len(github.created_prs) == 1


def test_important_finding_until_the_budget_ends_goes_stuck_naming_it(tmp_path):
    results, git, github, runner, notifier = run_with_reviewer(
        tmp_path, [IMPORTANT, IMPORTANT], attempts=2
    )

    assert not results[0].ok
    assert github.created_prs == []
    assert git.pushed == []
    assert notifier.stuck[0].failing_check == (
        "review: backend/apps/x/use_case.py:12 link and save are not atomic"
    )


def test_nits_are_listed_in_the_pr_body_and_never_block(tmp_path):
    nits_only = AgentResult(
        exit_code=0,
        stdout=(
            "REVIEW-FINDINGS-BEGIN\n"
            "[Nit] backend/apps/x/views.py:3 | duplicated helper | none\n"
            "[Pre-existing] backend/apps/y.py | old bug | x -> y\n"
            "REVIEW-FINDINGS-END\n"
        ),
        stderr="",
        timed_out=False,
    )

    results, _, github, runner, _ = run_with_reviewer(tmp_path, [nits_only])

    assert results[0].ok
    assert len(runner.builder_prompts) == 1
    body = github.created_prs[0][2]
    assert "[Nit] `backend/apps/x/views.py:3` duplicated helper" in body
    assert "[Pre-existing] `backend/apps/y.py` old bug" in body


SUGGESTED = AgentResult(
    exit_code=0,
    stdout=(
        "REVIEW-FINDINGS-BEGIN\n"
        "[Suggested ticket] backend/apps/x/views.py:9 | paginate the list @daedraMex | "
        "a big store loads every row; fixes #12\n"
        "[Suggested ticket] a.py | two | b\n"
        "[Suggested ticket] a.py | three | b\n"
        "[Suggested ticket] a.py | four | b\n"
        "REVIEW-FINDINGS-END\n"
    ),
    stderr="",
    timed_out=False,
)


def test_suggested_tickets_never_block_and_open_at_most_three_untriaged_issues(tmp_path):
    results, _, github, runner, _ = run_with_reviewer(tmp_path, [SUGGESTED])

    assert results[0].ok
    assert len(runner.builder_prompts) == 1
    assert len(github.created_issues) == 3
    title, body, _token = github.created_issues[0]
    assert title == "Suggested by review: paginate the list @\u200bdaedraMex"
    assert "PR #101 (ticket #7)" in body
    assert "untrusted model output" in body
    assert "@daedraMex" not in body
    assert "fixes #12" not in body
    assert "[Suggested ticket] `backend/apps/x/views.py:9`" in github.created_prs[0][2]


def test_a_failed_suggested_ticket_keeps_the_run_a_success(tmp_path, capsys):
    def failing(github):
        github.issue_error = GitHubError("HTTP 403")

    results, _, github, _, _ = run_with_reviewer(tmp_path, [SUGGESTED], setup_github=failing)

    assert results[0].ok
    assert github.created_issues == []
    assert "suggested ticket not opened" in capsys.readouterr().err


ATTACKED = AgentResult(
    exit_code=0,
    stdout=(
        "REVIEW-FINDINGS-BEGIN\n"
        "[Important] backend/apps/x/use_case.py:12 | link and save are not atomic | "
        "save raises -> partial state\n"
        "REVIEW-FINDINGS-END\n"
        "REVIEW-TEST-BEGIN\n"
        "```python\n"
        "def test_attack_rollback():\n"
        "    assert False\n"
        "```\n"
        "REVIEW-TEST-END\n"
    ),
    stderr="",
    timed_out=False,
)


def test_a_failing_attack_test_sends_the_builder_back_with_the_test(tmp_path):
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    git.attack_results = [("broke", "FAILED test_attack_rollback - assert False"), ("held", "")]

    results, _, github, runner, _ = run_with_reviewer(
        tmp_path, [ATTACKED, NO_FINDINGS], git=git, review_tests=True
    )

    assert results[0].ok
    assert git.placed_tests[0] == {
        "tests/review/test_review_7_1.py": "def test_attack_rollback():\n    assert False\n"
    }
    assert git.removed_tests[0] == ("tests/review/test_review_7_1.py",)
    assert len(runner.builder_prompts) == 2
    assert "FAILED test_attack_rollback" in runner.builder_prompts[1]
    assert "def test_attack_rollback" in runner.builder_prompts[1]


def test_an_important_finding_no_attack_proves_is_unproven_and_does_not_block(tmp_path):
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    git.attack_results = [("held", "1 passed")]

    results, _, github, runner, _ = run_with_reviewer(
        tmp_path, [ATTACKED], git=git, review_tests=True
    )

    assert results[0].ok
    assert len(runner.builder_prompts) == 1
    body = github.created_prs[0][2]
    assert "Attack tests: 1 written by the reviewer, all held." in body
    assert "Unproven (attack tests held; read it)" in body
    assert "link and save are not atomic" in body


def test_attack_tests_that_cannot_run_fall_back_to_the_findings(tmp_path):
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    git.attack_results = [("error", "ImportError"), ("error", "ImportError")]

    results, _, _, runner, _ = run_with_reviewer(
        tmp_path, [ATTACKED, NO_FINDINGS], git=git, review_tests=True
    )

    assert results[0].ok
    assert len(runner.builder_prompts) == 2


def test_attack_tests_that_leave_changes_behind_make_the_ticket_stuck(tmp_path):
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    git.fingerprints = ["same", "same", "changed"]

    results, _, github, _, _ = run_with_reviewer(tmp_path, [ATTACKED], git=git, review_tests=True)

    assert results[0].ok is False
    assert github.created_prs == []
    assert "attack tests left changes in the worktree" in github.comments[0][1]


def test_attack_tests_stay_off_by_default_and_for_console_only_changes(tmp_path):
    off = FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    run_with_reviewer(tmp_path / "off", [ATTACKED, NO_FINDINGS], git=off)
    console = FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    console.review_files = ["web/console/src/app/page.tsx"]
    run_with_reviewer(tmp_path / "console", [ATTACKED, NO_FINDINGS], git=console, review_tests=True)

    assert off.attack_runs == []
    assert console.attack_runs == []


def test_strong_model_ticket_skips_the_reviewer(tmp_path):
    results, _, github, runner, _ = run_with_reviewer(
        tmp_path, [], labels=("ready-for-agent", "strong-model")
    )

    assert results[0].ok
    assert runner.review_calls == []
    assert "automated review skipped (strong-model ticket)" in github.created_prs[0][2]


def test_an_unreadable_review_still_opens_the_pr_and_says_so(tmp_path):
    garbage = AgentResult(exit_code=0, stdout="LGTM", stderr="", timed_out=False)

    results, _, github, _, _ = run_with_reviewer(tmp_path, [garbage])

    assert results[0].ok
    assert "automated review failed" in github.created_prs[0][2]
    assert "read in full" in github.created_prs[0][2]


def test_a_reviewer_that_changes_the_worktree_sends_the_ticket_to_stuck(tmp_path):
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    git.fingerprints = ["before", "after"]

    results, git, github, _, notifier = run_with_reviewer(tmp_path, [NO_FINDINGS], git=git)

    assert not results[0].ok
    assert git.pushed == []
    assert notifier.stuck[0].failing_check == "reviewer modified the worktree"


def test_reviewer_off_keeps_the_old_flow(tmp_path):
    results, _, github, runner, _ = run_with_reviewer(tmp_path, [], pre_pr_review=False)

    assert results[0].ok
    assert runner.review_calls == []
    assert "automated review off" in github.created_prs[0][2]


def test_protected_paths_go_stuck_before_the_reviewer_runs(tmp_path):
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    git.review_files = ["backend/apps/x.py", "opencode.jsonc"]

    results, git, github, runner, notifier = run_with_reviewer(tmp_path, [], git=git)

    assert not results[0].ok
    assert runner.review_calls == []
    assert notifier.stuck[0].failing_check == "protected path changed"


def test_review_feedback_survives_a_failed_check_and_names_the_open_finding(tmp_path):
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    git.check_script = [True, False, False]

    results, git, github, runner, notifier = run_with_reviewer(
        tmp_path, [IMPORTANT], git=git, attempts=3
    )

    assert not results[0].ok
    assert "link and save are not atomic" in runner.builder_prompts[2]
    assert notifier.stuck[0].failing_check == (
        "check failed; review: backend/apps/x/use_case.py:12 link and save are not atomic"
    )


def test_an_open_finding_is_listed_when_the_next_review_fails(tmp_path):
    garbage = AgentResult(exit_code=0, stdout="LGTM", stderr="", timed_out=False)

    results, _, github, _, _ = run_with_reviewer(tmp_path, [IMPORTANT, garbage])

    body = github.created_prs[0][2]
    assert "automated review failed" in body
    assert "Open finding from an earlier round" in body
    assert "link and save are not atomic" in body


def test_builder_gets_main_s_factory_config_inline_and_keeps_project_config(tmp_path):
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    runner = FakeRunner()
    factory = build_factory(
        tmp_path, git=git, github=github, runner=runner, notifier=RecordingNotifier()
    )

    factory.run()

    builder = runner.calls[0]
    config = json.loads(builder["config_content"])
    expected = json.loads(git.builder_config)["permission"]
    assert config["permission"] == expected
    assert config["agent"]["build"]["permission"] == expected
    assert config["default_agent"] == "build"
    assert builder["disable_project_config"] is False
    assert (str(tmp_path / "repo"), "origin/main", "tools/factory/opencode.factory.json") in (
        git.ref_reads
    )


def test_review_fix_builder_also_gets_main_s_factory_config_inline(tmp_path):
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    github = FakeGitHub(review_fixes=[make_review_fix()])
    runner = FakeRunner()
    factory = build_factory(
        tmp_path, git=git, github=github, runner=runner, notifier=RecordingNotifier()
    )

    factory.run()

    assert (
        json.loads(runner.calls[0]["config_content"])["permission"]
        == (json.loads(git.builder_config)["permission"])
    )


def test_reviewer_still_disables_project_config(tmp_path):
    results, _, _, runner, _ = run_with_reviewer(tmp_path, [NO_FINDINGS])

    assert results[0].ok
    assert len(runner.review_calls) == 1


def test_a_blank_builder_config_on_main_fails_the_run_closed(tmp_path):
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    git.builder_config = "   "
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    runner = FakeRunner()
    factory = build_factory(
        tmp_path, git=git, github=github, runner=runner, notifier=RecordingNotifier()
    )

    with pytest.raises(RunFailed, match="opencode.factory.json"):
        factory.run()
    assert runner.calls == []


def test_a_dependency_change_without_the_label_goes_stuck(tmp_path):
    git = FakeGit(
        check_passed=True,
        decisions=DECISIONS_DOC,
        diff=DiffStats(files=(FileChange("backend/uv.lock", 3, 1),)),
    )
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=notifier
    )

    factory.run()

    assert git.pushed == []
    assert notifier.stuck[0].failing_check == "protected path changed"


def test_a_deps_change_ticket_publishes_and_labels_the_pr(tmp_path):
    git = FakeGit(
        check_passed=True,
        decisions=DECISIONS_DOC,
        diff=DiffStats(files=(FileChange("backend/uv.lock", 3, 1),)),
    )
    github = FakeGitHub(
        tickets=[make_ticket(7, labels={"ready-for-agent", "deps-change"})], pr_number=101
    )
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=RecordingNotifier()
    )

    results = factory.run()

    assert results[0].ok
    assert (101, "deps-change") in [(n, label) for n, label, _ in github.pr_labels]


def test_a_review_fix_never_pushes_a_branch_that_is_not_the_ticket_s(tmp_path):
    git = FakeGit(check_passed=True, decisions=DECISIONS_DOC)
    fix = make_review_fix()
    github = FakeGitHub(review_fixes=[replace(fix, branch="main")])
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=RecordingNotifier()
    )

    with pytest.raises(RunFailed, match="push target"):
        factory.run()
    assert git.pushed == []


def test_a_deps_change_ticket_that_rewrites_package_scripts_goes_stuck(tmp_path):
    git = FakeGit(
        check_passed=True,
        decisions=DECISIONS_DOC,
        diff=DiffStats(files=(FileChange("web/console/package.json", 1, 1),)),
    )
    git.dependency_old["web/console/package.json"] = '{"scripts": {"lint": "eslint ."}}'
    git.dependency_new["web/console/package.json"] = '{"scripts": {"lint": "true"}}'
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent", "deps-change"})])
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=notifier
    )

    factory.run()

    assert git.pushed == []
    assert notifier.stuck[0].failing_check.startswith(
        "dependency file changed beyond dependencies: web/console/package.json"
    )


def test_a_review_fix_that_changes_dependencies_labels_the_pr(tmp_path):
    git = FakeGit(
        check_passed=True,
        decisions=DECISIONS_DOC,
        diff=DiffStats(files=(FileChange("backend/uv.lock", 3, 1),)),
    )
    fix = make_review_fix()
    labelled = replace(fix, ticket=replace(fix.ticket, labels=frozenset({"deps-change"})))
    github = FakeGitHub(review_fixes=[labelled])
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=RecordingNotifier()
    )

    results = factory.run()

    assert results[0].ok
    assert (fix.pr_number, "deps-change") in [(n, label) for n, label, _ in github.pr_labels]


def test_a_stuck_ticket_whose_label_fails_is_held_out_of_the_next_run(tmp_path):
    git = FakeGit(check_passed=False)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})], issue_label_errors=2)
    notifier = RecordingNotifier()
    runner = FakeRunner()
    factory = build_factory(tmp_path, git=git, github=github, runner=runner, notifier=notifier)

    first = factory.run()

    assert not first[0].ok
    assert "needs-decision" in notifier.stuck[0].label_error
    assert "not found" in notifier.stuck[0].label_error
    assert LabelHolds(make_settings(tmp_path).state_dir).numbers() == {7}
    agent_runs = len(runner.calls)

    # The listing still shows #7 as ready, because the label never landed.
    second = factory.run()

    assert second == []
    assert len(runner.calls) == agent_runs
    assert github.issue_labels == []


def test_a_held_ticket_is_released_once_its_label_lands(tmp_path):
    git = FakeGit(check_passed=False)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})], issue_label_errors=1)
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=RecordingNotifier()
    )
    factory.run()

    # Next run: the retry adds the label, so the hold goes and the ticket is not run.
    results = factory.run()

    assert results == []
    assert github.issue_labels == [(7, "needs-decision", "TOKEN")]
    assert LabelHolds(make_settings(tmp_path).state_dir).numbers() == frozenset()


def test_the_hold_is_written_before_any_github_call_of_the_stuck_flow(tmp_path):
    git = FakeGit(check_passed=False)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    holds = LabelHolds(make_settings(tmp_path).state_dir)
    seen = []

    def comment(number, body, token):
        seen.append(holds.numbers())
        raise RuntimeError("gh api: HTTP 502")

    github.comment = comment
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=RecordingNotifier()
    )

    with pytest.raises(RunFailed):
        factory.run()

    assert seen == [{7}]
    assert holds.numbers() == {7}


def test_a_stuck_ticket_whose_label_lands_is_not_held(tmp_path):
    git = FakeGit(check_passed=False)
    github = FakeGitHub(tickets=[make_ticket(7, labels={"ready-for-agent"})])
    notifier = RecordingNotifier()
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=notifier
    )

    factory.run()

    assert notifier.stuck[0].label_error is None
    assert LabelHolds(make_settings(tmp_path).state_dir).numbers() == frozenset()


def test_a_failed_pr_label_leaves_the_pr_a_draft_without_auto_merge(tmp_path):
    diff = DiffStats(
        files=(FileChange(path="backend/apps/orders/migrations/0002_x.py", added=1, deleted=0),),
        migrations_changed=True,
    )
    git = FakeGit(check_passed=True, diff=diff)
    github = FakeGitHub(
        tickets=[make_ticket(7, labels={"ready-for-agent"})],
        pr_label_error=GitHubError("could not add label migration to pr #101: not found"),
    )
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=RecordingNotifier()
    )

    with pytest.raises(RunFailed, match="migration"):
        factory.run()

    assert github.created_prs != []
    assert github.ready_prs == []
    assert github.auto_merges == []


def test_a_review_fix_whose_pr_label_fails_pushes_nothing(tmp_path):
    git = FakeGit(
        check_passed=True,
        decisions=DECISIONS_DOC,
        diff=DiffStats(files=(FileChange("backend/uv.lock", 3, 1),)),
    )
    fix = make_review_fix()
    labelled = replace(fix, ticket=replace(fix.ticket, labels=frozenset({"deps-change"})))
    github = FakeGitHub(
        review_fixes=[labelled],
        pr_label_error=GitHubError("could not add label deps-change to pr #101: not found"),
    )
    factory = build_factory(
        tmp_path, git=git, github=github, runner=FakeRunner(), notifier=RecordingNotifier()
    )

    with pytest.raises(RunFailed, match="deps-change"):
        factory.run()

    assert git.pushed == []
    assert github.comments == []


def test_a_ticket_held_by_a_contract_is_skipped_and_logged_once(tmp_path, capsys):
    held = replace(
        make_ticket(7, labels={"ready-for-agent"}),
        contract_conflicts=("photos.submission-states held by PR #175 (#156)",),
    )
    runner = FakeRunner()
    factory = build_factory(
        tmp_path,
        git=FakeGit(check_passed=True),
        github=FakeGitHub(tickets=[held]),
        runner=runner,
        notifier=RecordingNotifier(),
    )

    results = factory.run()

    assert results == []
    assert runner.calls == []
    err = capsys.readouterr().err
    assert err.count("#7 skipped") == 1
    assert "photos.submission-states held by PR #175 (#156)" in err


def test_a_contract_skip_is_not_logged_when_the_ticket_is_not_ready_anyway(tmp_path, capsys):
    blocked = replace(
        make_ticket(7, labels={"ready-for-agent", "needs-decision"}),
        contract_conflicts=("photos.submission-states held by PR #175 (#156)",),
    )
    factory = build_factory(
        tmp_path,
        git=FakeGit(check_passed=True),
        github=FakeGitHub(tickets=[blocked]),
        runner=FakeRunner(),
        notifier=RecordingNotifier(),
    )

    factory.run()

    assert "skipped" not in capsys.readouterr().err
