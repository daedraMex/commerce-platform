"""The agent run: one ``opencode run`` invocation, as the agent user.

OpenCode runs with an explicit environment allowlist — not the factory user's
full environment — so nothing except the approved variables reaches the model.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .areas import Area
from .shell import CommandTimeout, RunCommand, run_command

OPENCODE_CONFIG_PATH = "tools/factory/opencode.factory.json"
OPENCODE_BIN = "/usr/bin/opencode"
MAX_CHECK_OUTPUT_CHARS = 4000
AGENT_KILL_BIN = "/usr/bin/pkill"
AGENT_KILL_TIMEOUT_SECONDS = 60

BASE_ENV_ALLOWLIST = ("PATH", "HOME", "LANG", "DATABASE_URL")

# Fixed, non-secret settings the backend needs to start without a worktree .env.
# Keep these values in sync with the `backend` job env in .github/workflows/ci.yml.
TEST_SETTINGS = {
    "SECRET_KEY": "ci-not-a-secret-change-me-0123456789",
    "DEBUG": "False",
    "ALLOWED_HOSTS": "localhost,127.0.0.1",
    "REDIS_URL": "redis://localhost:6379/0",
    "PYTEST_ADDOPTS": "-p no:cacheprovider",
}


# The preflight's model check (#202): a fixed token proves the model answered.
MODEL_CHECK_TOKEN = "FACTORY-MODEL-OK"
MODEL_CHECK_PROMPT = (
    f"Reply with exactly {MODEL_CHECK_TOKEN} and nothing else. Do not use any tool."
)
MODEL_CHECK_TIMEOUT_SECONDS = 180


def agent_cleanup_argv(agent_user: str) -> list[str]:
    """The sudo-gated command that kills every process the agent still owns.

    The factory cannot signal ``factory-agent`` processes directly: signals
    across users fail with EPERM, so ``killpg`` from the factory user only
    reaches sudo. Running ``pkill`` as the agent user cleans up whatever sudo
    could not relay the timeout to (next, Playwright, Chromium).
    """
    return ["sudo", "-n", "-u", agent_user, AGENT_KILL_BIN, "-KILL", "-u", agent_user]


class AgentSandboxError(RuntimeError):
    """The agent's sandbox could not be proven: cleanup failed or its home was tampered."""


# Home-directory sources OpenCode loads even with project config disabled; the agent
# owns its home, so any of these appearing means something planted config (#153).
AGENT_HOME_PLANTS = (".opencode", ".claude", ".agents")
MAX_CLEANUP_PASSES = 3


def ensure_agent_cleanup(run: RunCommand, agent_user: str | None) -> None:
    """Kill every agent process, repeating while pkill still finds some.

    pkill exits 1 when nothing matched; 0 or a SIGKILL of its sudo wrapper means it
    killed something (``KILLED_SOMETHING``), so it runs again. Anything else, or sudo
    refusing (which also exits 1), means the cleanup cannot be trusted and raises, so
    a broken sudoers rule fails loudly instead of silently.
    """
    if not agent_user:
        return
    for _ in range(MAX_CLEANUP_PASSES):
        result = run(agent_cleanup_argv(agent_user), "/", timeout=AGENT_KILL_TIMEOUT_SECONDS)
        refusal = _sudo_refusal(result.stderr)
        if refusal:
            raise AgentSandboxError(f"agent cleanup refused by sudo: {refusal}")
        if result.exit_code == 1:
            return
        if result.exit_code not in KILLED_SOMETHING:
            raise AgentSandboxError(
                f"agent cleanup failed: {result.stderr.strip() or result.exit_code}"
            )
    raise AgentSandboxError(
        f"agent processes still running after {MAX_CLEANUP_PASSES} pkill passes"
    )


# pkill exits 0 when it killed processes. While killing live agent processes it can
# also take down the sudo running it, which then reports SIGKILL: -9 from Python,
# 137 from a shell. Both mean "killed something; check again" (seen on the machine).
KILLED_SOMETHING = frozenset({0, -9, 137})


# sudo warnings that do not stop the command it runs.
_HARMLESS_SUDO = ("unable to resolve host",)


def _sudo_refusal(stderr: str) -> str:
    """The first sudo error line in ``stderr``, ignoring harmless warnings."""
    for line in stderr.splitlines():
        if line.startswith("sudo:") and not any(warning in line for warning in _HARMLESS_SUDO):
            return line.strip()
    return ""


def kill_agent_processes(run: RunCommand, agent_user: str | None) -> None:
    """Best-effort cleanup after a timeout, where the timeout is the reported failure."""
    try:
        ensure_agent_cleanup(run, agent_user)
    except Exception:
        pass


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
) -> dict[str, str]:
    """Build the explicit environment the agent subprocess receives.

    The model provider key is deliberately absent: the agent holds it in its
    own OpenCode auth store, so it never crosses the sudo boundary (and never
    appears in the journal).
    """
    env = {
        "OPENCODE_CONFIG": config_path,
        # Global sources OpenCode can turn off: ~/.claude (CLAUDE.md, skills) and
        # external skill directories (#153).
        "OPENCODE_DISABLE_CLAUDE_CODE": "1",
        "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1",
    }
    env.update(_allowlisted_env(base_env, agent_user=agent_user, agent_home=agent_home))
    env.update(TEST_SETTINGS)
    return env


PLAYWRIGHT_BROWSERS_SUBPATH = Path(".cache") / "ms-playwright"
CONSOLE_ENV_NAMES = ("PATH", "HOME", "LANG")


def build_check_env(
    base_env: dict[str, str],
    *,
    agent_user: str | None,
    agent_home: str | None,
    area: Area | None = None,
) -> dict[str, str]:
    """Build the explicit environment the check runner receives.

    The check runner executes agent-written code, so it gets only the base
    allowlist plus the settings its area needs: never the model provider key,
    the GitHub token or any other secret. The console area needs Node, pnpm and
    Playwright only, plus ``CI=true`` so Playwright never reuses a server on
    port 3000 from another worktree.
    """
    env = _allowlisted_env(base_env, agent_user=agent_user, agent_home=agent_home)
    if area is not None and area.name == "console":
        env = {name: env[name] for name in CONSOLE_ENV_NAMES if name in env}
        env["CI"] = "true"
        home = env.get("HOME")
        if home:
            env["PLAYWRIGHT_BROWSERS_PATH"] = str(Path(home) / PLAYWRIGHT_BROWSERS_SUBPATH)
        return env
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
        base_env: dict[str, str] | None = None,
        config_home: str | None = None,
    ):
        self._run = run
        self.agent_user = agent_user
        self.agent_home = agent_home
        self.base_env = dict(base_env if base_env is not None else os.environ)
        # XDG_CONFIG_HOME for OpenCode: a factory-owned directory the agent can read
        # but not write, so nothing the agent runs can plant global config (#153).
        self.config_home = config_home

    def run(
        self,
        *,
        worktree: Path,
        model: str,
        prompt: str,
        timeout_seconds: int,
        config_path: str | None = None,
        config_content: str | None = None,
        disable_project_config: bool = False,
    ) -> AgentResult:
        """Run OpenCode once, then kill any agent process it left behind.

        ``config_content`` is passed inline: it ranks above the repo's
        ``opencode.json`` and ``.opencode/``, which an ``OPENCODE_CONFIG`` file does
        not. The reviewer also disables project config; the builder keeps it, because
        it needs the repo's AGENTS.md.
        """
        env = build_agent_env(
            self.base_env,
            config_path=config_path or str(worktree / OPENCODE_CONFIG_PATH),
            agent_user=self.agent_user,
            agent_home=self.agent_home,
        )
        if config_content is not None:
            del env["OPENCODE_CONFIG"]
            env["OPENCODE_CONFIG_CONTENT"] = config_content
        if disable_project_config:
            env["OPENCODE_DISABLE_PROJECT_CONFIG"] = "1"
        if self.config_home:
            env["XDG_CONFIG_HOME"] = self.config_home
        self.verify_home_is_clean()
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
            kill_agent_processes(self._run, self.agent_user)
            return AgentResult(exit_code=None, stdout="", stderr="", timed_out=True)
        # A normal exit can leave background processes (nohup, servers) that would
        # change files after the checks or the review; none may outlive the step.
        ensure_agent_cleanup(self._run, self.agent_user)
        return AgentResult(
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            timed_out=False,
        )

    def model_check(self, worktree: Path, model: str, *, config_content: str) -> None:
        """Ask ``model`` for a fixed token, as the reviewer runs, and fail if it does not answer.

        A model without a provider login makes OpenCode exit with no output at
        all, which the reviewer step used to report as a missing findings block.
        """
        result = self.run(
            worktree=worktree,
            model=model,
            prompt=MODEL_CHECK_PROMPT,
            timeout_seconds=MODEL_CHECK_TIMEOUT_SECONDS,
            config_content=config_content,
            disable_project_config=True,
        )
        if result.timed_out:
            raise AgentSandboxError(f"{model} gave no answer within {MODEL_CHECK_TIMEOUT_SECONDS}s")
        if MODEL_CHECK_TOKEN not in result.stdout:
            said = " ".join((result.stderr or result.stdout).split())[:300] or "no output"
            raise AgentSandboxError(f"{model} gave no answer (exit {result.exit_code}): {said}")

    def verify_home_is_clean(self) -> None:
        """Refuse to start OpenCode when the agent's home holds a config source.

        OpenCode loads ``~/.opencode`` (config, plugins) even with project config
        disabled, and ``~/.claude``/``~/.agents`` unless switched off. The agent owns
        its home, so any of them appearing means something planted config (#153).
        """
        if not self.agent_user:
            return
        home = self.agent_home or f"/home/{self.agent_user}"
        for name in AGENT_HOME_PLANTS:
            path = f"{home}/{name}"
            result = self._run(
                ["sudo", "-n", "-u", self.agent_user, "--", "/usr/bin/test", "-e", path],
                "/",
                timeout=60,
            )
            if result.exit_code == 0:
                raise AgentSandboxError(
                    f"{path} exists in the agent's home; OpenCode would load it as global "
                    "config. Review and remove it (see docs/factory.md), then rerun."
                )
            if result.exit_code != 1:
                raise AgentSandboxError(
                    f"could not check {path}: {result.stderr.strip() or result.exit_code}"
                )

    def ensure_clean(self) -> None:
        """Kill every agent process; raise if the cleanup cannot be trusted."""
        ensure_agent_cleanup(self._run, self.agent_user)

    def smoke_check(self, worktree: Path) -> None:
        """Start OpenCode once as the agent, with the real env, and fail if it cannot."""
        env = build_agent_env(
            self.base_env,
            config_path=str(worktree / OPENCODE_CONFIG_PATH),
            agent_user=self.agent_user,
            agent_home=self.agent_home,
        )
        if self.config_home:
            env["XDG_CONFIG_HOME"] = self.config_home
        argv: list[str] = [OPENCODE_BIN, "--version"]
        if self.agent_user:
            argv = sudo_argv(self.agent_user, argv, env)
        result = self._run(argv, str(worktree), timeout=120, env=env, replace_env=True)
        if result.exit_code != 0:
            raise AgentSandboxError(
                "OpenCode cannot start as the agent: "
                f"{result.stderr.strip() or result.stdout.strip() or result.exit_code}"
            )
