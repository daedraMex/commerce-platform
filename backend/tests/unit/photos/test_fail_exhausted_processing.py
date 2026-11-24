from datetime import UTC, datetime

import pytest

from apps.photos.application.fail_exhausted_processing import FailExhaustedProcessing
from apps.photos.domain.submission import (
    PhotoSubmission,
    SubmissionKind,
    SubmissionStatus,
)
from apps.shared.domain.exceptions import NotFoundError
from apps.shared.domain.store import StoreReference
from tests.unit.photos.fakes import FakePhotoSubmissionRepository

HOME = StoreReference(id=1, slug="home")
ANIME = StoreReference(id=2, slug="anime")
NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


def make_submission(**overrides):
    values = {
        "id": 1,
        "store_id": HOME.id,
        "created_by_id": 7,
        "kind": SubmissionKind.RECTANGLE,
        "target_product_id": 10,
        "photographed_variant_id": 20,
        "idempotency_key": "key-1",
        "request_fingerprint": "a" * 64,
        "original_key": "stores/1/photos/originals/original.jpg",
        "preview_key": "stores/1/photos/previews/preview.jpg",
        "status": SubmissionStatus.PROCESSING,
        "attempts": 1,
    }
    values.update(overrides)
    return PhotoSubmission(**values)


def test_an_exhausted_attempt_moves_processing_to_failed_without_spending_an_attempt():
    repository = FakePhotoSubmissionRepository(rows=[make_submission()])
    use_case = FailExhaustedProcessing(repository=repository)

    saved = use_case(HOME, submission_id=1)

    assert saved.status is SubmissionStatus.FAILED
    assert saved.failure_code == "photo_processing_unavailable"
    assert saved.failure_message
    assert saved.attempts == 1
    assert repository.rows[1].status is SubmissionStatus.FAILED
    assert repository.rows[1].failure_code == "photo_processing_unavailable"


def test_a_discarded_submission_still_ends_failed_as_discarded():
    repository = FakePhotoSubmissionRepository(rows=[make_submission(discarded_at=NOW)])
    use_case = FailExhaustedProcessing(repository=repository)

    saved = use_case(HOME, submission_id=1)

    assert saved.status is SubmissionStatus.FAILED
    assert saved.failure_code == "photo_submission_discarded"


def test_an_exhausted_uploaded_submission_records_the_attempt_that_never_saved():
    repository = FakePhotoSubmissionRepository(
        rows=[make_submission(status=SubmissionStatus.UPLOADED, attempts=0)]
    )
    use_case = FailExhaustedProcessing(repository=repository)

    saved = use_case(HOME, submission_id=1)

    assert saved.status is SubmissionStatus.FAILED
    assert saved.failure_code == "photo_processing_unavailable"
    assert saved.failure_message
    assert saved.attempts == 1


def test_a_submission_that_is_no_longer_processing_is_left_unchanged():
    repository = FakePhotoSubmissionRepository(
        rows=[make_submission(status=SubmissionStatus.READY, result_media_id=30)]
    )
    use_case = FailExhaustedProcessing(repository=repository)

    saved = use_case(HOME, submission_id=1)

    assert saved.status is SubmissionStatus.READY
    assert saved.result_media_id == 30
    assert saved.failure_code == ""


def test_an_unknown_submission_is_not_found():
    repository = FakePhotoSubmissionRepository(rows=[make_submission()])
    use_case = FailExhaustedProcessing(repository=repository)

    with pytest.raises(NotFoundError):
        use_case(ANIME, submission_id=1)
