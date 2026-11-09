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
MAX_CHECK_OUTPUT_CHARS = 4000

BASE_ENV_ALLOWLIST = ("PATH", "HOME", "LANG", "DATABASE_URL")

# Fixed, non-secret settings the backend needs to start without a worktree .env.
# Keep these values in sync with the `backend` job env in .github/workflows/ci.yml.
TEST_SETTINGS = {
    "SECRET_KEY": "ci-not-a-secret-change-me-0123456789",
    "DEBUG": "False",
    "ALLOWED_HOSTS": "localhost,127.0.0.1",
    "REDIS_URL": "redis://localhost:6379/0",
}


def sudo_argv(agent_user: str, argv: list[str], env: dict[str, str]) -> list[str]:
    """Wrap ``argv`` in a sudo downgrade that preserves exactly ``env``.

    sudo's ``env_reset`` drops the explicit environment, so the sudoers rule
    needs ``SETENV`` and we name each variable in ``--preserve-env``.
    """
    return [
        "sudo",
        "-n",
        f"--preserve-env={','.join(env)}",
        "-u",
        agent_user,
        "--",
        *argv,
    ]


def _allowlisted_env(
    base_env: dict[str, str],
    *,
    agent_user: str | None,
    agent_home: str | None,
) -> dict[str, str]:
    env: dict[str, str] = {}
    for name in BASE_ENV_ALLOWLIST:
        if name == "HOME" and agent_user:
            env["HOME"] = agent_home or f"/home/{agent_user}"
        elif base_env.get(name):
            env[name] = base_env[name]
    return env


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
    env.update(_allowlisted_env(base_env, agent_user=agent_user, agent_home=agent_home))
    env.update(TEST_SETTINGS)
    for name in provider_vars:
        value = base_env.get(name)
        if value:
            env[name] = value
    return env


def build_check_env(
    base_env: dict[str, str],
    *,
    agent_user: str | None,
    agent_home: str | None,
) -> dict[str, str]:
    """Build the explicit environment the check runner receives.

    The check runner executes agent-written code, so it gets only the base
    allowlist plus the fixed test settings: never the model provider key, the
    GitHub token or any other secret.
    """
    env = _allowlisted_env(base_env, agent_user=agent_user, agent_home=agent_home)
    env.update(TEST_SETTINGS)
    return env


def truncate_check_output(output: str, *, limit: int = MAX_CHECK_OUTPUT_CHARS) -> str:
    """Keep the tail of check output so agent feedback stays bounded."""
    if len(output) <= limit:
        return output
    return "… (earlier output truncated) …\n" + output[-limit:]


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
        argv: list[str] = [OPENCODE_BIN, "run", "--model", model, prompt]
        if self.agent_user:
            argv = sudo_argv(self.agent_user, argv, env)
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
