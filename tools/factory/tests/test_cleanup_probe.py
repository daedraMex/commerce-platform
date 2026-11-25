import os
from pathlib import Path

import pytest

from factory.cleanup_probe import CleanupProbeError, verify_cleanup_probe


def _copies(tmp_path, installed_text="#!/bin/bash\necho probe\n", repo_text=None):
    repo = tmp_path / "repo" / "cleanup-probe"
    repo.parent.mkdir()
    repo.write_text(repo_text if repo_text is not None else installed_text)
    installed = tmp_path / "lib" / "cleanup-probe"
    installed.parent.mkdir()
    installed.write_text(installed_text)
    installed.chmod(0o755)
    return installed, repo


def test_accepts_an_installed_copy_identical_to_the_repo(tmp_path):
    installed, repo = _copies(tmp_path)

    verify_cleanup_probe(installed, repo, owner_uid=os.getuid())


def test_a_changed_repo_copy_names_the_install_command(tmp_path):
    installed, repo = _copies(tmp_path, repo_text="#!/bin/bash\necho new\n")

    with pytest.raises(CleanupProbeError) as excinfo:
        verify_cleanup_probe(installed, repo, owner_uid=os.getuid())

    message = str(excinfo.value)
    assert "differs from the repo" in message
    assert f"sudo install -D -o root -g root -m 0755 {repo} {installed}" in message


def test_a_missing_installed_copy_names_the_install_command(tmp_path):
    installed, repo = _copies(tmp_path)
    installed.unlink()

    with pytest.raises(CleanupProbeError, match="is not installed.*sudo install -D"):
        verify_cleanup_probe(installed, repo, owner_uid=os.getuid())


def test_an_installed_copy_not_owned_by_root_is_refused(tmp_path):
    installed, repo = _copies(tmp_path)

    with pytest.raises(CleanupProbeError, match="must be owned by root"):
        verify_cleanup_probe(installed, repo, owner_uid=os.getuid() + 1)


@pytest.mark.parametrize("mode", [0o775, 0o757])
def test_a_writable_installed_copy_is_refused(tmp_path, mode):
    installed, repo = _copies(tmp_path)
    installed.chmod(mode)

    with pytest.raises(CleanupProbeError, match="writable"):
        verify_cleanup_probe(installed, repo, owner_uid=os.getuid())


def test_a_symlinked_installed_copy_is_refused(tmp_path):
    installed, repo = _copies(tmp_path)
    installed.unlink()
    installed.symlink_to(repo)

    with pytest.raises(CleanupProbeError, match="symlink"):
        verify_cleanup_probe(installed, repo, owner_uid=os.getuid())


def test_a_missing_repo_copy_fails(tmp_path):
    installed, repo = _copies(tmp_path)
    repo.unlink()

    with pytest.raises(CleanupProbeError, match="repo copy"):
        verify_cleanup_probe(installed, repo, owner_uid=os.getuid())


def test_every_failure_keeps_the_install_command_within_the_telegram_limit(tmp_path):
    from factory.git import CLEANUP_PROBE_PATH
    from factory.preflight import MAX_ERROR_CHARS

    repo = Path("/srv/factory/repo/tools/factory/scripts/cleanup-probe")
    install = f"sudo install -D -o root -g root -m 0755 {repo} {CLEANUP_PROBE_PATH}"
    # "preflight failed: verify cleanup probe: " plus the longest reason.
    longest = f"{CLEANUP_PROBE_PATH} is group- or world-writable; as admin: {install}"

    assert len("verify cleanup probe: " + longest) <= MAX_ERROR_CHARS
