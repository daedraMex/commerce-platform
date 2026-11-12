from datetime import UTC, datetime

import pytest

from apps.photos.application.apply_photo import ApplyPhoto
from apps.photos.application.discard_photo import DiscardPhoto
from apps.photos.application.redo_photo import RedoPhoto
from apps.photos.application.retry_photo import RetryPhoto
from apps.photos.domain.errors import (
    AttemptsExhausted,
    CannotApply,
    CannotDiscard,
    CannotRedo,
    CannotStartProcessing,
)
from apps.photos.domain.submission import (
    MAX_ATTEMPTS,
    PhotoSubmission,
    SubmissionKind,
    SubmissionStatus,
)
from apps.shared.domain.exceptions import NotFoundError, PermissionDeniedError
from apps.shared.domain.permissions import MANAGE_CATALOG
from apps.shared.domain.store import StoreReference
from tests.unit.photos.fakes import (
    FakeAuthorizer,
    FakeCatalog,
    FakeMediaUploader,
    FakePhotoSubmissionRepository,
    FakeProcessingQueue,
    make_media,
)

HOME = StoreReference(id=1, slug="home")
ANIME = StoreReference(id=2, slug="anime")
NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
CORNERS = [
    {"x": 0.1, "y": 0.1},
    {"x": 0.9, "y": 0.1},
    {"x": 0.9, "y": 0.9},
    {"x": 0.1, "y": 0.9},
]
CROP = {"x": 1, "y": 1, "width": 8, "height": 10}


def make_submission(store=HOME, *, submission_id=1, **overrides):
    kind = overrides.pop("kind", SubmissionKind.RECTANGLE)
    values = {
        "id": submission_id,
        "store_id": store.id,
        "created_by_id": 7,
        "kind": kind,
        "target_product_id": overrides.pop("target_product_id", 10)
        if kind in (SubmissionKind.RECTANGLE, SubmissionKind.CONTOUR)
        else None,
        "photographed_variant_id": overrides.pop("photographed_variant_id", 20)
        if kind in (SubmissionKind.RECTANGLE, SubmissionKind.CONTOUR)
        else None,
        "idempotency_key": f"key-{submission_id}",
        "request_fingerprint": "a" * 64,
        "status": SubmissionStatus.READY,
        "result_media_id": 30,
        "attempts": 1,
        "original_key": f"stores/{store.id}/photos/originals/original.jpg",
        "preview_key": f"stores/{store.id}/photos/previews/preview.jpg",
        "corners": CORNERS,
        "crop": CROP,
    }
    values.update(overrides)
    return PhotoSubmission(**values)


@pytest.fixture
def repository():
    return FakePhotoSubmissionRepository(rows=[make_submission()])


@pytest.fixture
def catalog():
    return FakeCatalog(media=[make_media()])


@pytest.fixture
def authorizer():
    return FakeAuthorizer()


@pytest.fixture
def queue():
    return FakeProcessingQueue()


@pytest.fixture
def uploader():
    return FakeMediaUploader()


def apply_photo(repository, catalog, authorizer):
    return ApplyPhoto(repository=repository, catalog=catalog, authorizer=authorizer)


def redo_photo(repository, queue, authorizer):
    return RedoPhoto(repository=repository, queue=queue, authorizer=authorizer)


def retry_photo(repository, queue, authorizer):
    return RetryPhoto(repository=repository, queue=queue, authorizer=authorizer)


def discard_photo(repository, uploader, authorizer):
    return DiscardPhoto(repository=repository, uploader=uploader, authorizer=authorizer)


def test_apply_authorizes_catalog_manage_in_the_store(repository, catalog, authorizer):
    apply_photo(repository, catalog, authorizer)(HOME, user_id=7, submission_id=1, now=NOW)

    assert authorizer.calls == [(7, HOME, MANAGE_CATALOG)]


def test_apply_rejects_a_user_without_catalog_manage(repository, catalog):
    use_case = apply_photo(repository, catalog, FakeAuthorizer(allowed=False))

    with pytest.raises(PermissionDeniedError):
        use_case(HOME, user_id=7, submission_id=1, now=NOW)

    assert catalog.main_calls == []
    assert repository.rows[1].applied_at is None


def test_apply_links_the_ready_result_as_the_main_image(repository, catalog, authorizer):
    saved = apply_photo(repository, catalog, authorizer)(HOME, user_id=7, submission_id=1, now=NOW)

    assert catalog.main_calls == [
        {
            "store": HOME,
            "product_id": 10,
            "media_id": 30,
            "variant_id": 20,
            "position": None,
        }
    ]
    assert saved.applied_at == NOW
    assert saved.applied_by_id == 7
    assert saved.status is SubmissionStatus.READY
    assert repository.rows[1].applied_at == NOW


def test_apply_refuses_a_group_photo(repository, catalog, authorizer):
    repository.rows[1] = make_submission(kind=SubmissionKind.GROUP, result_media_id=30)

    with pytest.raises(CannotApply):
        apply_photo(repository, catalog, authorizer)(HOME, user_id=7, submission_id=1, now=NOW)

    assert catalog.main_calls == []


@pytest.mark.parametrize(
    "status",
    [SubmissionStatus.UPLOADED, SubmissionStatus.PROCESSING, SubmissionStatus.FAILED],
)
def test_apply_refuses_a_submission_that_is_not_ready(repository, catalog, authorizer, status):
    repository.rows[1] = make_submission(status=status, result_media_id=None)

    with pytest.raises(CannotApply):
        apply_photo(repository, catalog, authorizer)(HOME, user_id=7, submission_id=1, now=NOW)

    assert catalog.main_calls == []


def test_apply_never_finds_another_stores_submission(repository, catalog, authorizer):
    with pytest.raises(NotFoundError):
        apply_photo(repository, catalog, authorizer)(ANIME, user_id=7, submission_id=1, now=NOW)


def test_redo_authorizes_catalog_manage_in_the_store(repository, queue, authorizer):
    redo_photo(repository, queue, authorizer)(
        HOME, user_id=7, submission_id=1, corners=CORNERS, crop=CROP
    )

    assert authorizer.calls == [(7, HOME, MANAGE_CATALOG)]


def test_redo_rejects_a_user_without_catalog_manage(repository, queue):
    use_case = redo_photo(repository, queue, FakeAuthorizer(allowed=False))

    with pytest.raises(PermissionDeniedError):
        use_case(HOME, user_id=7, submission_id=1, corners=CORNERS, crop=CROP)

    assert queue.calls == []
    assert repository.rows[1].result_media_id == 30


def test_redo_moves_to_processing_keeps_the_old_media_and_enqueues(repository, queue, authorizer):
    saved = redo_photo(repository, queue, authorizer)(
        HOME,
        user_id=7,
        submission_id=1,
        corners=[{"x": 0.2, "y": 0.2}],
        crop={"x": 2, "y": 2, "width": 6, "height": 8},
    )

    assert saved.status is SubmissionStatus.PROCESSING
    assert saved.result_media_id is None
    assert saved.corners == [{"x": 0.2, "y": 0.2}]
    assert saved.crop == {"x": 2, "y": 2, "width": 6, "height": 8}
    assert queue.calls == [(HOME, 1)]


def test_redo_keeps_the_stored_corners_and_crop_when_omitted(repository, queue, authorizer):
    saved = redo_photo(repository, queue, authorizer)(HOME, user_id=7, submission_id=1)

    assert saved.corners == CORNERS
    assert saved.crop == CROP
    assert queue.calls == [(HOME, 1)]


def test_redo_refuses_a_submission_that_is_not_ready(repository, queue, authorizer):
    repository.rows[1] = make_submission(status=SubmissionStatus.FAILED)

    with pytest.raises(CannotRedo):
        redo_photo(repository, queue, authorizer)(
            HOME, user_id=7, submission_id=1, corners=CORNERS, crop=CROP
        )

    assert queue.calls == []


def test_redo_never_finds_another_stores_submission(repository, queue, authorizer):
    with pytest.raises(NotFoundError):
        redo_photo(repository, queue, authorizer)(
            ANIME, user_id=7, submission_id=1, corners=CORNERS, crop=CROP
        )


def test_retry_authorizes_catalog_manage_in_the_store(repository, queue, authorizer):
    repository.rows[1] = make_submission(status=SubmissionStatus.FAILED)

    retry_photo(repository, queue, authorizer)(HOME, user_id=7, submission_id=1)

    assert authorizer.calls == [(7, HOME, MANAGE_CATALOG)]


def test_retry_rejects_a_user_without_catalog_manage(repository, queue):
    repository.rows[1] = make_submission(status=SubmissionStatus.FAILED)
    use_case = retry_photo(repository, queue, FakeAuthorizer(allowed=False))

    with pytest.raises(PermissionDeniedError):
        use_case(HOME, user_id=7, submission_id=1)

    assert queue.calls == []


def test_retry_starts_a_new_attempt_and_enqueues(repository, queue, authorizer):
    repository.rows[1] = make_submission(status=SubmissionStatus.FAILED, attempts=1)

    saved = retry_photo(repository, queue, authorizer)(HOME, user_id=7, submission_id=1)

    assert saved.status is SubmissionStatus.PROCESSING
    assert saved.attempts == 2
    assert saved.failure_code == ""
    assert queue.calls == [(HOME, 1)]


@pytest.mark.parametrize(
    "status",
    [SubmissionStatus.UPLOADED, SubmissionStatus.READY, SubmissionStatus.PROCESSING],
)
def test_retry_refuses_a_submission_that_did_not_fail(repository, queue, authorizer, status):
    repository.rows[1] = make_submission(status=status, result_media_id=None)

    with pytest.raises(CannotStartProcessing):
        retry_photo(repository, queue, authorizer)(HOME, user_id=7, submission_id=1)

    assert queue.calls == []


def test_retry_refuses_an_exhausted_submission(repository, queue, authorizer):
    repository.rows[1] = make_submission(status=SubmissionStatus.FAILED, attempts=MAX_ATTEMPTS)

    with pytest.raises(AttemptsExhausted):
        retry_photo(repository, queue, authorizer)(HOME, user_id=7, submission_id=1)

    assert queue.calls == []


def test_retry_never_finds_another_stores_submission(repository, queue, authorizer):
    repository.rows[1] = make_submission(status=SubmissionStatus.FAILED)

    with pytest.raises(NotFoundError):
        retry_photo(repository, queue, authorizer)(ANIME, user_id=7, submission_id=1)


def test_discard_authorizes_catalog_manage_in_the_store(repository, uploader, authorizer):
    repository.rows[1] = make_submission(status=SubmissionStatus.UPLOADED, result_media_id=None)

    discard_photo(repository, uploader, authorizer)(HOME, user_id=7, submission_id=1, now=NOW)

    assert authorizer.calls == [(7, HOME, MANAGE_CATALOG)]


def test_discard_rejects_a_user_without_catalog_manage(repository, uploader):
    use_case = discard_photo(repository, uploader, FakeAuthorizer(allowed=False))

    with pytest.raises(PermissionDeniedError):
        use_case(HOME, user_id=7, submission_id=1, now=NOW)

    assert uploader.deleted == []
    assert repository.rows[1].discarded_at is None


def test_discard_stamps_the_submission_and_deletes_only_its_private_files(
    repository, uploader, authorizer
):
    repository.rows[1] = make_submission(status=SubmissionStatus.UPLOADED, result_media_id=None)

    saved = discard_photo(repository, uploader, authorizer)(
        HOME, user_id=7, submission_id=1, now=NOW
    )

    assert saved.discarded_at == NOW
    assert uploader.deleted == [
        (HOME, "stores/1/photos/originals/original.jpg"),
        (HOME, "stores/1/photos/previews/preview.jpg"),
    ]


def test_discard_refuses_an_applied_submission(repository, uploader, authorizer):
    repository.rows[1] = make_submission(applied_at=NOW, applied_by_id=7)

    with pytest.raises(CannotDiscard):
        discard_photo(repository, uploader, authorizer)(HOME, user_id=7, submission_id=1, now=NOW)

    assert uploader.deleted == []


def test_discard_refuses_an_already_discarded_submission(repository, uploader, authorizer):
    repository.rows[1] = make_submission(discarded_at=NOW)

    with pytest.raises(CannotDiscard):
        discard_photo(repository, uploader, authorizer)(HOME, user_id=7, submission_id=1, now=NOW)

    assert uploader.deleted == []


def test_discard_never_finds_another_stores_submission(repository, uploader, authorizer):
    with pytest.raises(NotFoundError):
        discard_photo(repository, uploader, authorizer)(ANIME, user_id=7, submission_id=1, now=NOW)
