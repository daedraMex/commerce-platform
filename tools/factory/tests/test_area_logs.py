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

    backend_log = logs / "preflight-42.1.backend.log"
    console_log = logs / "preflight-42.1.console.log"
    assert long in backend_log.read_text()  # full, never truncated
    assert "exit 0 after 12s" in backend_log.read_text()
    console = console_log.read_text()
    assert "exit 137 (a command was killed by SIGKILL) after 418s" in console
    assert "> test:e2e" in console and "Killed" in console
    assert result.failures == ("console: exit 137 (a command was killed by SIGKILL) after 418s",)


def test_the_summary_holds_every_status_and_path_and_stays_out_of_the_agent_output(tmp_path):
    worktree = _worktree(tmp_path)
    logs = tmp_path / "logs"
    run = Run(
        {
            "backend/scripts": CommandResult(0, "y" * 20_000, ""),
            "console/scripts": CommandResult(1, "z" * 20_000, ""),
        }
    )

    result = _checks(run, logs).check(worktree, areas=(BACKEND, CONSOLE))

    assert result.summary.startswith("Status: backend exit 0 after 12s; console exit 1 after 418s")
    assert f"- backend: {logs / 'preflight-42.1.backend.log'}" in result.summary
    assert f"- console: {logs / 'preflight-42.1.console.log'}" in result.summary
    # The agent and the PR body get the bounded output: the failed area's status,
    # no paths it cannot read, and no line for a passing area.
    assert result.output.rstrip().endswith("--- console: exit 1 after 418s")
    assert str(logs) not in result.output
    assert "--- backend" not in result.output
    assert len(result.output) < 4_200


def test_each_check_of_a_worktree_keeps_its_own_log(tmp_path):
    worktree = _worktree(tmp_path, "nf-212-slug")
    logs = tmp_path / "logs"
    checks = _checks(Run({}), logs, ticks=(0.0, 1.0, 2.0, 3.0))

    checks.check(worktree, areas=(BACKEND,))
    checks.check(worktree, areas=(BACKEND,))

    assert (logs / "nf-212-slug.1.backend.log").exists()
    assert (logs / "nf-212-slug.2.backend.log").exists()


def test_a_timed_out_area_keeps_what_it_printed_before_the_timeout(tmp_path):
    worktree = _worktree(tmp_path)
    logs = tmp_path / "logs"
    run = Run({"console/scripts": CommandTimeout("slow", stdout="> test:e2e\nstarting", stderr="")})

    result = _checks(run, logs).check(worktree, areas=(CONSOLE,))

    assert result.failures[0].startswith("console: timed out after")
    log = (logs / "preflight-42.1.console.log").read_text()
    assert "timed out" in log and "> test:e2e\nstarting" in log


def test_a_command_timeout_carries_the_partial_output():
    from factory.shell import run_command

    with pytest.raises(CommandTimeout) as excinfo:
        run_command(["bash", "-c", "echo before; echo err >&2; sleep 5"], "/", timeout=1)

    assert excinfo.value.stdout == "before\n"
    assert excinfo.value.stderr == "err\n"


def _report_tree(worktree):
    console = worktree / "web" / "console"
    results = console / "test-results" / "photos-retry"
    results.mkdir(parents=True)
    (results / "trace.zip").write_text("trace")
    (console / "playwright-report").mkdir()
    (console / "playwright-report" / "index.html").write_text("<html>")
    return console


def test_a_failed_console_check_keeps_its_playwright_report(tmp_path):
    worktree = _worktree(tmp_path)
    _report_tree(worktree)
    logs = tmp_path / "logs"
    run = Run({"console/scripts": CommandResult(1, "1 failed", "")})

    result = _checks(run, logs).check(worktree, areas=(CONSOLE,))

    kept = logs / "preflight-42.1.console-report"
    assert (kept / "test-results" / "photos-retry" / "trace.zip").read_text() == "trace"
    assert (kept / "playwright-report" / "index.html").exists()
    assert f"- console report: {kept}" in result.summary
    assert "test-results: copied 1 files" in (logs / "preflight-42.1.console.log").read_text()


def test_a_report_folder_that_is_a_link_is_never_followed(tmp_path):
    worktree = _worktree(tmp_path)
    home = tmp_path / "factory-home"
    (home / "state").mkdir(parents=True)
    (home / "state" / "attempts.log").write_text("ledger")
    console = worktree / "web" / "console"
    (console / "test-results").symlink_to(home)
    logs = tmp_path / "logs"

    _checks(Run({"console/scripts": CommandResult(1, "", "")}), logs).check(
        worktree, areas=(CONSOLE,)
    )

    assert not list(logs.rglob("attempts.log"))
    assert "test-results not kept" in (logs / "preflight-42.1.console.log").read_text()


def test_links_and_special_files_inside_a_report_are_skipped(tmp_path):
    import os

    worktree = _worktree(tmp_path)
    console = _report_tree(worktree)
    secret = tmp_path / "secret"
    secret.write_text("nope")
    results = console / "test-results"
    (results / "link-to-file").symlink_to(secret)
    (results / "link-to-dir").symlink_to(tmp_path)
    os.mkfifo(results / "pipe")
    logs = tmp_path / "logs"

    _checks(Run({"console/scripts": CommandResult(1, "", "")}), logs).check(
        worktree, areas=(CONSOLE,)
    )

    kept = logs / "preflight-42.1.console-report" / "test-results"
    assert sorted(p.name for p in kept.iterdir()) == ["photos-retry"]
    assert "skipped 3 links or special files" in (logs / "preflight-42.1.console.log").read_text()


def test_the_copy_stops_at_its_limits_and_uses_its_own_modes(tmp_path):
    import stat

    from factory.report_copy import copy_report

    source = tmp_path / "test-results"
    locked = source / "locked"
    locked.mkdir(parents=True)
    for n in range(5):
        (locked / f"f{n}.txt").write_text("x" * 10)
    locked.chmod(0o555)

    try:
        report = copy_report(source, tmp_path / "copy", max_bytes=1_000, max_files=3)
    finally:
        locked.chmod(0o755)

    assert report.files == 3 and report.stopped == ["more than 3 files"]
    assert stat.S_IMODE((tmp_path / "copy" / "locked").stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "copy" / "locked" / "f0.txt").stat().st_mode) == 0o600

    big = tmp_path / "big"
    big.mkdir()
    (big / "huge.bin").write_bytes(b"x" * 5_000)
    report = copy_report(big, tmp_path / "copy-big", max_bytes=1_000)
    assert report.stopped == ["over 1000 bytes"]


def test_a_passing_area_keeps_no_report(tmp_path):
    worktree = _worktree(tmp_path)
    _report_tree(worktree)
    logs = tmp_path / "logs"

    _checks(Run({}), logs).check(worktree, areas=(CONSOLE,))

    assert not list(logs.glob("*-report"))


def test_without_a_logs_dir_nothing_is_written(tmp_path):
    worktree = _worktree(tmp_path)
    run = Run({"console/scripts": CommandResult(1, "boom", "")})

    result = _checks(run, None).check(worktree, areas=(CONSOLE,))

    assert result.failures == ("console: exit 1 after 12s",)
    assert "Full logs" not in result.summary


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
    report = logs / "preflight-1.1.console-report" / "test-results"
    report.mkdir(parents=True)
    (report / "trace.zip").write_text("t")
    old_log = logs / "preflight-1.1.console.log"
    old_log.write_text("old")
    fresh = logs / "preflight-2.1.console.log"
    fresh.write_text("new")
    long_ago = time.time() - 30 * 86400
    locked = report / "locked"
    locked.mkdir()
    locked.chmod(0o555)  # read-only folders must not stop the cleanup
    for path in (old_log, logs / "preflight-1.1.console-report"):
        os.utime(path, (long_ago, long_ago))

    cleanup_old(logs, keep_days=14)

    assert not old_log.exists()
    assert not (logs / "preflight-1.1.console-report").exists()
    assert fresh.exists()
