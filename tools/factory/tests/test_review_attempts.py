from datetime import datetime
from zoneinfo import ZoneInfo

from factory.review_attempts import REVIEW_ATTEMPTS_FILE, ReviewAttemptLedger

MEXICO_CITY = ZoneInfo("America/Mexico_City")


def test_record_attempted_is_append_only_and_returns_every_id(tmp_path):
    now = datetime(2026, 11, 10, 10, 0, tzinfo=MEXICO_CITY)
    ledger = ReviewAttemptLedger(tmp_path / "state", clock=lambda: now)

    ledger.record_attempted("R1")
    ledger.record_attempted("R2")

    assert ledger.attempted_ids() == {"R1", "R2"}
    lines = ledger.path.read_text().splitlines()
    assert len(lines) == 2
    assert [line.split("\t")[1] for line in lines] == ["R1", "R2"]


def test_review_attempts_file_is_private_to_the_factory_user(tmp_path):
    ledger = ReviewAttemptLedger(tmp_path / "state")

    ledger.record_attempted("R1")

    assert ledger.path.name == REVIEW_ATTEMPTS_FILE
    assert ledger.path.stat().st_mode & 0o077 == 0
    assert ledger.state_dir.stat().st_mode & 0o077 == 0


def test_malformed_review_attempt_lines_are_ignored(tmp_path):
    ledger = ReviewAttemptLedger(tmp_path / "state")
    ledger.state_dir.mkdir(parents=True)
    ledger.path.write_text("missing separator\n\n2026-11-10T10:00:00\tR1\n")

    assert ledger.attempted_ids() == {"R1"}
