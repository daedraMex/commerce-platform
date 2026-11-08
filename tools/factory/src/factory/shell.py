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
