import json
from dataclasses import replace
from pathlib import Path

import pytest

from factory.areas import AREAS
from factory.config import Settings
from factory.git import CheckResult
from factory.github import GitHubError
from factory.preflight import MAX_ERROR_CHARS, Preflight, PreflightError
from factory.tickets import REQUIRED_LABELS, Ticket

REVIEWER_CONFIG = '{"permission": {"edit": {"*": "deny"}}}'


class FakeGit:
    def __init__(
        self,
        *,
        check_passed=True,
        check_output="check output",
        fetch_error=None,
        identity_error=None,
        remove_error=None,
        leaked_error=None,
        check_error=None,
        leftovers=(),
        events=None,
    ):
        self.check_passed = check_passed
        self.check_output = check_output
        self.fetch_error = fetch_error
        self.identity_error = identity_error
        self.remove_error = remove_error
        self.leaked_error = leaked_error
        self.check_error = check_error
        self.leftovers = list(leftovers)
        self.calls = events if events is not None else []

    def fetch_main(self, repo_dir):
        self.calls.append(("fetch_main", repo_dir))
        if self.fetch_error is not None:
            raise self.fetch_error

    def verify_commit_identity(self, repo_dir):
        self.calls.append(("verify_commit_identity", repo_dir))
        if self.identity_error is not None:
            raise self.identity_error

    reviewer_config = REVIEWER_CONFIG

    def read_file(self, worktree, relpath):
        if relpath == "tools/factory/opencode.reviewer.json":
            return self.reviewer_config
        return ""

    def preflight_leftovers(self, worktrees_dir):
        return list(self.leftovers)

    def verify_no_leaked_worktrees(self, repo_dir, worktrees_dir):
        self.calls.append(("verify_no_leaked_worktrees", worktrees_dir))
        if self.leaked_error is not None:
            raise self.leaked_error

    def create_worktree(self, repo_dir, worktree, branch):
        self.calls.append(("create_worktree", worktree, branch))
        return worktree

    def check(self, worktree, *, areas=None):
        self.calls.append(("check", worktree, areas))
        if self.check_error is not None:
            raise self.check_error
        return CheckResult(self.check_passed, self.check_output)

    def create_agent_cleanup_probe(self, worktree):
        self.calls.append(("create_agent_cleanup_probe", worktree))
        return worktree / "backend" / ".cleanup-probe"

    def remove_worktree(self, repo_dir, worktree, worktrees_dir):
        self.calls.append(("remove_worktree", worktree))
        if self.remove_error is not None:
            raise self.remove_error

    def branch_exists(self, repo_dir, branch):
        return True

    def delete_branch(self, repo_dir, branch):
        self.calls.append(("delete_branch", branch))


class FakeGitHub:
    def __init__(self, tickets=None, labels=None, label_error=None):
        self.tickets = tickets or []
        self.listed_with = None
        self.labels = REQUIRED_LABELS if labels is None else frozenset(labels)
        self.label_error = label_error

    def list_label_names(self, token=None):
        if self.label_error is not None:
            raise self.label_error
        return self.labels

    def list_tickets(self, token=None):
        self.listed_with = token
        return list(self.tickets)


class FakeTokenProvider:
    def mint(self, repo):
        return "MINTED-TOKEN"


class RecordingNotifier:
    def __init__(self):
        self.run_failed = []
        self.cleaned_up = []

    def send_cleaned_up(self, info):
        self.cleaned_up.append(info)

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
        state_dir=tmp_path / "state",
        pre_pr_review=True,
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
        "verify_no_leaked_worktrees",
        "create_worktree",
        "check",
        "create_agent_cleanup_probe",
        "remove_worktree",
        "delete_branch",
    ]
    assert events[6] == (
        "create_worktree",
        Path(tmp_path / "worktrees" / "preflight-42"),
        "preflight-42",
    )
    assert events[3] == ("verify_commit_identity", tmp_path / "repo")
    assert events[1][1]["repo_dir"] == tmp_path / "repo"


def test_preflight_runs_every_present_area_on_fresh_main(tmp_path):
    events = []

    build_preflight(tmp_path, git=FakeGit(events=events), events=events).run()

    check = next(event for event in events if event[0] == "check")
    assert check[2] == AREAS


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


def test_preflight_fails_loudly_when_worktree_cleanup_fails(tmp_path):
    git = FakeGit(remove_error=RuntimeError("rm: permission denied"))
    notifier = RecordingNotifier()

    with pytest.raises(PreflightError, match="verify worktree cleanup"):
        build_preflight(tmp_path, git=git, notifier=notifier).run()

    assert "rm: permission denied" in notifier.run_failed[0].reason
    assert [call[0] for call in git.calls][-2:] == [
        "create_agent_cleanup_probe",
        "remove_worktree",
    ]


def test_a_failed_cleanup_never_hides_the_step_that_failed(tmp_path):
    """On 2026-11-19 the cleanup error replaced the real one in Telegram (#194)."""
    git = FakeGit(
        check_error=RuntimeError("uv sync failed"),
        remove_error=RuntimeError("rm: Directory not empty"),
    )
    notifier = RecordingNotifier()

    with pytest.raises(PreflightError, match="check.sh: uv sync failed"):
        build_preflight(tmp_path, git=git, notifier=notifier).run()

    reasons = [info.reason for info in notifier.run_failed]
    assert reasons[0] == "preflight failed: check.sh: uv sync failed"
    assert "cleanup" in reasons[1]
    assert "rm: Directory not empty" in reasons[1]
    assert "check.sh" in reasons[1]


def test_an_interrupt_still_propagates_when_the_cleanup_fails(tmp_path):
    git = FakeGit(
        check_error=KeyboardInterrupt(),
        remove_error=RuntimeError("rm: Directory not empty"),
    )
    notifier = RecordingNotifier()

    with pytest.raises(KeyboardInterrupt):
        build_preflight(tmp_path, git=git, notifier=notifier).run()

    [info] = notifier.run_failed
    assert "interrupted during check.sh" in info.reason
    assert "rm: Directory not empty" in info.reason


def test_an_interrupt_with_a_clean_cleanup_sends_nothing(tmp_path):
    notifier = RecordingNotifier()

    with pytest.raises(KeyboardInterrupt):
        build_preflight(
            tmp_path, git=FakeGit(check_error=KeyboardInterrupt()), notifier=notifier
        ).run()

    assert notifier.run_failed == []


def test_preflight_fails_loudly_on_leftover_worktree_entries(tmp_path):
    git = FakeGit(leaked_error=RuntimeError("worktrees directory contains nf-66-leftover"))
    notifier = RecordingNotifier()

    with pytest.raises(PreflightError, match="verify worktrees directory"):
        build_preflight(tmp_path, git=git, notifier=notifier).run()

    assert "nf-66-leftover" in notifier.run_failed[0].reason
    assert [call[0] for call in git.calls][-1] == "verify_no_leaked_worktrees"


def test_preflight_removes_its_own_leftovers_and_goes_on(tmp_path):
    """A half-deleted preflight-* stopped every hourly run on 2026-11-19 (#194)."""
    leftover = tmp_path / "worktrees" / "preflight-1795099946"
    events = []
    git = FakeGit(leftovers=[leftover], events=events)
    notifier = RecordingNotifier()
    tickets = [Ticket(number=7, title="Ready", labels=frozenset({"ready-for-agent"}))]

    result = build_preflight(
        tmp_path, git=git, github=FakeGitHub(tickets), notifier=notifier, events=events
    ).run()

    assert result == tickets
    names = [call[0] for call in events]
    first = names.index("remove_worktree")
    assert events[first] == ("remove_worktree", leftover)
    assert events[first + 1] == ("delete_branch", "preflight-1795099946")
    assert first < names.index("verify_no_leaked_worktrees")
    [info] = notifier.cleaned_up
    assert str(leftover) in info.reason
    assert notifier.run_failed == []


def test_preflight_stops_when_a_leftover_cannot_be_removed(tmp_path):
    leftover = tmp_path / "worktrees" / "preflight-7"
    git = FakeGit(leftovers=[leftover], remove_error=RuntimeError("rm: Permission denied"))
    notifier = RecordingNotifier()

    with pytest.raises(PreflightError, match="remove preflight leftovers"):
        build_preflight(tmp_path, git=git, notifier=notifier).run()

    assert "rm: Permission denied" in notifier.run_failed[0].reason
    assert "create_worktree" not in [call[0] for call in git.calls]


class SandboxRunner:
    def __init__(self, events, error=None, model_errors=None):
        self.events = events
        self.error = error
        self.model_errors = dict(model_errors or {})

    def model_check(self, worktree, model, *, config_content):
        self.events.append(("model_check", model, config_content))
        if model in self.model_errors:
            raise self.model_errors[model]

    def ensure_clean(self):
        self.events.append(("agent_cleanup",))

    def verify_home_is_clean(self):
        self.events.append(("agent_home_clean",))

    def smoke_check(self, worktree):
        self.events.append(("opencode_smoke",))
        if self.error:
            raise self.error


def test_preflight_proves_cleanup_and_that_opencode_starts_as_the_agent(tmp_path):
    events = []
    preflight = build_preflight(tmp_path, events=events)
    preflight.runner = SandboxRunner(events)

    preflight.run()

    names = [event[0] for event in events]
    assert names.index("agent_cleanup") < names.index("agent_home_clean")
    assert names.index("agent_home_clean") < names.index("opencode_smoke")
    assert names.index("opencode_smoke") < names.index("create_agent_cleanup_probe")


def test_preflight_fails_when_opencode_cannot_start_as_the_agent(tmp_path):
    events = []
    preflight = build_preflight(tmp_path, events=events)
    preflight.runner = SandboxRunner(events, error=RuntimeError("EACCES mkdir"))

    with pytest.raises(PreflightError, match="verify agent sandbox"):
        preflight.run()


def test_preflight_checks_each_configured_model_after_opencode_starts(tmp_path):
    """A model whose provider login is missing must stop the run, not skip reviews (#202)."""
    events = []
    preflight = build_preflight(tmp_path, events=events)
    preflight.runner = SandboxRunner(events)

    preflight.run()

    checks = [event for event in events if event[0] == "model_check"]
    assert [event[1] for event in checks] == ["m", "s"]
    for event in checks:
        config = json.loads(event[2])
        assert config["permission"] == json.loads(REVIEWER_CONFIG)["permission"]
        assert config["agent"]["build"]["permission"] == config["permission"]
        assert config["default_agent"] == "build"
    names = [event[0] for event in events]
    assert names.index("opencode_smoke") < names.index("model_check")
    assert names.index("model_check") < names.index("create_agent_cleanup_probe")


def test_preflight_skips_a_model_that_answered_within_a_day(tmp_path):
    events = []
    preflight = build_preflight(tmp_path, events=events)
    preflight.runner = SandboxRunner(events)
    preflight.run()
    events.clear()

    preflight = build_preflight(tmp_path, events=events)
    preflight.runner = SandboxRunner(events)
    preflight.run()

    assert [event for event in events if event[0] == "model_check"] == []


def test_preflight_fails_naming_the_model_that_gives_no_answer(tmp_path):
    from factory.runner import AgentSandboxError

    events = []
    notifier = RecordingNotifier()
    preflight = build_preflight(tmp_path, events=events, notifier=notifier)
    preflight.runner = SandboxRunner(
        events, model_errors={"s": AgentSandboxError("s gave no answer (exit 0): no output")}
    )

    with pytest.raises(PreflightError, match="verify models"):
        preflight.run()

    assert "s gave no answer" in notifier.run_failed[0].reason
    retry = []
    preflight = build_preflight(tmp_path, events=retry)
    preflight.runner = SandboxRunner(retry)
    preflight.run()
    assert [event[1] for event in retry if event[0] == "model_check"] == ["s"]


def test_a_preflight_run_by_hand_rechecks_every_model(tmp_path):
    """After rotating a key, `factory preflight` must ask the model again."""
    events = []
    preflight = build_preflight(tmp_path, events=events)
    preflight.runner = SandboxRunner(events)
    preflight.run()
    events.clear()

    preflight = build_preflight(tmp_path, events=events)
    preflight.runner = SandboxRunner(events)
    preflight.recheck_models = True
    preflight.run()

    assert [event[1] for event in events if event[0] == "model_check"] == ["m", "s"]


def test_with_the_review_off_only_the_builder_model_is_checked(tmp_path):
    events = []
    preflight = build_preflight(tmp_path, events=events)
    preflight.settings = replace(preflight.settings, pre_pr_review=False)
    preflight.runner = SandboxRunner(events)

    preflight.run()

    assert [event[1] for event in events if event[0] == "model_check"] == ["m"]


def test_an_invalid_reviewer_config_fails_the_model_check_step(tmp_path):
    events = []
    git = FakeGit(events=events)
    git.reviewer_config = "{not json"
    preflight = build_preflight(tmp_path, git=git, events=events)
    preflight.runner = SandboxRunner(events)

    with pytest.raises(PreflightError, match="verify models: .*not valid JSON"):
        preflight.run()


def test_preflight_checks_one_model_once_when_both_settings_name_it(tmp_path):
    events = []
    preflight = build_preflight(tmp_path, events=events)
    preflight.settings = replace(preflight.settings, factory_strong_model="m")
    preflight.runner = SandboxRunner(events)

    preflight.run()

    assert [event[1] for event in events if event[0] == "model_check"] == ["m"]


def test_preflight_stops_with_the_create_commands_when_a_label_is_missing(tmp_path):
    events = []
    notifier = RecordingNotifier()
    github = FakeGitHub(labels=REQUIRED_LABELS - {"needs-decision", "deps-change"})

    with pytest.raises(PreflightError) as caught:
        build_preflight(tmp_path, github=github, notifier=notifier, events=events).run()

    assert caught.value.step == "verify labels"
    assert "create_worktree" not in [event[0] for event in events]
    reason = notifier.run_failed[0].reason
    assert "missing labels deps-change, needs-decision" in reason
    assert "gh label create <name> --repo daedraMex/commerce-platform" in reason


def test_preflight_stops_when_the_labels_cannot_be_listed(tmp_path):
    github = FakeGitHub(label_error=GitHubError("gh label list failed: HTTP 401"))

    with pytest.raises(PreflightError) as caught:
        build_preflight(tmp_path, github=github).run()

    assert caught.value.step == "verify labels"


def test_required_labels_cover_every_label_the_factory_reads_or_writes():
    assert REQUIRED_LABELS == {
        "ready-for-agent",
        "needs-decision",
        "strong-model",
        "migration",
        "deps-change",
    }


def test_preflight_names_every_missing_label_within_the_message_limit(tmp_path):
    notifier = RecordingNotifier()
    github = FakeGitHub(labels=())

    with pytest.raises(PreflightError):
        build_preflight(tmp_path, github=github, notifier=notifier).run()

    reason = notifier.run_failed[0].reason
    assert not reason.endswith("…")
    for name in REQUIRED_LABELS:
        assert name in reason
