from factory.runner import STRIPPED_ENV_VARS, AgentRunner
from factory.shell import CommandResult


class RecordingRun:
    def __init__(self, result=None):
        self.result = result or CommandResult(exit_code=0, stdout="", stderr="")
        self.calls = []

    def __call__(self, argv, cwd, *, timeout, env):
        self.calls.append((argv, cwd, env))
        return self.result


def test_run_strips_github_credentials_from_env(tmp_path):
    recorder = RecordingRun()
    runner = AgentRunner(run=recorder)
    runner.run(worktree=tmp_path, model="m", prompt="p", timeout_seconds=60)

    argv, cwd, env = recorder.calls[0]
    assert argv[:3] == ["opencode", "run", "--model"]
    for var in STRIPPED_ENV_VARS:
        assert env[var] is None
    assert env["OPENCODE_CONFIG"] == str(tmp_path / "tools/factory/opencode.factory.json")


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


def test_run_as_agent_user_prefixes_sudo(tmp_path):
    recorder = RecordingRun()
    runner = AgentRunner(run=recorder, agent_user="factory-agent")
    runner.run(worktree=tmp_path, model="m", prompt="p", timeout_seconds=60)

    argv, _cwd, _env = recorder.calls[0]
    assert argv[:5] == ["sudo", "-u", "factory-agent", "--", "opencode"]


def test_run_marks_timeout(tmp_path):
    from factory.shell import CommandTimeout

    def timed_out(argv, cwd, *, timeout, env):
        raise CommandTimeout("slow")

    runner = AgentRunner(run=timed_out)
    result = runner.run(worktree=tmp_path, model="m", prompt="p", timeout_seconds=60)
    assert result.timed_out is True
