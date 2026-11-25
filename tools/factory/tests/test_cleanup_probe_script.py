"""The root-owned cleanup-probe script, run for real against a temp root (#140)."""

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cleanup-probe"
ROOT_LINE = "root=/srv/factory/worktrees\n"


@pytest.fixture
def probe(tmp_path):
    root = tmp_path / "worktrees"
    root.mkdir()
    script = tmp_path / "cleanup-probe"
    text = SCRIPT.read_text()
    assert text.count(ROOT_LINE) == 1
    script.write_text(text.replace(ROOT_LINE, f"root={root}\n"))
    script.chmod(0o755)

    def run(*args):
        return subprocess.run([str(script), *args], capture_output=True, text=True)

    run.root = root
    return run


def _worktree(root, name="preflight-42"):
    worktree = root / name
    (worktree / "backend").mkdir(parents=True)
    return worktree


def test_the_script_is_executable_bash_with_a_fixed_root():
    text = SCRIPT.read_text()
    assert text.startswith("#!/bin/bash\n")
    assert ROOT_LINE in text
    assert SCRIPT.stat().st_mode & stat.S_IXUSR
    # SETENV in the sudoers rule would let the factory set any variable, so the
    # script reads nothing from the environment.
    assert "${FACTORY" not in text and "$HOME" not in text
    assert "mktemp -d /tmp/" in text


def test_creates_the_probe_with_the_agents_group_through_a_rename(probe):
    worktree = _worktree(probe.root)

    result = probe(str(worktree))

    assert result.returncode == 0, result.stderr
    created = worktree / "backend" / ".cleanup-probe"
    assert stat.S_IMODE(created.stat().st_mode) == 0o770
    assert created.stat().st_gid == os.getgid()
    assert (created / "file").read_text() == "cleanup probe\n"
    assert stat.S_IMODE((created / "file").stat().st_mode) == 0o644


@pytest.mark.parametrize(
    "arg",
    [
        "/etc",
        "/srv/factory/worktrees-evil/x",
        "{root}",
        "{root}/",
        "{root}/a/b",
        "{root}/..",
        "{root}/.",
        "{root}/../worktrees/preflight-42",
        "{root}/missing",
    ],
)
def test_refuses_any_path_but_one_existing_worktree(probe, arg):
    _worktree(probe.root)

    result = probe(arg.format(root=probe.root))

    assert result.returncode != 0
    assert "refusing" in result.stderr


def test_refuses_without_exactly_one_argument(probe):
    worktree = _worktree(probe.root)

    assert probe().returncode != 0
    assert probe(str(worktree), str(worktree)).returncode != 0


def test_refuses_a_symlinked_worktree_or_backend(probe, tmp_path):
    outside = tmp_path / "outside"
    (outside / "backend").mkdir(parents=True)
    (probe.root / "linked").symlink_to(outside)
    worktree = probe.root / "real"
    worktree.mkdir()
    (worktree / "backend").symlink_to(outside / "backend")

    for name in ("linked", "real"):
        result = probe(str(probe.root / name))
        assert result.returncode != 0
        assert "refusing" in result.stderr
    assert not (outside / "backend" / ".cleanup-probe").exists()


def test_fails_instead_of_nesting_into_an_existing_probe(probe):
    worktree = _worktree(probe.root)
    existing = worktree / "backend" / ".cleanup-probe"
    existing.mkdir()
    (existing / "keep").write_text("x")

    result = probe(str(worktree))

    assert result.returncode != 0
    assert not (existing / ".cleanup-probe").exists()
