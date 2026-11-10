from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1] / "systemd" / "factory.service"
TIMER = Path(__file__).resolve().parents[1] / "systemd" / "factory.timer"


def test_service_makes_factory_files_group_writable():
    assert "UMask=0007" in SERVICE.read_text()


def test_service_uses_the_system_wide_uv():
    assert "ExecStart=/usr/local/bin/uv run factory" in SERVICE.read_text()


def test_timer_runs_hourly_and_catches_up():
    timer = TIMER.read_text()
    assert "OnCalendar=hourly" in timer
    assert "Persistent=true" in timer


def test_service_is_oneshot_so_systemd_never_overlaps_runs():
    assert "Type=oneshot" in SERVICE.read_text()
    assert "Type=oneshot" in TIMER.read_text()
