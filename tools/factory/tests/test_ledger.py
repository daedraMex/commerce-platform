from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from factory.ledger import STARTED, AttemptLedger

MEXICO_CITY = ZoneInfo("America/Mexico_City")


def test_count_today_uses_the_mexico_city_day_boundary(tmp_path):
    now = datetime(2026, 11, 10, 0, 30, tzinfo=MEXICO_CITY)
    ledger = AttemptLedger(tmp_path / "state", clock=lambda: now)

    ledger.record_started(1, started_at=datetime(2026, 11, 9, 23, 59, tzinfo=MEXICO_CITY))
    ledger.record_started(2, started_at=datetime(2026, 11, 10, 0, 1, tzinfo=MEXICO_CITY))

    assert ledger.count_today() == 1


def test_count_today_converts_utc_timestamps_to_mexico_city(tmp_path):
    now = datetime(2026, 11, 10, 9, 0, tzinfo=MEXICO_CITY)
    ledger = AttemptLedger(tmp_path / "state", clock=lambda: now)

    # 05:30 UTC is still 2026-11-09 in Mexico City (UTC-6); 06:30 UTC is today.
    ledger.record_started(1, started_at=datetime(2026, 11, 10, 5, 30, tzinfo=UTC))
    ledger.record_started(2, started_at=datetime(2026, 11, 10, 6, 30, tzinfo=UTC))

    assert ledger.count_today() == 1


def test_failed_attempts_count_toward_the_daily_total(tmp_path):
    now = datetime(2026, 11, 10, 10, 0, tzinfo=MEXICO_CITY)
    ledger = AttemptLedger(tmp_path / "state", clock=lambda: now)

    ledger.record_started(7, started_at=now)
    ledger.record_outcome(7, "stuck", finished_at=now)
    ledger.record_started(8, started_at=now)
    ledger.record_outcome(8, "failed", finished_at=now)

    assert ledger.count_today() == 2


def test_a_started_line_without_an_outcome_still_counts(tmp_path):
    now = datetime(2026, 11, 10, 10, 0, tzinfo=MEXICO_CITY)
    ledger = AttemptLedger(tmp_path / "state", clock=lambda: now)

    ledger.record_started(7, started_at=now)

    assert ledger.count_today() == 1


def test_count_today_ignores_outcome_lines(tmp_path):
    now = datetime(2026, 11, 10, 10, 0, tzinfo=MEXICO_CITY)
    ledger = AttemptLedger(tmp_path / "state", clock=lambda: now)

    ledger.record_outcome(7, "ok", finished_at=now)

    assert ledger.count_today() == 0


def test_ledger_appends_started_then_outcome_lines(tmp_path):
    now = datetime(2026, 11, 10, 10, 0, tzinfo=MEXICO_CITY)
    ledger = AttemptLedger(tmp_path / "state", clock=lambda: now)

    ledger.record_started(7, started_at=now)
    ledger.record_outcome(7, "stuck", finished_at=now)

    lines = ledger.path.read_text().splitlines()
    assert len(lines) == 2
    timestamp, ticket, outcome = lines[0].split("\t")
    assert datetime.fromisoformat(timestamp).astimezone(MEXICO_CITY) == now
    assert ticket == "#7"
    assert outcome == STARTED
    assert lines[1].split("\t")[2] == "stuck"
    assert ledger.path.stat().st_mode & 0o077 == 0


def test_malformed_ledger_lines_are_ignored(tmp_path):
    now = datetime(2026, 11, 10, 10, 0, tzinfo=MEXICO_CITY)
    ledger = AttemptLedger(tmp_path / "state", clock=lambda: now)
    ledger.state_dir.mkdir(parents=True)
    ledger.path.write_text("not a timestamp\n\n")

    assert ledger.count_today() == 0
