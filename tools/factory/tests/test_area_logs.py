"""Each area's full check output, exit status and Playwright report are kept (#227)."""

import signal
from pathlib import Path

import pytest

from factory.area_checks import AreaChecks, describe_exit
from factory.areas import BACKEND, CONSOLE
from factory.preflight import MAX_ERROR_CHARS
from factory.shell import CommandResult, CommandTimeout


class Run:
    def __init__(self, results):
        self.results = dict(results)  # area script name -> CommandResult | Exception
        self.calls = []

    def __call__(self, argv, cwd, *, timeout, env=None, replace_env=False):
        self.calls.append(argv)
        if "/usr/bin/pkill" in argv:
            return CommandResult(1, "", "")
        for key, result in self.results.items():
            if any(key in part for part in argv):
                if isinstance(result, BaseException):
                    raise result
                return result
        return CommandResult(0, "", "")


def _worktree(tmp_path, name="preflight-42"):
    worktree = tmp_path / "worktrees" / name
    for area in (BACKEND, CONSOLE):
        script = worktree / area.script
        script.parent.mkdir(parents=True)
        script.write_text("#!/bin/sh\n")
    return worktree


def _checks(run, logs, ticks=(0.0, 12.4, 12.4, 430.0)):
    clock = iter(ticks)
    return AreaChecks(
        run,
        changed_files=lambda _w: [],
        port_in_use=lambda _p: False,
        logs_dir=logs,
        clock=lambda: next(clock),
    )


@pytest.mark.parametrize(
    ("code", "text"),
    [
        (0, "exit 0"),
        (1, "exit 1"),
        (137, "exit 137 (a command was killed by SIGKILL)"),
        (143, "exit 143 (a command was killed by SIGTERM)"),
        (-int(signal.SIGKILL), "killed by SIGKILL"),
        (200, "exit 200"),
    ],
)
def test_an_exit_says_whether_a_signal_ended_it(code, text):
    assert describe_exit(code) == text


def test_every_area_writes_its_full_output_and_status_to_its_own_log(tmp_path):
    worktree = _worktree(tmp_path)
    logs = tmp_path / "logs"
    long = "x" * 10_000
    run = Run(
        {
            "backend/scripts": CommandResult(0, f"{long}\n512 passed", ""),
            "console/scripts": CommandResult(137, "> test:e2e", "Killed"),
        }
    )

    result = _checks(run, logs).check(worktree, areas=(BACKEND, CONSOLE))

    backend_log = logs / "preflight-42.backend.log"
    console_log = logs / "preflight-42.console.log"
    assert long in backend_log.read_text()  # full, never truncated
    assert "exit 0 after 12s" in backend_log.read_text()
    console = console_log.read_text()
    assert "exit 137 (a command was killed by SIGKILL) after 418s" in console
    assert "> test:e2e" in console and "Killed" in console
    assert result.failures == ("console: exit 137 (a command was killed by SIGKILL) after 418s",)


def test_the_bounded_output_keeps_each_status_and_ends_with_the_log_paths(tmp_path):
    worktree = _worktree(tmp_path)
    logs = tmp_path / "logs"
    run = Run(
        {
            "backend/scripts": CommandResult(0, "y" * 20_000, ""),
            "console/scripts": CommandResult(1, "z" * 20_000, ""),
        }
    )

    result = _checks(run, logs).check(worktree, areas=(BACKEND, CONSOLE))

    assert "--- console: exit 1 after 418s" in result.output
    assert result.output.rstrip().endswith(str(logs / "preflight-42.console.log"))
    assert f"backend: {logs / 'preflight-42.backend.log'}" in result.output
    assert len(result.output) < 4_000 + 1_000


def test_a_timed_out_area_keeps_its_log_and_says_so(tmp_path):
    worktree = _worktree(tmp_path)
    logs = tmp_path / "logs"
    run = Run({"console/scripts": CommandTimeout("console")})

    result = _checks(run, logs).check(worktree, areas=(CONSOLE,))

    assert result.failures[0].startswith("console: timed out after")
    assert "timed out" in (logs / "preflight-42.console.log").read_text()


def test_a_failed_console_check_keeps_its_playwright_report(tmp_path):
    worktree = _worktree(tmp_path)
    logs = tmp_path / "logs"
    report = worktree / "web" / "console" / "test-results" / "photos-retry"
    report.mkdir(parents=True)
    (report / "trace.zip").write_text("trace")
    (worktree / "web" / "console" / "playwright-report").mkdir()
    (worktree / "web" / "console" / "playwright-report" / "index.html").write_text("<html>")
    outside = tmp_path / "secret"
    outside.write_text("nope")
    (report / "link").symlink_to(outside)
    run = Run({"console/scripts": CommandResult(1, "1 failed", "")})

    result = _checks(run, logs).check(worktree, areas=(CONSOLE,))

    kept = logs / "preflight-42.console-report"
    assert (kept / "test-results" / "photos-retry" / "trace.zip").read_text() == "trace"
    assert (kept / "playwright-report" / "index.html").exists()
    assert (kept / "test-results" / "photos-retry" / "link").is_symlink()  # never followed
    assert f"console report: {kept}" in result.output


def test_a_passing_area_keeps_no_report(tmp_path):
    worktree = _worktree(tmp_path)
    (worktree / "web" / "console" / "test-results").mkdir()
    logs = tmp_path / "logs"

    _checks(Run({}), logs).check(worktree, areas=(CONSOLE,))

    assert not (logs / "preflight-42.console-report").exists()


def test_without_a_logs_dir_nothing_is_written(tmp_path):
    worktree = _worktree(tmp_path)
    run = Run({"console/scripts": CommandResult(1, "boom", "")})

    result = _checks(run, None).check(worktree, areas=(CONSOLE,))

    assert result.failures == ("console: exit 1 after 12s",)
    assert "Full logs" not in result.output


def test_a_preflight_failure_names_the_area_and_its_status_within_the_limit():
    from factory.preflight import check_failure_message

    message = check_failure_message(
        ("console: exit 137 (a command was killed by SIGKILL) after 418s",),
        Path("/home/factory/factory/logs/preflight-1795586084.log"),
    )

    assert message.startswith("check.sh failed: console: exit 137")
    assert message.endswith("see /home/factory/factory/logs/preflight-1795586084.log")
    assert len("check.sh: " + message) <= MAX_ERROR_CHARS


def test_old_area_logs_and_reports_go_with_the_run_logs(tmp_path):
    import os
    import time

    from factory.cleanup import cleanup_old

    logs = tmp_path / "logs"
    report = logs / "preflight-1.console-report" / "test-results"
    report.mkdir(parents=True)
    (report / "trace.zip").write_text("t")
    old_log = logs / "preflight-1.console.log"
    old_log.write_text("old")
    fresh = logs / "preflight-2.console.log"
    fresh.write_text("new")
    long_ago = time.time() - 30 * 86400
    for path in (old_log, logs / "preflight-1.console-report"):
        os.utime(path, (long_ago, long_ago))

    cleanup_old(logs, keep_days=14)

    assert not old_log.exists()
    assert not (logs / "preflight-1.console-report").exists()
    assert fresh.exists()
