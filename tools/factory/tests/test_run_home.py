import json
import os
import stat

import pytest

from factory.run_home import (
    AGENT_AUTH_RELPATH,
    RunHomeError,
    RunHomes,
    validated_auth,
)
from factory.shell import CommandResult

API_AUTH = json.dumps(
    {"deepseek": {"type": "api", "key": "sk-1"}, "anthropic": {"type": "api", "key": "sk-2"}}
)


class RecordingRun:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, cwd, *, timeout, env=None, replace_env=False):
        self.calls.append(argv)
        if "/usr/bin/rm" in argv:
            import shutil

            shutil.rmtree(argv[-1], ignore_errors=True)
        return CommandResult(0, "", "")


def make_homes(tmp_path, auth=API_AUTH, run=None):
    homes_dir = tmp_path / "agent-homes"
    homes_dir.mkdir()
    auth_file = tmp_path / "agent-auth.json"
    if auth is not None:
        auth_file.write_text(auth)
    return RunHomes(
        homes_dir=homes_dir,
        auth_file=auth_file,
        agent_user="factory-agent",
        worktrees_dir=tmp_path / "worktrees",
        run=run or RecordingRun(),
    )


def test_a_run_home_is_fresh_and_carries_only_the_factory_auth_and_gitconfig(tmp_path):
    homes = make_homes(tmp_path)

    home = homes.create("builder")

    assert home.parent == tmp_path / "agent-homes"
    assert home.name.startswith("builder-")
    assert json.loads((home / AGENT_AUTH_RELPATH).read_text()) == json.loads(API_AUTH)
    gitconfig = (home / ".gitconfig").read_text()
    assert "[safe]" in gitconfig and str(tmp_path / "worktrees") + "/*" in gitconfig
    files = sorted(p.relative_to(home).as_posix() for p in home.rglob("*") if p.is_file())
    assert files == [".gitconfig", AGENT_AUTH_RELPATH]


def test_two_runs_never_share_a_home(tmp_path):
    homes = make_homes(tmp_path)

    assert homes.create("builder") != homes.create("builder")


def test_the_run_home_is_group_writable_and_its_auth_is_not_world_readable(tmp_path):
    home = make_homes(tmp_path).create("reviewer")

    assert stat.S_IMODE(os.stat(home).st_mode) == 0o2770
    assert stat.S_IMODE(os.stat(home / AGENT_AUTH_RELPATH).st_mode) == 0o640


def test_the_run_home_env_points_every_opencode_store_inside_it(tmp_path):
    homes = make_homes(tmp_path)
    home = homes.create("builder")

    env = homes.env(home, shared_home="/home/factory-agent")

    assert env["HOME"] == str(home)
    assert env["XDG_DATA_HOME"] == str(home / ".local" / "share")
    assert env["XDG_CACHE_HOME"] == str(home / ".cache")
    assert env["XDG_STATE_HOME"] == str(home / ".local" / "state")
    # Tool caches stay shared: OpenCode never reads them.
    assert env["UV_CACHE_DIR"] == "/home/factory-agent/.cache/uv"
    assert env["npm_config_store_dir"] == "/home/factory-agent/.local/share/pnpm/store"
    assert env["PLAYWRIGHT_BROWSERS_PATH"] == "/home/factory-agent/.cache/ms-playwright"


def test_a_run_home_is_removed_as_the_agent(tmp_path):
    run = RecordingRun()
    homes = make_homes(tmp_path, run=run)
    home = homes.create("builder")

    homes.remove(home)

    assert not home.exists()
    assert run.calls[-1] == [
        "sudo",
        "-n",
        "-u",
        "factory-agent",
        "--",
        "/usr/bin/rm",
        "-rf",
        str(home),
    ]


def test_remove_refuses_a_path_outside_the_homes_directory(tmp_path):
    homes = make_homes(tmp_path)

    with pytest.raises(RunHomeError, match="outside"):
        homes.remove(tmp_path / "worktrees" / "nf-7")


def test_leftovers_from_a_killed_run_are_listed(tmp_path):
    homes = make_homes(tmp_path)
    old = homes.create("builder")

    assert homes.leftovers() == [old]


@pytest.mark.parametrize(
    "auth, reason",
    [
        ('{"x": {"type": "wellknown", "key": "k", "token": "t"}}', "only api keys"),
        ('{"x": {"type": "oauth", "refresh": "r"}}', "only api keys"),
        ('{"x": {"type": "api", "key": "k", "url": "https://evil"}}', "unexpected field"),
        ("[]", "not a JSON object"),
        ("{not json", "not valid JSON"),
        ("{}", "no provider"),
    ],
)
def test_the_auth_copy_accepts_only_api_keys(auth, reason):
    """A wellknown entry makes OpenCode fetch and merge a remote config (#158)."""
    with pytest.raises(RunHomeError, match=reason):
        validated_auth(auth)


def test_a_missing_auth_file_names_the_install_step(tmp_path):
    homes = make_homes(tmp_path, auth=None)

    with pytest.raises(RunHomeError, match="agent-auth.json.*step 8"):
        homes.create("builder")
