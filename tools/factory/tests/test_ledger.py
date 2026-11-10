from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from factory.ledger import AttemptLedger

MEXICO_CITY = ZoneInfo("America/Mexico_City")


def test_count_today_uses_the_mexico_city_day_boundary(tmp_path):
    now = datetime(2026, 11, 10, 0, 30, tzinfo=MEXICO_CITY)
    ledger = AttemptLedger(tmp_path / "state", clock=lambda: now)

    ledger.record(1, "ok", started_at=datetime(2026, 11, 9, 23, 59, tzinfo=MEXICO_CITY))
    ledger.record(2, "stuck", started_at=datetime(2026, 11, 10, 0, 1, tzinfo=MEXICO_CITY))

    assert ledger.count_today() == 1


def test_count_today_converts_utc_timestamps_to_mexico_city(tmp_path):
    now = datetime(2026, 11, 10, 9, 0, tzinfo=MEXICO_CITY)
    ledger = AttemptLedger(tmp_path / "state", clock=lambda: now)

    # 05:30 UTC is still 2026-11-09 in Mexico City (UTC-6); 06:30 UTC is today.
    ledger.record(1, "ok", started_at=datetime(2026, 11, 10, 5, 30, tzinfo=UTC))
    ledger.record(2, "ok", started_at=datetime(2026, 11, 10, 6, 30, tzinfo=UTC))

    assert ledger.count_today() == 1


def test_failed_attempts_count_toward_the_daily_total(tmp_path):
    now = datetime(2026, 11, 10, 10, 0, tzinfo=MEXICO_CITY)
    ledger = AttemptLedger(tmp_path / "state", clock=lambda: now)

    ledger.record(7, "stuck", started_at=now)
    ledger.record(8, "failed", started_at=now)

    assert ledger.count_today() == 2


def test_record_appends_one_line_with_timestamp_ticket_and_outcome(tmp_path):
    now = datetime(2026, 11, 10, 10, 0, tzinfo=MEXICO_CITY)
    ledger = AttemptLedger(tmp_path / "state", clock=lambda: now)

    ledger.record(7, "stuck", started_at=now)

    lines = ledger.path.read_text().splitlines()
    assert len(lines) == 1
    timestamp, ticket, outcome = lines[0].split("\t")
    assert datetime.fromisoformat(timestamp).astimezone(MEXICO_CITY) == now
    assert ticket == "#7"
    assert outcome == "stuck"
    assert ledger.path.stat().st_mode & 0o077 == 0


def test_malformed_ledger_lines_are_ignored(tmp_path):
    now = datetime(2026, 11, 10, 10, 0, tzinfo=MEXICO_CITY)
    ledger = AttemptLedger(tmp_path / "state", clock=lambda: now)
    ledger.state_dir.mkdir(parents=True)
    ledger.path.write_text("not a timestamp\n\n")

    assert ledger.count_today() == 0
