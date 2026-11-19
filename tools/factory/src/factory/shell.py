"""Thin wrapper over subprocess so every external call is faked in tests."""

from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

TIMEOUT_GRACE_SECONDS = 20
# Shorter than a timeout's grace: someone pressed Ctrl+C and is waiting.
INTERRUPT_GRACE_SECONDS = 5


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
        _terminate_process_group(proc, grace_seconds=TIMEOUT_GRACE_SECONDS)
        raise CommandTimeout(f"command timed out after {timeout}s: {' '.join(argv)}") from exc
    except BaseException:
        # Ctrl+C or SystemExit reaches only the factory: the command runs in its own
        # session. Stop it before the caller's cleanup deletes the files it is
        # writing (#194). Agent-user processes still need the caller's pkill.
        _terminate_process_group(proc, grace_seconds=INTERRUPT_GRACE_SECONDS)
        raise
    return CommandResult(exit_code=proc.returncode, stdout=stdout, stderr=stderr)


def _terminate_process_group(proc: subprocess.Popen, *, grace_seconds: int) -> None:
    """Stop the command group, giving sudo time to relay SIGTERM first.

    Sending SIGTERM to sudo lets it forward the signal to the command it
    started. After the grace period the whole same-user group is killed. When
    the command runs as another user, that kill only reaches sudo; the caller
    follows up with the agent-user ``pkill`` cleanup.
    """
    try:
        proc.terminate()
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    for pipe in (proc.stdout, proc.stderr):
        if pipe is not None:
            pipe.close()
