from factory.runner import AgentRunner, build_agent_env
from factory.shell import CommandResult


class RecordingRun:
    def __init__(self, result=None):
        self.result = result or CommandResult(exit_code=0, stdout="", stderr="")
        self.calls = []

    def __call__(self, argv, cwd, *, timeout, env=None):
        self.calls.append((argv, cwd, env))
        return self.result


def _env_from_argv(argv):
    start = argv.index("env") + 1
    end = argv.index("opencode")
    env = {}
    for item in argv[start:end]:
        key, _, value = item.partition("=")
        env[key] = value
    return env


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
        provider_vars=("DEEPSEEK_API_KEY",),
    )
    assert env["OPENCODE_CONFIG"] == "/work/tools/factory/opencode.factory.json"
    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/home/factory-agent"
    assert env["LANG"] == "en_US.UTF-8"
    assert env["DATABASE_URL"] == "postgres://db"
    assert env["DEEPSEEK_API_KEY"] == "dk-123"
    assert "GH_TOKEN" not in env
    assert "TELEGRAM_TOKEN" not in env


def test_build_agent_env_defaults_home_to_agent_user():
    env = build_agent_env(
        {"HOME": "/home/factory", "PATH": "/usr/bin"},
        config_path="c",
        agent_user="factory-agent",
        agent_home=None,
        provider_vars=(),
    )
    assert env["HOME"] == "/home/factory-agent"


def test_run_uses_env_allowlist_in_argv(tmp_path):
    recorder = RecordingRun()
    runner = AgentRunner(
        run=recorder,
        agent_user="factory-agent",
        provider_env_vars=("DEEPSEEK_API_KEY",),
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

    argv, _cwd, env = recorder.calls[0]
    assert argv[:5] == ["sudo", "-u", "factory-agent", "--", "env"]
    allowed = _env_from_argv(argv)
    assert "GH_TOKEN" not in allowed
    assert allowed["DEEPSEEK_API_KEY"] == "dk"
    assert allowed["OPENCODE_CONFIG"].endswith("tools/factory/opencode.factory.json")
    assert env is None


def test_run_passes_model_and_prompt(tmp_path):
    recorder = RecordingRun()
    runner = AgentRunner(run=recorder)
    runner.run(
        worktree=tmp_path,
        model="deepseek/deepseek-flash",
        prompt="implement ticket",
        timeout_seconds=60,
    )

    argv, _cwd, _env = recorder.calls[0]
    assert "deepseek/deepseek-flash" in argv
    assert "implement ticket" in argv


def test_run_marks_timeout(tmp_path):
    from factory.shell import CommandTimeout

    def timed_out(argv, cwd, *, timeout, env=None):
        raise CommandTimeout("slow")

    runner = AgentRunner(run=timed_out)
    result = runner.run(worktree=tmp_path, model="m", prompt="p", timeout_seconds=60)
    assert result.timed_out is True
