"""The agent run: one ``opencode run`` invocation, as the agent user.

OpenCode runs with an explicit environment allowlist — not the factory user's
full environment — so nothing except the approved variables reaches the model.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .shell import CommandTimeout, RunCommand, run_command

OPENCODE_CONFIG_PATH = "tools/factory/opencode.factory.json"
OPENCODE_BIN = "/usr/bin/opencode"

BASE_ENV_ALLOWLIST = ("PATH", "HOME", "LANG", "DATABASE_URL")


def build_agent_env(
    base_env: dict[str, str],
    *,
    config_path: str,
    agent_user: str | None,
    agent_home: str | None,
    provider_vars: tuple[str, ...],
) -> dict[str, str]:
    """Build the explicit environment the agent subprocess receives."""
    env = {"OPENCODE_CONFIG": config_path}
    for name in BASE_ENV_ALLOWLIST:
        if name == "HOME" and agent_user:
            env["HOME"] = agent_home or f"/home/{agent_user}"
        elif base_env.get(name):
            env[name] = base_env[name]
    for name in provider_vars:
        value = base_env.get(name)
        if value:
            env[name] = value
    return env


@dataclass(frozen=True)
class AgentResult:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool


class AgentRunner:
    def __init__(
        self,
        run: RunCommand = run_command,
        *,
        agent_user: str | None = None,
        agent_home: str | None = None,
        provider_env_vars: tuple[str, ...] = (),
        base_env: dict[str, str] | None = None,
    ):
        self._run = run
        self.agent_user = agent_user
        self.agent_home = agent_home
        self.provider_env_vars = provider_env_vars
        self.base_env = dict(base_env if base_env is not None else os.environ)

    def run(
        self,
        *,
        worktree: Path,
        model: str,
        prompt: str,
        timeout_seconds: int,
    ) -> AgentResult:
        env = build_agent_env(
            self.base_env,
            config_path=str(worktree / OPENCODE_CONFIG_PATH),
            agent_user=self.agent_user,
            agent_home=self.agent_home,
            provider_vars=self.provider_env_vars,
        )
        argv: list[str] = []
        if self.agent_user:
            argv += ["sudo", "-n", "-u", self.agent_user, "--"]
        argv += [OPENCODE_BIN, "run", "--model", model, prompt]
        try:
            result = self._run(
                argv,
                str(worktree),
                timeout=timeout_seconds,
                env=env,
                replace_env=True,
            )
        except CommandTimeout:
            return AgentResult(exit_code=None, stdout="", stderr="", timed_out=True)
        return AgentResult(
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            timed_out=False,
        )
