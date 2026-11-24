from pathlib import Path

from factory.self_update import (
    REEXEC_ENV,
    SelfUpdate,
)
from factory.shell import CommandResult

REPO = Path("/srv/factory/repo")
TOOLS = REPO / "tools" / "factory"
OLD = "a" * 40
NEW = "b" * 40


class Machine:
    """Answer git and uv like the factory checkout would."""

    def __init__(
        self,
        *,
        head=OLD,
        target=NEW,
        branch="main",
        dirty="",
        ancestor=True,
        merge_ok=True,
        sync_ok=True,
        fetch_ok=True,
    ):
        self.head, self.target, self.branch, self.dirty = head, target, branch, dirty
        self.ancestor, self.merge_ok, self.sync_ok, self.fetch_ok = (
            ancestor,
            merge_ok,
            sync_ok,
            fetch_ok,
        )
        self.calls = []

    def __call__(self, argv, cwd, *, timeout, env=None, replace_env=False):
        self.calls.append((argv, cwd))
        ok, fail = CommandResult(0, "", ""), CommandResult(1, "", "boom")
        if argv[:2] == ["git", "fetch"]:
            return ok if self.fetch_ok else CommandResult(1, "", "network down")
        if argv == ["git", "rev-parse", "HEAD"]:
            return CommandResult(0, self.head + "\n", "")
        if argv == ["git", "rev-parse", "origin/main"]:
            return CommandResult(0, self.target + "\n", "")
        if argv == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return CommandResult(0, self.branch + "\n", "")
        if argv[:3] == ["git", "status", "--porcelain"]:
            return CommandResult(0, self.dirty, "")
        if argv[:3] == ["git", "merge-base", "--is-ancestor"]:
            return ok if self.ancestor else fail
        if argv[:3] == ["git", "merge", "--ff-only"]:
            if self.merge_ok:
                self.head = self.target
                return ok
            return CommandResult(1, "", "Not possible to fast-forward")
        if argv[:2] == ["uv", "sync"]:
            return ok if self.sync_ok else CommandResult(1, "", "resolution failed")
        raise AssertionError(f"unexpected {argv}")

    def ran(self, prefix):
        return [argv for argv, _ in self.calls if argv[: len(prefix)] == prefix]


def make(machine, env=None):
    execs = []
    updater = SelfUpdate(
        repo_dir=REPO,
        tools_dir=TOOLS,
        run=machine,
        env=env if env is not None else {},
        execv=lambda path, argv: execs.append((path, argv)),
        command=[
            "/srv/factory/repo/tools/factory/.venv/bin/python",
            "-m",
            "factory.main",
            "preflight",
        ],
    )
    return updater, execs


def test_a_clean_main_behind_origin_fast_forwards_syncs_and_reexecs():
    """On 2026-11-24 the checkout ran #190 code, 48 commits behind (#215)."""
    machine = Machine()
    env = {}
    updater, execs = make(machine, env)

    outcome = updater.run()

    assert outcome.status == "updated"
    assert machine.ran(["git", "merge", "--ff-only"]) == [
        ["git", "merge", "--ff-only", "origin/main"]
    ]
    sync = [(argv, cwd) for argv, cwd in machine.calls if argv[:2] == ["uv", "sync"]]
    # --locked: a stale uv.lock fails the sync instead of being rewritten, which
    # would leave "local changes" and stop every later run.
    assert sync == [(["uv", "sync", "--locked", "--quiet"], str(TOOLS))]
    python = "/srv/factory/repo/tools/factory/.venv/bin/python"
    assert execs == [(python, [python, "-m", "factory.main", "preflight"])]
    assert env[REEXEC_ENV] == NEW


def test_the_reexecuted_run_does_not_update_again():
    machine = Machine(head=NEW, target=NEW)
    updater, execs = make(machine, env={REEXEC_ENV: NEW})

    outcome = updater.run()

    assert outcome.status == "current"
    assert outcome.head == NEW
    assert execs == []
    assert machine.ran(["git", "fetch"]) == []  # the first run just fetched


def test_a_current_checkout_changes_nothing():
    machine = Machine(head=NEW, target=NEW)
    updater, execs = make(machine)

    outcome = updater.run()

    assert outcome.status == "current"
    assert machine.ran(["git", "merge"]) == []
    assert machine.ran(["uv", "sync"]) == []
    assert execs == []


def test_local_changes_block_the_update_and_touch_nothing():
    machine = Machine(dirty=" M tools/factory/src/factory/main.py\n")
    updater, execs = make(machine)

    outcome = updater.run()

    assert outcome.status == "blocked"
    assert "local changes" in outcome.reason
    assert OLD[:7] in outcome.reason and NEW[:7] in outcome.reason
    assert machine.ran(["git", "merge"]) == [] and execs == []


def test_another_branch_blocks_the_update():
    machine = Machine(branch="hotfix")
    outcome = make(machine)[0].run()

    assert outcome.status == "blocked"
    assert "not on main (on hotfix)" in outcome.reason
    assert machine.ran(["git", "merge"]) == []


def test_a_diverged_checkout_blocks_the_update():
    machine = Machine(ancestor=False)
    outcome = make(machine)[0].run()

    assert outcome.status == "blocked"
    assert "diverged" in outcome.reason
    assert machine.ran(["git", "merge"]) == []


def test_a_failed_sync_blocks_and_does_not_reexec():
    machine = Machine(sync_ok=False)
    updater, execs = make(machine)

    outcome = updater.run()

    assert outcome.status == "blocked"
    assert "uv sync failed" in outcome.reason and "resolution failed" in outcome.reason
    assert execs == []


def test_a_failed_fetch_blocks_the_run_and_still_names_the_commit():
    outcome = make(Machine(fetch_ok=False))[0].run()

    assert outcome.status == "blocked"
    assert "network down" in outcome.reason
    assert outcome.head == OLD


def test_an_update_is_written_to_the_journal_before_the_reexec(capsys):
    make(Machine())[0].run()

    assert f"self-update {OLD[:7]} -> {NEW[:7]}" in capsys.readouterr().err


def test_head_names_the_commit_without_updating():
    machine = Machine()

    assert make(machine)[0].head() == OLD
    assert machine.ran(["git", "fetch"]) == []


def test_the_default_command_reruns_the_same_subcommand_with_the_venv_python(monkeypatch):
    import sys

    monkeypatch.setattr(sys, "argv", ["/x/.venv/bin/factory", "preflight"])
    updater = SelfUpdate(repo_dir=REPO, tools_dir=TOOLS, run=Machine(), env={})

    assert updater._command == [sys.executable, "-m", "factory.main", "preflight"]


def _git(cwd, *args):
    import subprocess

    subprocess.run(
        ["git", "-c", "user.email=a@b", "-c", "user.name=a", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def test_with_real_git_a_clean_clone_fast_forwards_and_a_dirty_one_is_left_alone(tmp_path):
    from factory.shell import run_command

    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    seed = tmp_path / "seed"
    _git(tmp_path, "clone", "-q", str(origin), str(seed))
    (seed / "a.txt").write_text("1\n")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-qm", "one")
    _git(seed, "push", "-q", "origin", "HEAD:main")
    repo = tmp_path / "repo"
    _git(tmp_path, "clone", "-q", str(origin), str(repo))
    (seed / "a.txt").write_text("2\n")
    _git(seed, "commit", "-qam", "two")
    _git(seed, "push", "-q", "origin", "HEAD:main")

    def run(argv, cwd, *, timeout, env=None, replace_env=False):
        if argv[0] == "uv":
            return CommandResult(0, "", "")
        return run_command(argv, cwd, timeout=timeout)

    dirty = tmp_path / "dirty"
    _git(tmp_path, "clone", "-q", str(origin), str(dirty))
    _git(dirty, "reset", "-q", "--hard", "HEAD~1")
    (dirty / "a.txt").write_text("local edit\n")

    execs = []
    updated = SelfUpdate(
        repo_dir=repo,
        tools_dir=repo,
        run=run,
        env={},
        execv=lambda *a: execs.append(a),
        command=["x"],
    ).run()
    blocked = SelfUpdate(
        repo_dir=dirty,
        tools_dir=dirty,
        run=run,
        env={},
        execv=lambda *a: execs.append(a),
        command=["x"],
    ).run()

    assert updated.status == "updated" and (repo / "a.txt").read_text() == "2\n"
    assert blocked.status == "blocked" and "local changes" in blocked.reason
    assert (dirty / "a.txt").read_text() == "local edit\n"
    assert len(execs) == 1
