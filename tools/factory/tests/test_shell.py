import os
import sys
import time

import pytest

from factory.shell import CommandTimeout, merge_env, run_command


def test_merge_env_removes_none_keys(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "secret")
    monkeypatch.setenv("KEEP", "value")
    env = merge_env({"GH_TOKEN": None, "NEW": "x"})
    assert "GH_TOKEN" not in env
    assert env["KEEP"] == "value"
    assert env["NEW"] == "x"


def test_merge_env_passthrough_without_overrides(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    env = merge_env(None)
    assert env["PATH"] == "/usr/bin"


def test_run_command_kills_the_same_user_process_group_on_timeout(tmp_path):
    pidfile = tmp_path / "child.pid"
    termfile = tmp_path / "term.marker"
    script = (
        "import os, signal, subprocess, sys, time\n"
        f"open({str(termfile)!r}, 'w').write('started')\n"
        "def on_term(*_):\n"
        f"    open({str(termfile)!r}, 'w').write('terminated')\n"
        "    sys.exit(0)\n"
        "signal.signal(signal.SIGTERM, on_term)\n"
        f"child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open({str(pidfile)!r}, 'w').write(str(child.pid))\n"
        "time.sleep(60)\n"
    )

    with pytest.raises(CommandTimeout):
        run_command([sys.executable, "-c", script], str(tmp_path), timeout=1)

    assert termfile.read_text() == "terminated"
    child = int(pidfile.read_text())
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    pytest.fail(f"child process {child} survived the process-group kill")


def _is_dead(pid: int) -> bool:
    """Gone, or a zombie: an orphan's reaper (PID 1 in a container) may never wait."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    try:
        with open(f"/proc/{pid}/stat") as stat:
            return stat.read().rsplit(")", 1)[1].split()[0] == "Z"
    except FileNotFoundError:
        return True


def _wait_until_gone(pid: int, seconds: float = 5) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if _is_dead(pid):
            return True
        time.sleep(0.05)
    return False


def test_run_command_kills_the_process_group_when_interrupted(tmp_path):
    """Ctrl+C reaches only the factory: its children run in their own session (#194).

    Before the fix, ``check.sh`` kept writing into the worktree while the
    preflight's cleanup deleted it.
    """
    import signal
    import threading

    pidfile = tmp_path / "child.pid"
    script = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open({str(pidfile)!r}, 'w').write(str(child.pid))\n"
        "time.sleep(60)\n"
    )

    def interrupt_once_started():
        deadline = time.time() + 10
        while not pidfile.exists() and time.time() < deadline:
            time.sleep(0.05)
        os.kill(os.getpid(), signal.SIGINT)  # what Ctrl+C sends

    threading.Thread(target=interrupt_once_started, daemon=True).start()
    with pytest.raises(KeyboardInterrupt):
        run_command([sys.executable, "-c", script], str(tmp_path), timeout=30)

    child = int(pidfile.read_text())
    assert _wait_until_gone(child, seconds=0.5), (
        f"grandchild {child} still running after the interrupt propagated"
    )
