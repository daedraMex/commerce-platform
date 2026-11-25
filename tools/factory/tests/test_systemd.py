from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1] / "systemd" / "factory.service"
TIMER = Path(__file__).resolve().parents[1] / "systemd" / "factory.timer"


def test_service_makes_factory_files_group_writable():
    assert "UMask=0007" in SERVICE.read_text()


def test_service_uses_the_system_wide_uv_with_a_locked_environment():
    # --locked fails on a stale uv.lock instead of rewriting it in the checkout,
    # which the self-update would then see as local changes (#216).
    assert "ExecStart=/usr/local/bin/uv run --locked factory\n" in SERVICE.read_text()


def test_timer_runs_hourly_and_catches_up():
    timer = TIMER.read_text()
    assert "OnCalendar=hourly" in timer
    assert "Persistent=true" in timer


def test_service_is_oneshot_so_systemd_never_overlaps_runs():
    assert "Type=oneshot" in SERVICE.read_text()
    assert "Type=oneshot" in TIMER.read_text()


METRICS_SERVICE = SERVICE.parent / "factory-metrics.service"
METRICS_TIMER = SERVICE.parent / "factory-metrics.timer"


def test_metrics_service_runs_the_metrics_command_once():
    service = METRICS_SERVICE.read_text()
    assert "Type=oneshot" in service
    assert "ExecStart=/usr/local/bin/uv run --locked factory metrics" in service
    assert "EnvironmentFile=%h/factory/secrets.env" in service


def test_metrics_timer_runs_monday_morning_in_mexico_city_and_catches_up():
    timer = METRICS_TIMER.read_text()
    assert "OnCalendar=Mon *-*-* 09:00:00 America/Mexico_City" in timer
    assert "Persistent=true" in timer
    assert "Unit=factory-metrics.service" in timer
