from pathlib import Path

import pytest

from factory.config import Settings
from factory.preflight import MAX_ERROR_CHARS, Preflight, PreflightError
from factory.tickets import Ticket


class FakeGit:
    def __init__(
        self,
        *,
        check_passed=True,
        check_output="check output",
        fetch_error=None,
        identity_error=None,
        events=None,
    ):
        self.check_passed = check_passed
        self.check_output = check_output
        self.fetch_error = fetch_error
        self.identity_error = identity_error
        self.calls = events if events is not None else []

    def fetch_main(self, repo_dir):
        self.calls.append(("fetch_main", repo_dir))
        if self.fetch_error is not None:
            raise self.fetch_error

    def verify_commit_identity(self, repo_dir):
        self.calls.append(("verify_commit_identity", repo_dir))
        if self.identity_error is not None:
            raise self.identity_error

    def create_worktree(self, repo_dir, worktree, branch):
        self.calls.append(("create_worktree", worktree, branch))
        return worktree

    def check(self, worktree):
        self.calls.append(("check", worktree))
        return (self.check_passed, self.check_output)

    def remove_worktree(self, repo_dir, worktree):
        self.calls.append(("remove_worktree", worktree))

    def delete_branch(self, repo_dir, branch):
        self.calls.append(("delete_branch", branch))


class FakeGitHub:
    def __init__(self, tickets=None):
        self.tickets = tickets or []
        self.listed_with = None

    def list_tickets(self, token=None):
        self.listed_with = token
        return list(self.tickets)


class FakeTokenProvider:
    def mint(self, repo):
        return "MINTED-TOKEN"


class RecordingNotifier:
    def __init__(self):
        self.run_failed = []

    def send_pr_ready(self, info):
        return None

    def send_stuck(self, info):
        return None

    def send_run_failed(self, info):
        self.run_failed.append(info)


def make_settings(tmp_path):
    return Settings(
        factory_model="m",
        factory_strong_model="s",
        repo="daedraMex/commerce-platform",
        max_tickets=1,
        attempts=5,
        repo_dir=tmp_path / "repo",
        worktrees_dir=tmp_path / "worktrees",
        logs_dir=tmp_path / "logs",
        time_limit_seconds=60,
        keep_days=14,
        telegram_bot_token="tg-secret",
        telegram_chat_id="chat",
        github_app_id="1",
        github_private_key="-----BEGIN PRIVATE KEY-----",
        github_installation_id="2",
        agent_user="factory-agent",
        secrets_file=tmp_path / "secrets.env",
        deploy_key=tmp_path / ".ssh" / "commerce_deploy",
    )


def build_preflight(tmp_path, *, git=None, github=None, notifier=None, verified=None, events=None):
    settings = make_settings(tmp_path)
    events = events if events is not None else []
    verified = verified if verified is not None else events

    def verify_isolation(**kwargs):
        verified.append(("verify_isolation", kwargs))

    def verify_git_version():
        verified.append(("verify_git_version",))

    def verify_sudoers_logging():
        verified.append(("verify_sudoers_logging",))

    return Preflight(
        settings,
        git=git or FakeGit(events=events),
        github=github or FakeGitHub(),
        notifier=notifier or RecordingNotifier(),
        token_provider=FakeTokenProvider(),
        clock=lambda: 42,
        verify_isolation_fn=verify_isolation,
        verify_git_version_fn=verify_git_version,
        verify_sudoers_logging_fn=verify_sudoers_logging,
    )


def test_preflight_runs_real_steps_in_order_and_returns_tickets(tmp_path):
    tickets = [Ticket(number=7, title="Ready", labels=frozenset({"ready-for-agent"}))]
    events = []
    git = FakeGit(events=events)
    github = FakeGitHub(tickets)

    result = build_preflight(tmp_path, git=git, github=github, events=events).run()

    assert result == tickets
    assert github.listed_with == "MINTED-TOKEN"
    assert [event[0] for event in events] == [
        "fetch_main",
        "verify_isolation",
        "verify_git_version",
        "verify_commit_identity",
        "verify_sudoers_logging",
        "create_worktree",
        "check",
        "remove_worktree",
        "delete_branch",
    ]
    assert events[5] == (
        "create_worktree",
        Path(tmp_path / "worktrees" / "preflight-42"),
        "preflight-42",
    )
    assert events[3] == ("verify_commit_identity", tmp_path / "repo")
    assert events[1][1]["repo_dir"] == tmp_path / "repo"


def test_preflight_failure_notifies_cleans_up_and_stops(tmp_path):
    git = FakeGit(check_passed=False)
    notifier = RecordingNotifier()

    with pytest.raises(PreflightError, match="check.sh") as caught:
        build_preflight(tmp_path, git=git, notifier=notifier).run()

    assert caught.value.step == "check.sh"
    assert len(notifier.run_failed) == 1
    assert notifier.run_failed[0].reason.startswith(
        "preflight failed: check.sh: check.sh failed; see "
    )
    assert str(tmp_path / "logs" / "preflight-42.log") in notifier.run_failed[0].reason
    assert [call[0] for call in git.calls][-2:] == ["remove_worktree", "delete_branch"]


def test_preflight_check_failure_writes_the_log_but_not_the_output_to_telegram(tmp_path):
    git = FakeGit(check_passed=False, check_output="FAILED CHECK OUTPUT")
    notifier = RecordingNotifier()

    with pytest.raises(PreflightError, match="check.sh"):
        build_preflight(tmp_path, git=git, notifier=notifier).run()

    log_path = tmp_path / "logs" / "preflight-42.log"
    assert log_path.read_text() == "FAILED CHECK OUTPUT"
    reason = notifier.run_failed[0].reason
    assert str(log_path) in reason
    assert "FAILED CHECK OUTPUT" not in reason


def test_preflight_fetch_failure_creates_no_worktree_and_notifies(tmp_path):
    git = FakeGit(fetch_error=RuntimeError("could not read from remote"))
    notifier = RecordingNotifier()

    with pytest.raises(PreflightError, match="fetch origin/main"):
        build_preflight(tmp_path, git=git, notifier=notifier).run()

    assert [call[0] for call in git.calls] == ["fetch_main"]
    assert "preflight failed: fetch origin/main: could not read from remote" in (
        notifier.run_failed[0].reason
    )


def test_preflight_shortens_errors_and_never_includes_settings_secrets(tmp_path):
    git = FakeGit(fetch_error=RuntimeError("boom " * 500))
    notifier = RecordingNotifier()
    settings = make_settings(tmp_path)

    with pytest.raises(PreflightError):
        build_preflight(tmp_path, git=git, notifier=notifier).run()

    reason = notifier.run_failed[0].reason
    assert len(reason) <= len("preflight failed: fetch origin/main: ") + MAX_ERROR_CHARS
    assert reason.endswith("…")
    assert settings.telegram_bot_token not in reason
    assert settings.github_private_key not in reason


def test_preflight_stops_before_creating_a_worktree_when_isolation_fails(tmp_path):
    git = FakeGit()

    def failing_isolation(**_kwargs):
        raise RuntimeError("agent user can read the key")

    preflight = Preflight(
        make_settings(tmp_path),
        git=git,
        github=FakeGitHub(),
        notifier=RecordingNotifier(),
        token_provider=FakeTokenProvider(),
        clock=lambda: 42,
        verify_isolation_fn=failing_isolation,
        verify_git_version_fn=lambda: None,
        verify_sudoers_logging_fn=lambda: None,
    )

    with pytest.raises(PreflightError, match="verify isolation"):
        preflight.run()

    assert [call[0] for call in git.calls] == ["fetch_main"]


def test_preflight_stops_before_creating_a_worktree_when_sudoers_would_log(tmp_path):
    git = FakeGit()

    def failing_sudoers():
        raise RuntimeError("missing Defaults:factory !log_allowed")

    preflight = Preflight(
        make_settings(tmp_path),
        git=git,
        github=FakeGitHub(),
        notifier=RecordingNotifier(),
        token_provider=FakeTokenProvider(),
        clock=lambda: 42,
        verify_isolation_fn=lambda **_kwargs: None,
        verify_git_version_fn=lambda: None,
        verify_sudoers_logging_fn=failing_sudoers,
    )

    with pytest.raises(PreflightError, match="verify sudoers logging"):
        preflight.run()

    assert [call[0] for call in git.calls] == ["fetch_main", "verify_commit_identity"]


def test_preflight_stops_before_creating_a_worktree_when_identity_is_missing(tmp_path):
    git = FakeGit(identity_error=RuntimeError("XOLO_BOT_USER_ID is not set"))
    notifier = RecordingNotifier()

    with pytest.raises(PreflightError, match="verify commit identity"):
        build_preflight(tmp_path, git=git, notifier=notifier).run()

    assert [call[0] for call in git.calls] == ["fetch_main", "verify_commit_identity"]
    assert "XOLO_BOT_USER_ID is not set" in notifier.run_failed[0].reason
