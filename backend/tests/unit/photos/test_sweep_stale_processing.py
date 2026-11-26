from datetime import UTC, datetime, timedelta

import pytest

from apps.photos.application.process_photo import ProcessPhotoSubmission
from apps.photos.application.sweep_stale_processing import SweepStaleProcessing
from apps.photos.domain.errors import ConcurrentModification
from apps.photos.domain.submission import (
    PhotoSubmission,
    SubmissionKind,
    SubmissionStatus,
)
from apps.shared.domain.store import StoreReference
from tests.unit.photos.fakes import (
    FakeCatalog,
    FakePhotoProcessor,
    FakePhotoSubmissionRepository,
    FakePrivateMediaReader,
)

HOME = StoreReference(id=1, slug="home")
ANIME = StoreReference(id=2, slug="anime")
NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
STALE_AFTER = timedelta(minutes=15)


def make_submission(
    *,
    submission_id=1,
    store=HOME,
    status=SubmissionStatus.PROCESSING,
    updated_at=NOW - timedelta(minutes=20),
    attempts=1,
    discarded_at=None,
):
    return PhotoSubmission(
        id=submission_id,
        store_id=store.id,
        created_by_id=7,
        kind=SubmissionKind.GROUP,
        idempotency_key=f"key-{submission_id}",
        request_fingerprint="a" * 64,
        original_key=f"stores/{store.id}/photos/originals/original.jpg",
        preview_key=f"stores/{store.id}/photos/previews/preview.jpg",
        status=status,
        attempts=attempts,
        updated_at=updated_at,
        discarded_at=discarded_at,
    )


def sweep(repository):
    return SweepStaleProcessing(repository=repository, stale_after=STALE_AFTER)(NOW)


def test_a_processing_submission_older_than_the_threshold_is_marked_failed():
    repository = FakePhotoSubmissionRepository(rows=[make_submission()])

    failed = sweep(repository)

    assert [submission.id for submission in failed] == [1]
    stored = repository.rows[1]
    assert stored.status is SubmissionStatus.FAILED
    assert stored.failure_code == "photo_processing_unavailable"
    assert stored.failure_message
    assert stored.attempts == 1


def test_a_processing_submission_newer_than_the_threshold_is_left_alone():
    repository = FakePhotoSubmissionRepository(
        rows=[make_submission(updated_at=NOW - timedelta(minutes=5))]
    )

    assert sweep(repository) == []
    assert repository.rows[1].status is SubmissionStatus.PROCESSING
    assert repository.rows[1].failure_code == ""


@pytest.mark.parametrize("status", [SubmissionStatus.READY, SubmissionStatus.FAILED])
def test_a_submission_in_another_state_is_left_alone(status):
    repository = FakePhotoSubmissionRepository(rows=[make_submission(status=status)])

    assert sweep(repository) == []
    assert repository.rows[1].status is status


def test_an_uploaded_submission_older_than_the_threshold_is_marked_failed():
    repository = FakePhotoSubmissionRepository(
        rows=[make_submission(status=SubmissionStatus.UPLOADED, attempts=0)]
    )

    failed = sweep(repository)

    assert [submission.id for submission in failed] == [1]
    stored = repository.rows[1]
    assert stored.status is SubmissionStatus.FAILED
    assert stored.failure_code == "photo_processing_unavailable"
    assert stored.failure_message
    assert stored.attempts == 1


def test_an_uploaded_submission_newer_than_the_threshold_is_left_alone():
    repository = FakePhotoSubmissionRepository(
        rows=[
            make_submission(
                status=SubmissionStatus.UPLOADED,
                attempts=0,
                updated_at=NOW - timedelta(minutes=5),
            )
        ]
    )

    assert sweep(repository) == []
    assert repository.rows[1].status is SubmissionStatus.UPLOADED
    assert repository.rows[1].failure_code == ""
    assert repository.rows[1].attempts == 0


def test_a_discarded_uploaded_submission_records_the_discarded_failure():
    repository = FakePhotoSubmissionRepository(
        rows=[
            make_submission(
                status=SubmissionStatus.UPLOADED,
                attempts=0,
                discarded_at=NOW - timedelta(minutes=1),
            )
        ]
    )

    failed = sweep(repository)

    assert [submission.id for submission in failed] == [1]
    assert repository.rows[1].status is SubmissionStatus.FAILED
    assert repository.rows[1].failure_code == "photo_submission_discarded"
    assert repository.rows[1].attempts == 0


def test_a_worker_that_receives_the_lost_message_after_the_sweep_leaves_it_failed():
    repository = FakePhotoSubmissionRepository(
        rows=[make_submission(status=SubmissionStatus.UPLOADED, attempts=0)]
    )
    swept = sweep(repository)[0]
    processor = FakePhotoProcessor()

    ProcessPhotoSubmission(
        repository=repository,
        catalog=FakeCatalog(),
        processor=processor,
        reader=FakePrivateMediaReader(contents={swept.original_key: b"original"}),
    )(HOME, swept.id)

    stored = repository.rows[1]
    assert stored.status is SubmissionStatus.FAILED
    assert stored.failure_code == "photo_processing_unavailable"
    assert stored.attempts == 1
    assert processor.calls == []


def test_a_discarded_processing_submission_records_the_discarded_failure():
    repository = FakePhotoSubmissionRepository(
        rows=[make_submission(discarded_at=NOW - timedelta(minutes=1))]
    )

    failed = sweep(repository)

    assert [submission.id for submission in failed] == [1]
    assert repository.rows[1].status is SubmissionStatus.FAILED
    assert repository.rows[1].failure_code == "photo_submission_discarded"


def test_the_sweep_touches_every_stores_stale_submissions():
    repository = FakePhotoSubmissionRepository(
        rows=[
            make_submission(submission_id=1, store=HOME),
            make_submission(submission_id=2, store=ANIME),
            make_submission(
                submission_id=3,
                store=ANIME,
                updated_at=NOW - timedelta(minutes=1),
            ),
            make_submission(
                submission_id=4,
                store=ANIME,
                status=SubmissionStatus.UPLOADED,
                attempts=0,
            ),
        ]
    )

    failed = sweep(repository)

    assert sorted(submission.id for submission in failed) == [1, 2, 4]
    assert repository.rows[1].status is SubmissionStatus.FAILED
    assert repository.rows[2].status is SubmissionStatus.FAILED
    assert repository.rows[3].status is SubmissionStatus.PROCESSING
    assert repository.rows[4].status is SubmissionStatus.FAILED


def test_a_store_scoped_sweep_only_touches_that_store():
    repository = FakePhotoSubmissionRepository(
        rows=[
            make_submission(submission_id=1, store=HOME),
            make_submission(
                submission_id=2,
                store=ANIME,
                status=SubmissionStatus.UPLOADED,
                attempts=0,
            ),
        ]
    )
    use_case = SweepStaleProcessing(repository=repository, stale_after=STALE_AFTER)

    failed = use_case(NOW, store=ANIME)

    assert [submission.id for submission in failed] == [2]
    assert repository.rows[1].status is SubmissionStatus.PROCESSING
    assert repository.rows[2].status is SubmissionStatus.FAILED


class ConcurrentChangeRepository(FakePhotoSubmissionRepository):
    def save(self, submission):
        if submission.id == 1:
            raise ConcurrentModification("This submission changed during the sweep.")
        return super().save(submission)


@pytest.mark.parametrize("status", [SubmissionStatus.PROCESSING, SubmissionStatus.UPLOADED])
def test_a_submission_that_changes_during_the_sweep_is_skipped_not_overwritten(status):
    repository = ConcurrentChangeRepository(
        rows=[
            make_submission(submission_id=1, status=status, attempts=0),
            make_submission(submission_id=2, status=status, attempts=0),
        ]
    )

    failed = sweep(repository)

    assert [submission.id for submission in failed] == [2]
    assert repository.rows[1].status is status
    assert repository.rows[2].status is SubmissionStatus.FAILED
