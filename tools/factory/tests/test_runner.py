from pathlib import Path

import pytest

from factory.areas import CONSOLE
from factory.runner import (
    TEST_SETTINGS,
    AgentRunner,
    build_agent_env,
    build_check_env,
    sudo_argv,
    truncate_check_output,
)
from factory.shell import CommandResult


class RecordingRun:
    """Answer like the machine: `test -e` finds nothing and pkill has nothing left (1)."""

    def __init__(self, result=None):
        self.result = result or CommandResult(exit_code=0, stdout="", stderr="")
        self.calls = []

    def __call__(self, argv, cwd, *, timeout, env=None, replace_env=False):
        self.calls.append((argv, cwd, env, replace_env))
        if "/usr/bin/test" in argv or "/usr/bin/pkill" in argv:
            return CommandResult(exit_code=1, stdout="", stderr="")
        return self.result

    def opencode_call(self):
        return next(call for call in self.calls if "/usr/bin/opencode" in call[0])


def test_build_agent_env_allowlists_only_known_vars():
    base = {
        "PATH": "/usr/bin",
        "HOME": "/home/factory",
        "LANG": "en_US.UTF-8",
        "DATABASE_URL": "postgres://db",
        "DEEPSEEK_API_KEY": "dk-123",
        "GH_TOKEN": "secret",
        "TELEGRAM_TOKEN": "secret",
    }
    env = build_agent_env(
        base,
        config_path="/work/tools/factory/opencode.factory.json",
        agent_user="factory-agent",
        agent_home="/home/factory-agent",
    )
    assert env["OPENCODE_CONFIG"] == "/work/tools/factory/opencode.factory.json"
    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/home/factory-agent"
    assert env["LANG"] == "en_US.UTF-8"
    assert env["DATABASE_URL"] == "postgres://db"
    assert "DEEPSEEK_API_KEY" not in env
    assert "GH_TOKEN" not in env
    assert "TELEGRAM_TOKEN" not in env
    assert {name: env[name] for name in TEST_SETTINGS} == TEST_SETTINGS
    assert "FACTORY_TELEGRAM_BOT_TOKEN" not in env
    assert "XOLO_BOT_PRIVATE_KEY" not in env


def test_build_agent_env_defaults_home_to_agent_user():
    env = build_agent_env(
        {"HOME": "/home/factory", "PATH": "/usr/bin"},
        config_path="c",
        agent_user="factory-agent",
        agent_home=None,
    )
    assert env["HOME"] == "/home/factory-agent"


def test_build_check_env_has_only_the_base_allowlist_and_test_settings():
    env = build_check_env(
        {
            "PATH": "/usr/bin",
            "HOME": "/home/factory",
            "LANG": "C",
            "DATABASE_URL": "postgres://db",
            "DEEPSEEK_API_KEY": "dk-123",
            "GH_TOKEN": "secret",
            "OPENCODE_CONFIG": "/work/opencode.json",
            "FACTORY_TELEGRAM_BOT_TOKEN": "tg-secret",
            "XOLO_BOT_PRIVATE_KEY": "-----BEGIN PRIVATE KEY-----",
        },
        agent_user="factory-agent",
        agent_home="/home/factory-agent",
    )
    assert env == {
        "PATH": "/usr/bin",
        "HOME": "/home/factory-agent",
        "LANG": "C",
        "DATABASE_URL": "postgres://db",
        **TEST_SETTINGS,
    }


def test_console_check_env_adds_ci_and_the_playwright_browser_path():
    env = build_check_env(
        {
            "PATH": "/usr/local/bin:/usr/bin",
            "HOME": "/home/factory",
            "LANG": "C",
            "DATABASE_URL": "postgres://db",
            "DEEPSEEK_API_KEY": "dk-123",
        },
        agent_user="factory-agent",
        agent_home="/home/factory-agent",
        area=CONSOLE,
    )

    assert env == {
        "PATH": "/usr/local/bin:/usr/bin",
        "HOME": "/home/factory-agent",
        "LANG": "C",
        "CI": "true",
        "PLAYWRIGHT_BROWSERS_PATH": "/home/factory-agent/.cache/ms-playwright",
    }


def test_backend_check_env_does_not_set_ci_or_the_browser_path():
    env = build_check_env(
        {"PATH": "/usr/bin", "HOME": "/home/factory", "LANG": "C"},
        agent_user="factory-agent",
        agent_home="/home/factory-agent",
    )

    assert "CI" not in env
    assert "PLAYWRIGHT_BROWSERS_PATH" not in env
    assert env["PYTEST_ADDOPTS"] == "-p no:cacheprovider"


def test_check_env_uses_the_values_matching_ci():
    assert TEST_SETTINGS == {
        "SECRET_KEY": "ci-not-a-secret-change-me-0123456789",
        "DEBUG": "False",
        "ALLOWED_HOSTS": "localhost,127.0.0.1",
        "REDIS_URL": "redis://localhost:6379/0",
        "PYTEST_ADDOPTS": "-p no:cacheprovider",
    }


CI_WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"


def backend_job_env(text: str) -> dict[str, str]:
    """Read the ``env:`` mapping of the backend job from the CI workflow."""
    lines = text.splitlines()
    backend = next(i for i, line in enumerate(lines) if line.strip() == "backend:")
    env_start = next(i for i in range(backend + 1, len(lines)) if lines[i] == "    env:")
    env: dict[str, str] = {}
    for line in lines[env_start + 1 :]:
        if not line.startswith("      "):
            break
        key, separator, value = line.strip().partition(":")
        if separator:
            env[key] = value.strip().strip('"').strip("'")
    return env


def test_test_settings_match_the_ci_backend_job():
    env = backend_job_env(CI_WORKFLOW.read_text())

    assert {key: env[key] for key in TEST_SETTINGS} == TEST_SETTINGS


def test_truncate_check_output_keeps_the_tail():
    output = "x" * 50 + "y" * 50
    truncated = truncate_check_output(output, limit=20)
    assert truncated.endswith("y" * 20)
    assert "truncated" in truncated
    assert "x" not in truncated


def test_truncate_check_output_leaves_short_output_alone():
    assert truncate_check_output("ok", limit=20) == "ok"


def test_run_uses_non_interactive_sudo_and_full_path(tmp_path):
    recorder = RecordingRun()
    runner = AgentRunner(
        run=recorder,
        agent_user="factory-agent",
        base_env={
            "PATH": "/usr/bin",
            "HOME": "/home/factory",
            "LANG": "C",
            "DATABASE_URL": "postgres://db",
            "DEEPSEEK_API_KEY": "dk",
            "GH_TOKEN": "nope",
        },
    )
    runner.run(worktree=tmp_path, model="m", prompt="p", timeout_seconds=60)

    argv, _cwd, env, replace_env = recorder.opencode_call()
    assert argv == [
        "sudo",
        "-n",
        "--preserve-env=OPENCODE_CONFIG,OPENCODE_DISABLE_CLAUDE_CODE,"
        "OPENCODE_DISABLE_EXTERNAL_SKILLS,PATH,HOME,LANG,DATABASE_URL,"
        "SECRET_KEY,DEBUG,ALLOWED_HOSTS,REDIS_URL,PYTEST_ADDOPTS",
        "-u",
        "factory-agent",
        "--",
        "/usr/bin/opencode",
        "run",
        "--model",
        "m",
        "p",
    ]
    assert replace_env is True
    assert "GH_TOKEN" not in env
    assert "DEEPSEEK_API_KEY" not in env
    assert env["OPENCODE_CONFIG"].endswith("tools/factory/opencode.factory.json")


def test_sudo_argv_preserves_only_the_named_env():
    argv = sudo_argv(
        "factory-agent",
        ["/usr/bin/opencode"],
        {"PATH": "/usr/bin", "DATABASE_URL": "postgres://db"},
    )
    assert argv == [
        "sudo",
        "-n",
        "--preserve-env=PATH,DATABASE_URL",
        "-u",
        "factory-agent",
        "--",
        "/usr/bin/opencode",
    ]


def test_run_passes_model_and_prompt(tmp_path):
    recorder = RecordingRun()
    runner = AgentRunner(run=recorder)
    runner.run(
        worktree=tmp_path,
        model="deepseek/deepseek-flash",
        prompt="implement ticket",
        timeout_seconds=60,
    )

    argv, _cwd, _env, _replace_env = recorder.calls[0]
    assert "/usr/bin/opencode" in argv
    assert "deepseek/deepseek-flash" in argv
    assert "implement ticket" in argv


def test_run_marks_timeout(tmp_path):
    from factory.shell import CommandTimeout

    def timed_out(argv, cwd, *, timeout, env=None, replace_env=False):
        raise CommandTimeout("slow")

    runner = AgentRunner(run=timed_out)
    result = runner.run(worktree=tmp_path, model="m", prompt="p", timeout_seconds=60)
    assert result.timed_out is True


def test_run_timeout_cleans_up_every_agent_process(tmp_path):
    from factory.shell import CommandTimeout

    calls = []

    def run(argv, cwd, *, timeout, env=None, replace_env=False):
        calls.append((argv, cwd, env, replace_env))
        if "/usr/bin/opencode" in argv:
            raise CommandTimeout("slow")
        return CommandResult(exit_code=1, stdout="", stderr="")

    runner = AgentRunner(run=run, agent_user="factory-agent", base_env={"PATH": "/usr/bin"})
    result = runner.run(worktree=tmp_path, model="m", prompt="p", timeout_seconds=60)

    assert result.timed_out is True
    opencode = next(i for i, call in enumerate(calls) if "/usr/bin/opencode" in call[0])
    assert calls[opencode + 1] == (
        [
            "sudo",
            "-n",
            "-u",
            "factory-agent",
            "/usr/bin/pkill",
            "-KILL",
            "-u",
            "factory-agent",
        ],
        "/",
        None,
        False,
    )


def test_runner_uses_an_explicit_config_path_when_given(tmp_path):
    run = RecordingRun()
    runner = AgentRunner(run=run, agent_user=None, base_env={"PATH": "/usr/bin"})

    runner.run(
        worktree=tmp_path,
        model="m",
        prompt="p",
        timeout_seconds=10,
        config_path=str(tmp_path / "tools/factory/opencode.reviewer.json"),
    )

    env = run.calls[0][2]
    assert env["OPENCODE_CONFIG"] == str(tmp_path / "tools/factory/opencode.reviewer.json")


def test_runner_passes_inline_config_above_project_config(tmp_path):
    run = RecordingRun()
    runner = AgentRunner(run=run, agent_user=None, base_env={"PATH": "/usr/bin"})

    runner.run(
        worktree=tmp_path,
        model="m",
        prompt="p",
        timeout_seconds=10,
        config_content='{"permission": {"edit": {"*": "deny"}}}',
        disable_project_config=True,
    )

    env = run.calls[0][2]
    assert env["OPENCODE_CONFIG_CONTENT"] == '{"permission": {"edit": {"*": "deny"}}}'
    assert env["OPENCODE_DISABLE_PROJECT_CONFIG"] == "1"
    assert "OPENCODE_CONFIG" not in env


def test_builder_config_is_inline_but_keeps_the_project_config(tmp_path):
    run = RecordingRun()
    runner = AgentRunner(run=run, agent_user=None, base_env={"PATH": "/usr/bin"})

    runner.run(
        worktree=tmp_path,
        model="m",
        prompt="p",
        timeout_seconds=10,
        config_content='{"permission": {"edit": {"AGENTS.md": "deny"}}}',
        disable_project_config=False,
    )

    env = run.calls[0][2]
    assert env["OPENCODE_CONFIG_CONTENT"] == '{"permission": {"edit": {"AGENTS.md": "deny"}}}'
    assert "OPENCODE_DISABLE_PROJECT_CONFIG" not in env
    assert "OPENCODE_CONFIG" not in env


def test_every_opencode_run_reads_global_config_from_the_factory_owned_dir(tmp_path):
    run = RecordingRun()
    runner = AgentRunner(
        run=run,
        agent_user=None,
        base_env={"PATH": "/usr/bin"},
        config_home="/srv/factory/agent-config",
    )

    runner.run(worktree=tmp_path, model="m", prompt="p", timeout_seconds=10)

    assert run.calls[0][2]["XDG_CONFIG_HOME"] == "/srv/factory/agent-config"


def test_a_normal_run_still_kills_every_agent_process_left_behind(tmp_path):
    run = RecordingRun()
    runner = AgentRunner(run=run, agent_user="factory-agent", base_env={"PATH": "/usr/bin"})

    result = runner.run(worktree=tmp_path, model="m", prompt="p", timeout_seconds=10)

    assert result.timed_out is False
    assert run.calls[-1][0] == [
        "sudo",
        "-n",
        "-u",
        "factory-agent",
        "/usr/bin/pkill",
        "-KILL",
        "-u",
        "factory-agent",
    ]


class ScriptedRun:
    """Answer each argv by a rule; record every call."""

    def __init__(self, rule):
        self.rule = rule
        self.calls = []

    def __call__(self, argv, cwd, *, timeout, env=None, replace_env=False):
        self.calls.append((argv, cwd, env, replace_env))
        return self.rule(argv)


PKILL = ["sudo", "-n", "-u", "factory-agent", "/usr/bin/pkill", "-KILL", "-u", "factory-agent"]


def test_every_run_disables_claude_code_and_external_skills(tmp_path):
    run = RecordingRun()
    AgentRunner(run=run, agent_user=None, base_env={"PATH": "/usr/bin"}).run(
        worktree=tmp_path, model="m", prompt="p", timeout_seconds=10
    )

    env = run.calls[0][2]
    assert env["OPENCODE_DISABLE_CLAUDE_CODE"] == "1"
    assert env["OPENCODE_DISABLE_EXTERNAL_SKILLS"] == "1"


def test_a_planted_dot_opencode_in_the_agent_home_stops_the_run(tmp_path):
    from factory.runner import AgentSandboxError

    def rule(argv):
        if argv[-2:] == ["-e", "/home/factory-agent/.opencode"]:
            return CommandResult(0, "", "")
        if "/usr/bin/test" in argv:
            return CommandResult(1, "", "")
        return CommandResult(1, "", "")

    run = ScriptedRun(rule)
    runner = AgentRunner(
        run=run, agent_user="factory-agent", agent_home="/home/factory-agent", base_env={}
    )

    with pytest.raises(AgentSandboxError, match=r"/home/factory-agent/\.opencode"):
        runner.run(worktree=tmp_path, model="m", prompt="p", timeout_seconds=10)
    assert not any("/usr/bin/opencode" in call[0] for call in run.calls)


def test_cleanup_repeats_until_nothing_is_left():
    from factory.runner import ensure_agent_cleanup

    answers = iter([0, 0, 1])
    run = ScriptedRun(lambda argv: CommandResult(next(answers), "", ""))

    ensure_agent_cleanup(run, "factory-agent")

    assert [call[0] for call in run.calls] == [PKILL, PKILL, PKILL]


def test_cleanup_that_sudo_refuses_fails_loudly():
    from factory.runner import AgentSandboxError, ensure_agent_cleanup

    run = ScriptedRun(lambda argv: CommandResult(1, "", "sudo: a password is required"))

    with pytest.raises(AgentSandboxError, match="password is required"):
        ensure_agent_cleanup(run, "factory-agent")


def test_cleanup_with_an_unexpected_exit_fails_loudly():
    from factory.runner import AgentSandboxError, ensure_agent_cleanup

    run = ScriptedRun(lambda argv: CommandResult(3, "", "pkill: fatal"))

    with pytest.raises(AgentSandboxError, match="pkill: fatal"):
        ensure_agent_cleanup(run, "factory-agent")


def test_smoke_check_starts_opencode_with_the_agent_env(tmp_path):
    from factory.runner import AgentSandboxError

    run = ScriptedRun(
        lambda argv: (
            CommandResult(1, "", "EACCES: mkdir '/srv/factory/agent-config/opencode'")
            if "--version" in argv
            else CommandResult(1, "", "")
        )
    )
    runner = AgentRunner(
        run=run,
        agent_user="factory-agent",
        agent_home="/home/factory-agent",
        base_env={},
        config_home="/srv/factory/agent-config",
    )

    with pytest.raises(AgentSandboxError, match="EACCES"):
        runner.smoke_check(tmp_path)
    version_call = next(call for call in run.calls if "--version" in call[0])
    assert version_call[2]["XDG_CONFIG_HOME"] == "/srv/factory/agent-config"


def test_cleanup_that_keeps_finding_processes_fails_loudly():
    from factory.runner import AgentSandboxError, ensure_agent_cleanup

    run = ScriptedRun(lambda argv: CommandResult(0, "", ""))

    with pytest.raises(AgentSandboxError, match="still running"):
        ensure_agent_cleanup(run, "factory-agent")


def test_a_harmless_sudo_warning_is_not_a_cleanup_failure():
    from factory.runner import ensure_agent_cleanup

    run = ScriptedRun(
        lambda argv: CommandResult(1, "", "sudo: unable to resolve host pop-os: Name or service")
    )

    ensure_agent_cleanup(run, "factory-agent")


def test_cleanup_whose_sudo_wrapper_is_killed_checks_again():
    # pkill -KILL -u factory-agent can take down the sudo process running it while it
    # kills live agent processes; sudo then reports -9. That means "killed something".
    from factory.runner import ensure_agent_cleanup

    answers = iter([-9, 1])
    run = ScriptedRun(lambda argv: CommandResult(next(answers), "", ""))

    ensure_agent_cleanup(run, "factory-agent")

    assert len(run.calls) == 2


def test_cleanup_that_is_killed_on_every_pass_fails_loudly():
    from factory.runner import AgentSandboxError, ensure_agent_cleanup

    run = ScriptedRun(lambda argv: CommandResult(137, "", ""))

    with pytest.raises(AgentSandboxError, match="still running"):
        ensure_agent_cleanup(run, "factory-agent")


def _model_check_runner(answer):
    def rule(argv):
        if "run" in argv and "--model" in argv:
            return answer
        return CommandResult(1, "", "")  # test -e: no plant; pkill: nothing left

    run = ScriptedRun(rule)
    runner = AgentRunner(
        run=run,
        agent_user="factory-agent",
        agent_home="/home/factory-agent",
        base_env={},
        config_home="/srv/factory/agent-config",
    )
    return runner, run


def test_model_check_asks_the_model_for_a_token_with_the_read_only_config(tmp_path):
    from factory.runner import MODEL_CHECK_TOKEN

    runner, run = _model_check_runner(CommandResult(0, f"> build\n\n{MODEL_CHECK_TOKEN}\n", ""))

    runner.model_check(tmp_path, "anthropic/claude-sonnet-5-5", config_content='{"a": 1}')

    argv, cwd, env, _ = next(call for call in run.calls if "run" in call[0])
    assert argv[argv.index("--model") + 1] == "anthropic/claude-sonnet-5-5"
    assert cwd == str(tmp_path)
    assert env["OPENCODE_CONFIG_CONTENT"] == '{"a": 1}'
    assert env["OPENCODE_DISABLE_PROJECT_CONFIG"] == "1"
    assert env["XDG_CONFIG_HOME"] == "/srv/factory/agent-config"


def test_model_check_fails_naming_the_model_when_it_gives_no_output(tmp_path):
    """The reviewer ran without its provider login and printed nothing (#202)."""
    from factory.runner import AgentSandboxError

    runner, _ = _model_check_runner(CommandResult(0, "", ""))

    with pytest.raises(
        AgentSandboxError, match=r"anthropic/claude-sonnet-5-5 gave no answer \(exit 0\)"
    ):
        runner.model_check(tmp_path, "anthropic/claude-sonnet-5-5", config_content="{}")


def test_model_check_reports_what_the_model_said_instead(tmp_path):
    from factory.runner import AgentSandboxError

    runner, _ = _model_check_runner(CommandResult(1, "", "ProviderAuthError: no credentials"))

    with pytest.raises(AgentSandboxError, match="exit 1.*ProviderAuthError"):
        runner.model_check(tmp_path, "anthropic/claude-sonnet-5-5", config_content="{}")


def test_an_interrupted_agent_run_kills_every_agent_process_before_it_propagates(tmp_path):
    """Ctrl+C reaches only the factory; the agent's own processes need the pkill (#197)."""
    calls = []

    def run(argv, cwd, *, timeout, env=None, replace_env=False):
        calls.append(argv)
        if "/usr/bin/opencode" in argv:
            raise KeyboardInterrupt
        return CommandResult(exit_code=1, stdout="", stderr="")

    runner = AgentRunner(run=run, agent_user="factory-agent", base_env={"PATH": "/usr/bin"})

    with pytest.raises(KeyboardInterrupt):
        runner.run(worktree=tmp_path, model="m", prompt="p", timeout_seconds=60)

    opencode = next(i for i, argv in enumerate(calls) if "/usr/bin/opencode" in argv)
    assert "/usr/bin/pkill" in calls[opencode + 1]


class FakeRunHomes:
    def __init__(self, tmp_path, create_error=None):
        self.tmp_path = tmp_path
        self.created = []
        self.removed = []
        self.create_error = create_error

    def create(self, label):
        if self.create_error is not None:
            raise self.create_error
        home = self.tmp_path / f"{label}-{len(self.created)}"
        home.mkdir()
        self.created.append(home)
        return home

    def env(self, home, *, shared_home):
        return {
            "HOME": str(home),
            "XDG_DATA_HOME": str(home / ".local/share"),
            "UV_CACHE_DIR": f"{shared_home}/.cache/uv",
        }

    def remove(self, home):
        self.removed.append(home)


def _homes_runner(tmp_path, homes, answer=None, raise_on_opencode=None):
    calls = []

    def run(argv, cwd, *, timeout, env=None, replace_env=False):
        calls.append((argv, env))
        if "/usr/bin/opencode" in argv:
            if raise_on_opencode is not None:
                raise raise_on_opencode
            return answer or CommandResult(0, "done", "")
        return CommandResult(1, "", "")

    runner = AgentRunner(
        run=run,
        agent_user="factory-agent",
        agent_home="/home/factory-agent",
        base_env={"PATH": "/usr/bin"},
        run_homes=homes,
    )
    return runner, calls


def test_every_opencode_run_gets_a_fresh_home_that_is_removed_after(tmp_path):
    """Nothing a run writes in its home is loaded by a later one (#158)."""
    homes = FakeRunHomes(tmp_path)
    runner, calls = _homes_runner(tmp_path, homes)

    runner.run(worktree=tmp_path, model="m", prompt="p", timeout_seconds=60)
    runner.run(
        worktree=tmp_path, model="s", prompt="r", timeout_seconds=60, disable_project_config=True
    )

    assert [home.name for home in homes.created] == ["builder-0", "reviewer-1"]
    assert homes.removed == homes.created
    envs = [env for argv, env in calls if "/usr/bin/opencode" in argv]
    assert envs[0]["HOME"] == str(homes.created[0])
    assert envs[0]["XDG_DATA_HOME"] == str(homes.created[0] / ".local/share")
    assert envs[0]["UV_CACHE_DIR"] == "/home/factory-agent/.cache/uv"
    opencode_argv = next(argv for argv, _ in calls if "/usr/bin/opencode" in argv)
    assert "XDG_DATA_HOME" in opencode_argv[2]  # passed through sudo --preserve-env


def test_the_run_home_is_removed_after_a_timeout_and_after_an_interrupt(tmp_path):
    from factory.shell import CommandTimeout

    for error in (CommandTimeout("slow"), KeyboardInterrupt()):
        homes = FakeRunHomes(tmp_path / type(error).__name__)
        (tmp_path / type(error).__name__).mkdir()
        runner, _ = _homes_runner(tmp_path, homes, raise_on_opencode=error)
        try:
            runner.run(worktree=tmp_path, model="m", prompt="p", timeout_seconds=60)
        except KeyboardInterrupt:
            pass
        assert homes.removed == homes.created and len(homes.created) == 1


def test_a_run_home_that_cannot_be_made_stops_before_opencode(tmp_path):
    from factory.run_home import RunHomeError

    homes = FakeRunHomes(tmp_path, create_error=RunHomeError("agent-auth.json is missing"))
    runner, calls = _homes_runner(tmp_path, homes)

    with pytest.raises(RunHomeError, match="agent-auth.json"):
        runner.run(worktree=tmp_path, model="m", prompt="p", timeout_seconds=60)

    assert not any("/usr/bin/opencode" in argv for argv, _ in calls)
