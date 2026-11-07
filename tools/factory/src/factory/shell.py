"""Thin wrapper over subprocess so every external call is faked in tests."""

from __future__ import annotations

import os
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


def run_command(
    argv: list[str],
    cwd: str,
    *,
    timeout: int = 300,
    env: dict[str, str] | None = None,
) -> CommandResult:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=merged_env,
        )
    except subprocess.TimeoutExpired as exc:
        raise CommandTimeout(f"command timed out after {timeout}s: {' '.join(argv)}") from exc
    return CommandResult(exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
