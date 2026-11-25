"""factory-agent cannot schedule work that outlives the factory's cleanup (#231)."""

import pytest

from factory.agent_scheduling import SchedulingError, SchedulingPaths, verify_agent_cannot_schedule
from factory.preflight import MAX_ERROR_CHARS
from factory.shell import CommandResult

AGENT = "factory-agent"


def _paths(tmp_path, *, at_installed=True):
    etc = tmp_path / "etc"
    etc.mkdir(parents=True, exist_ok=True)
    linger = tmp_path / "linger"
    linger.mkdir(exist_ok=True)
    at_bin = tmp_path / "at"
    if at_installed:
        at_bin.write_text("")
    return SchedulingPaths(
        cron_allow=etc / "cron.allow",
        cron_deny=etc / "cron.deny",
        at_allow=etc / "at.allow",
        at_deny=etc / "at.deny",
        at_binary=at_bin,
        linger_dir=linger,
    )


def _no_manager(argv, cwd, *, timeout, env=None, replace_env=False):
    assert argv == ["/usr/bin/pgrep", "-u", AGENT, "-x", "systemd"]
    return CommandResult(1, "", "")


def _safe(tmp_path, **kwargs):
    paths = _paths(tmp_path, **kwargs)
    paths.cron_deny.write_text("daemon\nfactory-agent\n")
    paths.at_deny.write_text("factory-agent\n")
    return paths


def test_a_denied_agent_without_lingering_or_a_user_manager_passes(tmp_path):
    verify_agent_cannot_schedule(AGENT, _safe(tmp_path), run=_no_manager)


def test_cron_with_neither_list_lets_every_user_schedule(tmp_path):
    paths = _safe(tmp_path)
    paths.cron_deny.unlink()

    with pytest.raises(SchedulingError, match="cron") as excinfo:
        verify_agent_cannot_schedule(AGENT, paths, run=_no_manager)

    assert f"echo {AGENT} >> {paths.cron_deny}" in str(excinfo.value)


def test_cron_deny_without_the_agent_fails(tmp_path):
    paths = _safe(tmp_path)
    paths.cron_deny.write_text("daemon\nfactory-agent-2\n# factory-agent\n")

    with pytest.raises(SchedulingError, match="cron"):
        verify_agent_cannot_schedule(AGENT, paths, run=_no_manager)


def test_an_allow_list_decides_over_the_deny_list(tmp_path):
    paths = _safe(tmp_path)
    paths.cron_allow.write_text("root\ndaedramx\n")
    verify_agent_cannot_schedule(AGENT, paths, run=_no_manager)

    paths.cron_allow.write_text("root\nfactory-agent\n")
    with pytest.raises(SchedulingError, match="cron.allow"):
        verify_agent_cannot_schedule(AGENT, paths, run=_no_manager)


def test_at_not_installed_or_with_neither_list_is_root_only(tmp_path):
    paths = _safe(tmp_path, at_installed=False)
    paths.at_deny.unlink()
    verify_agent_cannot_schedule(AGENT, paths, run=_no_manager)

    paths = _safe(tmp_path / "with-at")
    paths.at_deny.unlink()
    verify_agent_cannot_schedule(AGENT, paths, run=_no_manager)


def test_at_deny_without_the_agent_fails(tmp_path):
    paths = _safe(tmp_path)
    paths.at_deny.write_text("nobody\n")

    with pytest.raises(SchedulingError, match="at.deny"):
        verify_agent_cannot_schedule(AGENT, paths, run=_no_manager)


def test_an_unreadable_list_fails_with_the_fix(tmp_path, monkeypatch):
    paths = _safe(tmp_path)
    original = type(paths.at_deny).read_text

    def unreadable(self, *args, **kwargs):
        if self == paths.at_deny:
            raise PermissionError(13, "Permission denied")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(type(paths.at_deny), "read_text", unreadable)

    with pytest.raises(SchedulingError, match=f"cannot read {paths.at_deny}") as excinfo:
        verify_agent_cannot_schedule(AGENT, paths, run=_no_manager)

    assert f"sudo chmod 644 {paths.at_deny}" in str(excinfo.value)


def test_lingering_fails(tmp_path):
    paths = _safe(tmp_path)
    (paths.linger_dir / AGENT).write_text("")

    with pytest.raises(SchedulingError, match="loginctl disable-linger factory-agent"):
        verify_agent_cannot_schedule(AGENT, paths, run=_no_manager)


def test_a_running_user_manager_fails(tmp_path):
    def manager(argv, cwd, *, timeout, env=None, replace_env=False):
        return CommandResult(0, "4242\n", "")

    with pytest.raises(SchedulingError, match="loginctl terminate-user factory-agent"):
        verify_agent_cannot_schedule(AGENT, _safe(tmp_path), run=manager)


def test_a_pgrep_that_cannot_answer_fails(tmp_path):
    def broken(argv, cwd, *, timeout, env=None, replace_env=False):
        return CommandResult(2, "", "pgrep: invalid user name")

    with pytest.raises(SchedulingError, match="cannot tell"):
        verify_agent_cannot_schedule(AGENT, _safe(tmp_path), run=broken)


def test_every_problem_is_named_and_the_message_stays_short(tmp_path):
    paths = _paths(tmp_path)
    paths.at_deny.write_text("nobody\n")
    (paths.linger_dir / AGENT).write_text("")

    with pytest.raises(SchedulingError) as excinfo:
        verify_agent_cannot_schedule(AGENT, paths, run=_no_manager)

    message = str(excinfo.value)
    assert message.startswith("factory-agent can schedule work: cron")
    assert "3 problems" in message
    assert len("verify agent scheduling: " + message) <= MAX_ERROR_CHARS
