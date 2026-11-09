import os

import pytest

from factory.cleanup import cleanup_old

NOW = 1_700_000_000


def age(path, *, days):
    stamp = NOW - days * 86400
    os.utime(path, (stamp, stamp))


def test_cleanup_old_hands_expired_directories_to_remove_dir(tmp_path):
    root = tmp_path / "worktrees"
    root.mkdir()
    keep = root / "keep"
    expired = root / "expired"
    keep.mkdir()
    expired.mkdir()
    age(keep, days=1)
    age(expired, days=30)
    removed = []

    cleanup_old(root, now=NOW, keep_days=14, remove_dir=removed.append)

    assert removed == [expired]
    assert keep.exists()


def test_cleanup_old_still_removes_directories_without_a_callback(tmp_path):
    root = tmp_path / "logs"
    root.mkdir()
    expired = root / "expired"
    expired.mkdir()
    (expired / "run.log").write_text("old")
    age(expired, days=30)

    cleanup_old(root, now=NOW, keep_days=14)

    assert not expired.exists()


def test_cleanup_old_removes_expired_files(tmp_path):
    root = tmp_path / "logs"
    root.mkdir()
    expired = root / "run.log"
    expired.write_text("old")
    age(expired, days=30)

    cleanup_old(root, now=NOW, keep_days=14)

    assert not expired.exists()


def test_cleanup_old_does_not_swallow_remove_dir_errors(tmp_path):
    root = tmp_path / "worktrees"
    root.mkdir()
    expired = root / "expired"
    expired.mkdir()
    age(expired, days=30)

    def explode(_path):
        raise RuntimeError("cleanup exploded")

    with pytest.raises(RuntimeError, match="cleanup exploded"):
        cleanup_old(root, now=NOW, keep_days=14, remove_dir=explode)
