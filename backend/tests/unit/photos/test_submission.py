from copy import deepcopy
from datetime import UTC, datetime

import pytest

from apps.photos.domain.errors import (
    AttemptsExhausted,
    CannotApply,
    CannotDiscard,
    CannotMarkFailed,
    CannotMarkReady,
    CannotRedo,
    CannotStartProcessing,
    ConcurrentModification,
    IdempotencyConflict,
    InvalidSubmissionTarget,
)
from apps.photos.domain.submission import (
    MAX_ATTEMPTS,
    PhotoSubmission,
    SubmissionKind,
    SubmissionStatus,
    resolve_replay,
)
from apps.shared.domain.store import StoreReference

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
CORNERS = [{"x": 1, "y": 2}, {"x": 3, "y": 4}, {"x": 5, "y": 6}, {"x": 7, "y": 8}]
CROP = {"x": 0, "y": 0, "width": 800, "height": 1000}


def make_submission(**overrides):
    values = {
        "store_id": 1,
        "created_by_id": 2,
        "kind": SubmissionKind.RECTANGLE,
        "target_product_id": 10,
        "idempotency_key": "key-1",
        "request_fingerprint": "fingerprint-1",
    }
    values.update(overrides)
    return PhotoSubmission(**values)


@pytest.mark.parametrize(
    ("status", "attempts", "expected_attempts"),
    [
        (SubmissionStatus.UPLOADED, 0, 1),
        (SubmissionStatus.FAILED, 1, 2),
    ],
)
def test_start_processing_moves_uploaded_or_failed_to_processing(
    status, attempts, expected_attempts
):
    submission = make_submission(status=status, attempts=attempts)

    submission.start_processing()

    assert submission.status is SubmissionStatus.PROCESSING
    assert submission.attempts == expected_attempts


@pytest.mark.parametrize("status", [SubmissionStatus.PROCESSING, SubmissionStatus.READY])
def test_start_processing_refuses_other_states(status):
    submission = make_submission(status=status)

    with pytest.raises(CannotStartProcessing) as error:
        submission.start_processing()

    assert error.value.code == "submission_cannot_start_processing"
    assert submission.status is status


def test_start_processing_allows_the_last_attempt():
    submission = make_submission(status=SubmissionStatus.FAILED, attempts=MAX_ATTEMPTS - 1)

    submission.start_processing()

    assert submission.attempts == MAX_ATTEMPTS
    assert submission.status is SubmissionStatus.PROCESSING


def test_start_processing_refuses_after_max_attempts():
    submission = make_submission(status=SubmissionStatus.FAILED, attempts=MAX_ATTEMPTS)

    with pytest.raises(AttemptsExhausted) as error:
        submission.start_processing()

    assert error.value.code == "submission_attempts_exhausted"
    assert submission.status is SubmissionStatus.FAILED
    assert submission.attempts == MAX_ATTEMPTS


@pytest.mark.parametrize("terminal", ["applied_at", "discarded_at"])
def test_start_processing_refuses_a_terminal_submission(terminal):
    submission = make_submission(status=SubmissionStatus.UPLOADED, **{terminal: NOW})

    with pytest.raises(CannotStartProcessing) as error:
        submission.start_processing()

    assert error.value.code == "submission_cannot_start_processing"
    assert submission.status is SubmissionStatus.UPLOADED
    assert submission.attempts == 0


def test_mark_ready_records_the_result_and_pipeline_version():
    submission = make_submission(status=SubmissionStatus.PROCESSING, attempts=1)

    submission.mark_ready(result_media_id=42, pipeline_version="2026-11-11.1")

    assert submission.status is SubmissionStatus.READY
    assert submission.result_media_id == 42
    assert submission.pipeline_version == "2026-11-11.1"


@pytest.mark.parametrize(
    "status",
    [SubmissionStatus.UPLOADED, SubmissionStatus.READY, SubmissionStatus.FAILED],
)
def test_mark_ready_refuses_other_states(status):
    submission = make_submission(status=status)

    with pytest.raises(CannotMarkReady) as error:
        submission.mark_ready(result_media_id=42, pipeline_version="v1")

    assert error.value.code == "submission_cannot_mark_ready"
    assert submission.status is status


def test_mark_ready_refuses_an_applied_submission():
    submission = make_submission(status=SubmissionStatus.PROCESSING, applied_at=NOW)

    with pytest.raises(CannotMarkReady) as error:
        submission.mark_ready(result_media_id=42, pipeline_version="v1")

    assert error.value.code == "submission_cannot_mark_ready"
    assert submission.status is SubmissionStatus.PROCESSING
    assert submission.result_media_id is None


def test_mark_ready_records_the_result_of_a_discarded_submission():
    submission = make_submission(status=SubmissionStatus.PROCESSING, discarded_at=NOW)

    submission.mark_ready(result_media_id=42, pipeline_version="v1")

    assert submission.status is SubmissionStatus.READY
    assert submission.result_media_id == 42
    assert submission.pipeline_version == "v1"


def test_mark_failed_records_the_failure():
    submission = make_submission(status=SubmissionStatus.PROCESSING)

    submission.mark_failed("decode_error", "Could not read the photo.")

    assert submission.status is SubmissionStatus.FAILED
    assert submission.failure_code == "decode_error"
    assert submission.failure_message == "Could not read the photo."


@pytest.mark.parametrize(
    "status",
    [SubmissionStatus.UPLOADED, SubmissionStatus.READY, SubmissionStatus.FAILED],
)
def test_mark_failed_refuses_other_states(status):
    submission = make_submission(status=status)

    with pytest.raises(CannotMarkFailed) as error:
        submission.mark_failed("decode_error", "Could not read the photo.")

    assert error.value.code == "submission_cannot_mark_failed"
    assert submission.status is status


def test_mark_failed_refuses_an_applied_submission():
    submission = make_submission(status=SubmissionStatus.PROCESSING, applied_at=NOW)

    with pytest.raises(CannotMarkFailed) as error:
        submission.mark_failed("decode_error", "Could not read the photo.")

    assert error.value.code == "submission_cannot_mark_failed"
    assert submission.status is SubmissionStatus.PROCESSING
    assert submission.failure_code == ""


def test_mark_failed_records_the_failure_of_a_discarded_submission():
    submission = make_submission(status=SubmissionStatus.PROCESSING, discarded_at=NOW)

    submission.mark_failed("decode_error", "Could not read the photo.")

    assert submission.status is SubmissionStatus.FAILED
    assert submission.failure_code == "decode_error"
    assert submission.failure_message == "Could not read the photo."


def test_redo_returns_the_previous_result_and_moves_to_processing():
    submission = make_submission(
        status=SubmissionStatus.READY,
        result_media_id=99,
        pipeline_version="v1",
    )

    previous_result = submission.redo(corners=CORNERS, crop=CROP)

    assert previous_result == 99
    assert submission.status is SubmissionStatus.PROCESSING
    assert submission.result_media_id is None
    assert submission.corners == CORNERS
    assert submission.crop == CROP


@pytest.mark.parametrize(
    "status",
    [SubmissionStatus.UPLOADED, SubmissionStatus.PROCESSING, SubmissionStatus.FAILED],
)
def test_redo_refuses_non_ready_submissions(status):
    submission = make_submission(status=status, result_media_id=99)

    with pytest.raises(CannotRedo) as error:
        submission.redo(corners=CORNERS, crop=CROP)

    assert error.value.code == "submission_cannot_redo"
    assert submission.status is status
    assert submission.result_media_id == 99


@pytest.mark.parametrize("terminal", ["applied_at", "discarded_at"])
def test_redo_refuses_a_terminal_submission(terminal):
    submission = make_submission(
        status=SubmissionStatus.READY,
        result_media_id=99,
        **{terminal: NOW},
    )

    with pytest.raises(CannotRedo) as error:
        submission.redo(corners=CORNERS, crop=CROP)

    assert error.value.code == "submission_cannot_redo"
    assert submission.status is SubmissionStatus.READY
    assert submission.result_media_id == 99


def test_apply_stamps_a_ready_submission_without_changing_its_status():
    submission = make_submission(status=SubmissionStatus.READY)

    submission.apply(user_id=7, now=NOW)

    assert submission.applied_at == NOW
    assert submission.applied_by_id == 7
    assert submission.status is SubmissionStatus.READY


@pytest.mark.parametrize(
    "status",
    [SubmissionStatus.UPLOADED, SubmissionStatus.PROCESSING, SubmissionStatus.FAILED],
)
def test_apply_refuses_a_submission_that_is_not_ready(status):
    submission = make_submission(status=status)

    with pytest.raises(CannotApply) as error:
        submission.apply(user_id=7, now=NOW)

    assert error.value.code == "submission_cannot_apply"
    assert submission.applied_at is None


def test_apply_refuses_a_discarded_submission():
    submission = make_submission(status=SubmissionStatus.READY, discarded_at=NOW)

    with pytest.raises(CannotApply) as error:
        submission.apply(user_id=7, now=NOW)

    assert error.value.code == "submission_cannot_apply"
    assert submission.applied_at is None


def test_apply_refuses_an_already_applied_submission():
    submission = make_submission(
        status=SubmissionStatus.READY,
        applied_at=NOW,
        applied_by_id=7,
    )

    with pytest.raises(CannotApply) as error:
        submission.apply(user_id=7, now=NOW)

    assert error.value.code == "submission_cannot_apply"


@pytest.mark.parametrize(
    "status",
    [
        SubmissionStatus.UPLOADED,
        SubmissionStatus.PROCESSING,
        SubmissionStatus.READY,
        SubmissionStatus.FAILED,
    ],
)
def test_discard_stamps_an_unapplied_submission(status):
    submission = make_submission(status=status)

    submission.discard(now=NOW)

    assert submission.discarded_at == NOW


def test_discard_refuses_an_applied_submission():
    submission = make_submission(
        status=SubmissionStatus.READY,
        applied_at=NOW,
        applied_by_id=7,
    )

    with pytest.raises(CannotDiscard) as error:
        submission.discard(now=NOW)

    assert error.value.code == "submission_cannot_discard"
    assert submission.discarded_at is None


def test_discard_refuses_an_already_discarded_submission():
    submission = make_submission(status=SubmissionStatus.READY, discarded_at=NOW)

    with pytest.raises(CannotDiscard) as error:
        submission.discard(now=NOW)

    assert error.value.code == "submission_cannot_discard"


def test_resolve_replay_returns_the_existing_submission_for_the_same_fingerprint():
    submission = make_submission(request_fingerprint="same-payload")

    assert resolve_replay(submission, "same-payload") is submission


def test_resolve_replay_raises_when_the_fingerprint_differs():
    submission = make_submission(request_fingerprint="same-payload")

    with pytest.raises(IdempotencyConflict) as error:
        resolve_replay(submission, "different-payload")

    assert error.value.code == "submission_idempotency_conflict"


def test_resolve_replay_without_an_existing_submission_returns_none():
    assert resolve_replay(None, "same-payload") is None


@pytest.mark.parametrize("kind", [SubmissionKind.RECTANGLE, SubmissionKind.CONTOUR])
def test_individual_kinds_require_a_target_product(kind):
    with pytest.raises(InvalidSubmissionTarget) as error:
        make_submission(kind=kind, target_product_id=None)

    assert error.value.code == "submission_invalid_target"


def test_group_photos_have_no_target_product():
    submission = make_submission(kind=SubmissionKind.GROUP, target_product_id=None)

    assert submission.kind is SubmissionKind.GROUP
    assert submission.target_product_id is None


def test_group_photos_refuse_a_target_product():
    with pytest.raises(InvalidSubmissionTarget) as error:
        make_submission(kind=SubmissionKind.GROUP, target_product_id=10)

    assert error.value.code == "submission_invalid_target"


def test_group_photos_refuse_a_photographed_variant():
    with pytest.raises(InvalidSubmissionTarget) as error:
        make_submission(
            kind=SubmissionKind.GROUP,
            target_product_id=None,
            photographed_variant_id=10,
        )

    assert error.value.code == "submission_invalid_target"


class FakePhotoSubmissionRepository:
    def __init__(self):
        self._rows = {}
        self._next_id = 1

    def get(self, store, submission_id):
        row = self._rows.get(submission_id)
        if row is None or row.store_id != store.id:
            return None
        return row

    def get_by_idempotency_key(self, store, created_by, key):
        for row in self._rows.values():
            if (
                row.store_id == store.id
                and row.created_by_id == created_by
                and row.idempotency_key == key
            ):
                return row
        return None

    def add(self, submission):
        submission.id = self._next_id
        submission.version = 0
        self._next_id += 1
        self._rows[submission.id] = submission
        return submission

    def save(self, submission):
        stored = self._rows.get(submission.id)
        if (
            stored is None
            or stored.store_id != submission.store_id
            or stored.version != submission.version
        ):
            raise ConcurrentModification(
                "This submission was changed by another request; reload it and try again."
            )
        stored.version += 1
        submission.version = stored.version
        return submission


def test_the_fake_repository_round_trips_and_scopes_to_the_store():
    repository = FakePhotoSubmissionRepository()
    home = StoreReference(id=1, slug="home")
    anime = StoreReference(id=2, slug="anime")
    submission = repository.add(make_submission())

    assert repository.get(home, submission.id) is submission
    assert repository.get(anime, submission.id) is None
    assert repository.get_by_idempotency_key(home, 2, "key-1") is submission
    assert repository.get_by_idempotency_key(anime, 2, "key-1") is None


def test_the_fake_repository_rejects_a_stale_copy():
    repository = FakePhotoSubmissionRepository()
    submission = repository.add(make_submission())
    first_reader = deepcopy(submission)
    stale_reader = deepcopy(submission)

    first_reader.start_processing()
    saved = repository.save(first_reader)

    assert saved.version == 1
    assert repository.get(StoreReference(id=1, slug="home"), submission.id).version == 1

    stale_reader.start_processing()
    with pytest.raises(ConcurrentModification) as error:
        repository.save(stale_reader)

    assert error.value.code == "submission_concurrent_modification"
    assert stale_reader.version == 0
