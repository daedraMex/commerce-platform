"""One factory run at a time: the hourly run and a manual preflight never overlap (#233)."""

import os
import subprocess
import sys

import pytest

from factory.run_lock import LOCK_ENV, RunLocked, acquire_run_lock


def test_a_second_run_is_refused_and_told_who_holds_the_lock(tmp_path):
    lock = tmp_path / "run.lock"
    first_env = {}
    fd = acquire_run_lock(lock, env=first_env, command="run", now="2026-11-25T08:00:00")

    with pytest.raises(RunLocked) as excinfo:
        acquire_run_lock(lock, env={}, command="preflight")

    assert f"pid {os.getpid()}" in str(excinfo.value)
    assert "run since 2026-11-25T08:00:00" in str(excinfo.value)
    assert first_env[LOCK_ENV] == str(fd)
    os.close(fd)


def test_the_lock_goes_with_the_process(tmp_path):
    lock = tmp_path / "run.lock"
    fd = acquire_run_lock(lock, env={}, command="run")
    os.close(fd)  # what the kernel does when the process dies

    again = acquire_run_lock(lock, env={}, command="run")

    os.close(again)


def test_a_self_updated_process_keeps_the_lock_it_inherited(tmp_path):
    lock = tmp_path / "run.lock"
    env = {}
    fd = acquire_run_lock(lock, env=env, command="run")
    child = (
        "import os, sys\n"
        "from factory.run_lock import acquire_run_lock\n"
        "env = {'FACTORY_RUN_LOCK_FD': sys.argv[2]}\n"
        "print(acquire_run_lock(sys.argv[1], env=env, command='run'))\n"
    )

    # As os.execv would: the inheritable descriptor and its number in the environment.
    out = subprocess.run(
        [sys.executable, "-c", child, str(lock), env[LOCK_ENV]],
        pass_fds=[fd],
        capture_output=True,
        text=True,
        check=True,
    )

    assert out.stdout.strip() == str(fd)
    with pytest.raises(RunLocked):
        acquire_run_lock(lock, env={}, command="preflight")
    os.close(fd)


def test_a_forged_descriptor_does_not_bypass_the_lock(tmp_path):
    lock = tmp_path / "run.lock"
    holder = acquire_run_lock(lock, env={}, command="run")
    other = os.open(tmp_path / "other", os.O_RDWR | os.O_CREAT, 0o600)

    with pytest.raises(RunLocked):
        acquire_run_lock(lock, env={LOCK_ENV: str(other)}, command="preflight")
    with pytest.raises(RunLocked):
        acquire_run_lock(lock, env={LOCK_ENV: "999999"}, command="preflight")

    os.close(other)
    os.close(holder)


def test_the_lock_file_is_private(tmp_path):
    lock = tmp_path / "state" / "run.lock"
    fd = acquire_run_lock(lock, env={}, command="run")

    assert oct(lock.stat().st_mode & 0o777) == "0o600"
    os.close(fd)
