"""The parts of ``Git`` stand alone (#147)."""

from factory.area_checks import AreaChecks
from factory.areas import BACKEND, CONSOLE
from factory.git import Git
from factory.git_repo import GitRepo
from factory.shell import CommandResult
from factory.worktree_cleanup import WorktreeCleanup


class Run:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, cwd, *, timeout, env=None, replace_env=False):
        self.calls.append(argv)
        if "/usr/bin/pkill" in argv:
            return CommandResult(1, "", "")
        return CommandResult(0, "", "")


def _scripts(worktree):
    for area in (BACKEND, CONSOLE):
        script = worktree / area.script
        script.parent.mkdir(parents=True)
        script.write_text("#!/bin/sh\n")


def test_area_checks_pick_areas_from_the_changed_files_they_are_given(tmp_path):
    _scripts(tmp_path)
    seen = []

    def changed(worktree):
        seen.append(worktree)
        return ["web/console/app/page.tsx"]

    result = AreaChecks(Run(), changed_files=changed, port_in_use=lambda _port: False).check(
        tmp_path
    )

    assert seen == [tmp_path]
    assert result.checked_areas == (CONSOLE,)


def test_explicit_areas_never_ask_for_changed_files(tmp_path):
    _scripts(tmp_path)

    def changed(_worktree):
        raise AssertionError("not asked")

    result = AreaChecks(Run(), changed_files=changed, port_in_use=lambda _port: False).check(
        tmp_path, areas=(BACKEND,)
    )

    assert result.checked_areas == (BACKEND,)


def test_git_is_a_repo_whose_checks_read_its_own_changed_files(tmp_path):
    git = Git(Run(), agent_user="factory-agent")

    assert isinstance(git, GitRepo)
    assert isinstance(git.checks, AreaChecks)
    assert isinstance(git.cleanup, WorktreeCleanup)
    git.changed_files = lambda worktree: ["web/console/x.tsx"]
    assert git.checks._changed_files(tmp_path) == ["web/console/x.tsx"]
