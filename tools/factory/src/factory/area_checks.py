"""Running each area's check script as the agent (sudo, ports, process groups)."""

from __future__ import annotations

import os
import shutil
import signal
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .areas import BACKEND, Area, select_areas
from .runner import (
    build_check_env,
    ensure_agent_cleanup,
    kill_agent_processes,
    sudo_argv,
    truncate_check_output,
)
from .shell import CommandTimeout, RunCommand, run_command

CHECK_TIMEOUT_SECONDS = 1800

REVIEW_TESTS_TIMEOUT_SECONDS = 600


@dataclass(frozen=True)
class CheckResult:
    """The result of running one or more areas' check scripts."""

    passed: bool
    output: str
    failed_areas: tuple[Area, ...] = ()
    checked_areas: tuple[Area, ...] = ()
    skipped_areas: tuple[Area, ...] = ()
    # One line per failed area: its name, how it ended and how long it took (#227).
    failures: tuple[str, ...] = ()


def describe_exit(code: int) -> str:
    """``exit 1``, ``killed by SIGKILL``, or ``exit 137 (a command was killed by SIGKILL)``.

    A negative code means the script itself died by a signal. A shell exits
    128 + n when a command it ran died by signal n, which is how a check.sh
    reports a test runner the kernel or a timeout killed.
    """
    if code < 0:
        return f"killed by {_signal_name(-code)}"
    if 128 < code < 128 + 65:
        name = _signal_name(code - 128)
        if name is not None:
            return f"exit {code} (a command was killed by {name})"
    return f"exit {code}"


def _signal_name(number: int) -> str | None:
    try:
        return signal.Signals(number).name
    except ValueError:
        return None


def port_in_use(port: int) -> bool:
    """Return True when something is already listening on ``port``."""
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.2)
                if sock.connect_ex((host, port)) == 0:
                    return True
        except OSError:
            continue
    return False


class AreaChecks:
    """Check scripts and the reviewer's attack tests, run as the unprivileged agent."""

    def __init__(
        self,
        run: RunCommand = run_command,
        *,
        changed_files: Callable[[Path], list[str]],
        agent_user: str | None = None,
        agent_home: str | None = None,
        base_env: dict[str, str] | None = None,
        port_in_use: Callable[[int], bool] = port_in_use,
        logs_dir: Path | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._run = run
        self._logs_dir = logs_dir
        self._clock = clock
        self._changed_files = changed_files
        self._agent_user = agent_user
        self._agent_home = agent_home
        self._base_env = dict(base_env if base_env is not None else os.environ)
        self._port_in_use = port_in_use

    def _port_still_busy(self, port: int) -> bool:
        """Check a fixed port, cleaning up leftover agent servers once first."""
        if not self._port_in_use(port):
            return False
        kill_agent_processes(self._run, self._agent_user)
        return self._port_in_use(port)

    def check(self, worktree: Path, *, areas: tuple[Area, ...] | None = None) -> CheckResult:
        """Run each selected area's check script as the agent user.

        With no explicit ``areas`` the ticket's changed files decide them; the
        preflight passes every area because its worktree is fresh main. Each
        script gets its own timeout and a labelled slice of the output. The
        agent wrote this code, so the scripts must run as the unprivileged agent
        user with only the environment allowlist their area needs — never as the
        factory user and never with secrets. A missing script is skipped, not a
        failure.
        """
        selected = select_areas(self._changed_files(worktree)) if areas is None else areas
        chunks: list[str] = []
        failures: list[str] = []
        statuses: list[str] = []
        kept: list[tuple[str, Path]] = []
        failed: list[Area] = []
        checked: list[Area] = []
        skipped: list[Area] = []
        for area in selected:
            script = worktree / area.script
            label = f"{area.name} ({area.script.as_posix()})"
            if not script.is_file():
                chunks.append(f"=== {label}: skipped (script not found) ===")
                skipped.append(area)
                continue
            if area.port is not None and self._port_still_busy(area.port):
                failed.append(area)
                chunks.append(f"=== {label}: failed: port {area.port} busy after agent cleanup ===")
                continue
            env = build_check_env(
                self._base_env,
                agent_user=self._agent_user,
                agent_home=self._agent_home,
                area=area,
            )
            checked.append(area)
            argv = [str(script)]
            if self._agent_user:
                argv = sudo_argv(self._agent_user, argv, env)
            started = self._clock()
            try:
                result = self._run(
                    argv,
                    str(script.parent),
                    timeout=CHECK_TIMEOUT_SECONDS,
                    env=env,
                    replace_env=True,
                )
            except CommandTimeout:
                kill_agent_processes(self._run, self._agent_user)
                failed.append(area)
                status = f"timed out after {CHECK_TIMEOUT_SECONDS}s"
                chunks.append(f"=== {label}: {status} ===")
                failures.append(f"{area.name}: {status}")
                statuses.append(f"{area.name} {status}")
                kept += self._keep(worktree, area, label, status, "", "", failed=True)
                continue
            except BaseException:
                # Ctrl+C or a stop: the check's agent processes never saw it (#197).
                kill_agent_processes(self._run, self._agent_user)
                raise
            status = f"{describe_exit(result.exit_code)} after {round(self._clock() - started)}s"
            output = result.stdout
            if result.stderr:
                output += ("\n" if output else "") + result.stderr
            body = output.strip()
            chunk = f"=== {label} ===\n{body}" if body else f"=== {label} ==="
            chunks.append(f"{chunk}\n--- {area.name}: {status}")
            statuses.append(f"{area.name} {status}")
            if result.exit_code != 0:
                failed.append(area)
                failures.append(f"{area.name}: {status}")
            kept += self._keep(
                worktree,
                area,
                label,
                status,
                result.stdout,
                result.stderr,
                failed=result.exit_code != 0,
            )
        # Tests and dev servers run as the agent; none may outlive the checks, and a
        # cleanup that cannot be trusted fails the run instead of passing silently.
        ensure_agent_cleanup(self._run, self._agent_user)
        output = truncate_check_output("\n\n".join(chunks).strip())
        # After the truncation, so every status and path survives a long output.
        if statuses:
            output += "\n\nStatus: " + "; ".join(statuses)
        if kept:
            output += "\nFull logs:\n" + "\n".join(f"- {name}: {path}" for name, path in kept)
        return CheckResult(
            passed=not failed,
            output=output,
            failed_areas=tuple(failed),
            checked_areas=tuple(checked),
            skipped_areas=tuple(skipped),
            failures=tuple(failures),
        )

    def _keep(
        self,
        worktree: Path,
        area: Area,
        label: str,
        status: str,
        stdout: str,
        stderr: str,
        *,
        failed: bool,
    ) -> list[tuple[str, Path]]:
        """Write the area's full output, and on failure copy its reports; return the paths.

        Named after the worktree, so a ticket's and a preflight's logs never mix.
        A copy that fails never fails the check: it says so in the log instead.
        """
        if self._logs_dir is None:
            return []
        self._logs_dir.mkdir(parents=True, exist_ok=True)
        log = self._logs_dir / f"{worktree.name}.{area.name}.log"
        log.write_text(
            f"# {label}\n# {status}\n\n{stdout}" + (f"\n--- stderr ---\n{stderr}" if stderr else "")
        )
        kept = [(area.name, log)]
        sources = [worktree / report for report in area.reports if (worktree / report).is_dir()]
        if failed and sources:
            target = self._logs_dir / f"{worktree.name}.{area.name}-report"
            try:
                if target.exists():
                    shutil.rmtree(target)
                for source in sources:
                    # The agent wrote these files: never follow its symlinks.
                    shutil.copytree(source, target / source.name, symlinks=True)
                os.utime(target)  # keep_days counts from now, not from the copied mtimes
                kept.append((f"{area.name} report", target))
            except OSError as exc:
                with log.open("a") as handle:
                    handle.write(f"\n# report not kept: {exc}\n")
        return kept

    def run_review_tests(self, worktree: Path, files: tuple[str, ...]) -> tuple[str, str]:
        """Run the reviewer's attack tests as the agent; return (status, output).

        ``files`` are backend-relative paths the runner chose. The tests go through
        ``backend/scripts/check.sh --review-tests``, the one backend entry the sudoers
        rule allows, with the backend's check environment. pytest exit 0 means the
        attacks held, 1 means one broke; anything else (refused path, import error,
        no tests collected, timeout) gives no verdict.
        """
        script = worktree / BACKEND.script
        if not script.is_file():
            return "error", "backend/scripts/check.sh not found"
        env = build_check_env(
            self._base_env,
            agent_user=self._agent_user,
            agent_home=self._agent_home,
            area=BACKEND,
        )
        # No bytecode: the runner deletes the tests afterwards, and an agent-owned
        # __pycache__ beside them would outlive that cleanup.
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        argv = [str(script), "--review-tests", *files]
        if self._agent_user:
            argv = sudo_argv(self._agent_user, argv, env)
        try:
            result = self._run(
                argv,
                str(script.parent),
                timeout=REVIEW_TESTS_TIMEOUT_SECONDS,
                env=env,
                replace_env=True,
            )
        except CommandTimeout:
            kill_agent_processes(self._run, self._agent_user)
            ensure_agent_cleanup(self._run, self._agent_user)
            return "error", f"attack tests timed out after {REVIEW_TESTS_TIMEOUT_SECONDS}s"
        except BaseException:
            # Ctrl+C or a stop: the tests' agent processes never saw it (#197).
            kill_agent_processes(self._run, self._agent_user)
            raise
        ensure_agent_cleanup(self._run, self._agent_user)
        output = result.stdout + (("\n" + result.stderr) if result.stderr else "")
        if result.exit_code == 0:
            return "held", output
        if result.exit_code == 1:
            return "broke", output
        return "error", output

    def place_review_tests(self, worktree: Path, tests: dict[str, str]) -> None:
        """Write the attack tests at backend-relative paths the runner chose."""
        for relpath, content in tests.items():
            path = worktree / "backend" / relpath
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)

    def remove_review_tests(self, worktree: Path, relpaths: tuple[str, ...]) -> None:
        """Delete the attack tests, then their directory if nothing else is in it."""
        parents = set()
        for relpath in relpaths:
            path = worktree / "backend" / relpath
            path.unlink(missing_ok=True)
            parents.add(path.parent)
        for parent in parents:
            if parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
