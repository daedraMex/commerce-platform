from pathlib import Path

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
    def __init__(self, result=None):
        self.result = result or CommandResult(exit_code=0, stdout="", stderr="")
        self.calls = []

    def __call__(self, argv, cwd, *, timeout, env=None, replace_env=False):
        self.calls.append((argv, cwd, env, replace_env))
        return self.result


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

    argv, _cwd, env, replace_env = recorder.calls[0]
    assert argv == [
        "sudo",
        "-n",
        "--preserve-env=OPENCODE_CONFIG,PATH,HOME,LANG,DATABASE_URL,"
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
        if len(calls) == 1:
            raise CommandTimeout("slow")
        return CommandResult(exit_code=0, stdout="", stderr="")

    runner = AgentRunner(run=run, agent_user="factory-agent", base_env={"PATH": "/usr/bin"})
    result = runner.run(worktree=tmp_path, model="m", prompt="p", timeout_seconds=60)

    assert result.timed_out is True
    assert calls[1] == (
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
