"""The agent run: one ``opencode run`` invocation per ticket."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .shell import CommandTimeout, RunCommand, run_command

OPENCODE_CONFIG_PATH = "tools/factory/opencode.factory.json"


@dataclass(frozen=True)
class AgentResult:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool


class AgentRunner:
    def __init__(self, run: RunCommand = run_command):
        self._run = run

    def run(
        self,
        *,
        worktree: Path,
        model: str,
        prompt: str,
        timeout_seconds: int,
    ) -> AgentResult:
        config_path = worktree / OPENCODE_CONFIG_PATH
        argv = ["opencode", "run", "--model", model, prompt]
        env = {"OPENCODE_CONFIG": str(config_path)}
        try:
            result = self._run(
                argv,
                str(worktree),
                timeout=timeout_seconds,
                env=env,
            )
        except CommandTimeout:
            return AgentResult(exit_code=None, stdout="", stderr="", timed_out=True)
        return AgentResult(
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            timed_out=False,
        )
