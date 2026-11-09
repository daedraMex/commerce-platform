from pathlib import Path

import pytest

from factory.shell import CommandResult
from factory.sudoers import SudoersError, has_no_log_allowed, verify_sudoers_logging

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class FakeRun:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, argv, cwd, *, timeout, env=None, replace_env=False):
        self.calls.append((argv, cwd, env, replace_env))
        return self.result


def recorded(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_accepts_recorded_sudo_l_output_with_no_log_allowed():
    run = FakeRun(CommandResult(0, recorded("sudo_l_no_log_allowed.txt"), ""))

    verify_sudoers_logging(run)


def test_rejects_recorded_sudo_l_output_with_log_allowed():
    run = FakeRun(CommandResult(0, recorded("sudo_l_log_allowed.txt"), ""))

    with pytest.raises(SudoersError, match="!log_allowed"):
        verify_sudoers_logging(run)


def test_fails_closed_when_sudo_l_returns_nonzero():
    run = FakeRun(CommandResult(1, "", "sudo: a password is required"))

    with pytest.raises(SudoersError, match="sudo -n -l"):
        verify_sudoers_logging(run)


def test_fails_closed_when_the_defaults_block_is_missing():
    run = FakeRun(CommandResult(0, "User factory may run the following commands:\n", ""))

    with pytest.raises(SudoersError, match="Matching Defaults"):
        verify_sudoers_logging(run)


def test_only_the_matching_defaults_block_counts():
    text = (
        "User factory may run the following commands on factory-host:\n"
        "    (factory-agent) NOPASSWD: /usr/bin/true !log_allowed\n"
    )

    assert has_no_log_allowed(text) is False


def test_runs_non_interactive_sudo_l_with_a_stable_locale():
    run = FakeRun(CommandResult(0, recorded("sudo_l_no_log_allowed.txt"), ""))

    verify_sudoers_logging(run)

    assert run.calls == [(["sudo", "-n", "-l"], "/", {"LC_ALL": "C"}, False)]
