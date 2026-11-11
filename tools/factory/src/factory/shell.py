"""Thin wrapper over subprocess so every external call is faked in tests."""

from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Callable
from dataclasses import dataclass


class CommandTimeout(RuntimeError):
    """Raised when an external command exceeds its time limit."""


@dataclass(frozen=True)
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str


RunCommand = Callable[..., CommandResult]


def merge_env(overrides: dict[str, str | None] | None) -> dict[str, str]:
    """Merge overrides over the current environment; a ``None`` value removes a key."""
    merged = os.environ.copy()
    if overrides:
        for key, value in overrides.items():
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = value
    return merged


def run_command(
    argv: list[str],
    cwd: str,
    *,
    timeout: int = 300,
    env: dict[str, str | None] | None = None,
    replace_env: bool = False,
) -> CommandResult:
    if replace_env:
        merged_env = {key: value for key, value in (env or {}).items() if value is not None}
    else:
        merged_env = merge_env(env)
    # Start the command in its own session so a timeout can kill the whole
    # process group. Killing only sudo would orphan next/playwright children.
    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=merged_env,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _kill_process_group(proc)
        proc.communicate()
        raise CommandTimeout(f"command timed out after {timeout}s: {' '.join(argv)}") from exc
    return CommandResult(exit_code=proc.returncode, stdout=stdout, stderr=stderr)


def _kill_process_group(proc: subprocess.Popen) -> None:
    """Kill the child and every process it started, without leaking them."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except ProcessLookupError:
        proc.kill()
