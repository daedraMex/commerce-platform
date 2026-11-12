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
