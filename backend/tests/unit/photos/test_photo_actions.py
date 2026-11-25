from datetime import UTC, datetime

import pytest

from apps.catalog.services import StoreMismatch
from apps.photos.application.apply_photo import ApplyPhoto
from apps.photos.application.change_group_photo_links import ChangeGroupPhotoLinks
from apps.photos.application.discard_photo import DiscardPhoto
from apps.photos.application.redo_photo import RedoPhoto
from apps.photos.application.remove_photo import RemovePhoto
from apps.photos.application.retry_photo import RetryPhoto
from apps.photos.domain.errors import (
    AttemptsExhausted,
    CannotApply,
    CannotChangeGroupLinks,
    CannotDiscard,
    CannotRedo,
    CannotRemove,
    CannotStartProcessing,
    RedoExhausted,
)
from apps.photos.domain.submission import (
    MAX_ATTEMPTS,
    MAX_REDOS,
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
    FakeUnitOfWork,
    make_media,
    make_product,
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


@pytest.fixture
def unit_of_work():
    return FakeUnitOfWork()


def apply_photo(repository, catalog, authorizer, unit_of_work):
    return ApplyPhoto(
        repository=repository,
        catalog=catalog,
        authorizer=authorizer,
        unit_of_work=unit_of_work,
    )


def remove_photo(repository, catalog, authorizer, unit_of_work):
    return RemovePhoto(
        repository=repository,
        catalog=catalog,
        authorizer=authorizer,
        unit_of_work=unit_of_work,
    )


def change_group_links(repository, catalog, authorizer, unit_of_work):
    return ChangeGroupPhotoLinks(
        repository=repository,
        catalog=catalog,
        authorizer=authorizer,
        unit_of_work=unit_of_work,
    )


def redo_photo(repository, queue, authorizer, unit_of_work):
    return RedoPhoto(
        repository=repository,
        queue=queue,
        authorizer=authorizer,
        unit_of_work=unit_of_work,
    )


def retry_photo(repository, queue, authorizer, unit_of_work):
    return RetryPhoto(
        repository=repository,
        queue=queue,
        authorizer=authorizer,
        unit_of_work=unit_of_work,
    )


def discard_photo(repository, uploader, authorizer):
    return DiscardPhoto(repository=repository, uploader=uploader, authorizer=authorizer)


def test_apply_authorizes_catalog_manage_in_the_store(
    repository, catalog, authorizer, unit_of_work
):
    apply_photo(repository, catalog, authorizer, unit_of_work)(
        HOME, user_id=7, submission_id=1, now=NOW
    )

    assert authorizer.calls == [(7, HOME, MANAGE_CATALOG)]


def test_apply_rejects_a_user_without_catalog_manage(repository, catalog, unit_of_work):
    use_case = apply_photo(repository, catalog, FakeAuthorizer(allowed=False), unit_of_work)

    with pytest.raises(PermissionDeniedError):
        use_case(HOME, user_id=7, submission_id=1, now=NOW)

    assert catalog.append_calls == []
    assert repository.rows[1].applied_at is None


def test_apply_appends_the_ready_result_to_an_empty_carousel_as_the_cover(
    repository, catalog, authorizer, unit_of_work
):
    saved = apply_photo(repository, catalog, authorizer, unit_of_work)(
        HOME, user_id=7, submission_id=1, now=NOW
    )

    assert catalog.append_calls == [
        {
            "store": HOME,
            "product_id": 10,
            "media_id": 30,
            "variant_id": 20,
        }
    ]
    link = next(iter(catalog.images.values()))
    assert link.role.value == "main"
    assert link.position == 1
    assert saved.applied_at == NOW
    assert saved.applied_by_id == 7
    assert saved.status is SubmissionStatus.READY
    assert repository.rows[1].applied_at == NOW
    assert unit_of_work.committed == 1


def test_apply_appends_to_a_non_empty_carousel_at_the_end(
    repository, catalog, authorizer, unit_of_work
):
    cover = catalog.append_to_carousel(HOME, product_id=10, media_id=30)
    catalog.media[31] = make_media(media_id=31, content_hash="hash-2")
    repository.rows[1] = make_submission(result_media_id=31)

    apply_photo(repository, catalog, authorizer, unit_of_work)(
        HOME, user_id=7, submission_id=1, now=NOW
    )

    appended = catalog.images[2]
    assert appended.role.value == "gallery"
    assert appended.position == 2
    assert catalog.images[cover.id].role.value == "main"
    assert catalog.images[cover.id].is_active is True


def test_apply_refuses_a_group_photo(repository, catalog, authorizer, unit_of_work):
    repository.rows[1] = make_submission(kind=SubmissionKind.GROUP, result_media_id=30)

    with pytest.raises(CannotApply):
        apply_photo(repository, catalog, authorizer, unit_of_work)(
            HOME, user_id=7, submission_id=1, now=NOW
        )

    assert catalog.append_calls == []


@pytest.mark.parametrize(
    "status",
    [SubmissionStatus.UPLOADED, SubmissionStatus.PROCESSING, SubmissionStatus.FAILED],
)
def test_apply_refuses_a_submission_that_is_not_ready(
    repository, catalog, authorizer, unit_of_work, status
):
    repository.rows[1] = make_submission(status=status, result_media_id=None)

    with pytest.raises(CannotApply):
        apply_photo(repository, catalog, authorizer, unit_of_work)(
            HOME, user_id=7, submission_id=1, now=NOW
        )

    assert catalog.append_calls == []


def test_apply_never_finds_another_stores_submission(repository, catalog, authorizer, unit_of_work):
    with pytest.raises(NotFoundError):
        apply_photo(repository, catalog, authorizer, unit_of_work)(
            ANIME, user_id=7, submission_id=1, now=NOW
        )


class FailingSaveRepository(FakePhotoSubmissionRepository):
    def save(self, submission):
        raise RuntimeError("cannot save the submission")


def test_apply_rolls_the_unit_of_work_back_when_the_submission_save_fails(
    catalog, authorizer, unit_of_work
):
    repository = FailingSaveRepository(rows=[make_submission()])
    use_case = apply_photo(repository, catalog, authorizer, unit_of_work)

    with pytest.raises(RuntimeError):
        use_case(HOME, user_id=7, submission_id=1, now=NOW)

    assert unit_of_work.entered == 1
    assert unit_of_work.rolled_back == 1
    assert unit_of_work.committed == 0


def test_remove_authorizes_catalog_manage_in_the_store(
    repository, catalog, authorizer, unit_of_work
):
    repository.rows[1] = make_submission(applied_at=NOW, applied_by_id=7)
    catalog.append_to_carousel(HOME, product_id=10, media_id=30)

    remove_photo(repository, catalog, authorizer, unit_of_work)(HOME, user_id=7, submission_id=1)

    assert authorizer.calls == [(7, HOME, MANAGE_CATALOG)]


def test_remove_rejects_a_user_without_catalog_manage(repository, catalog, unit_of_work):
    repository.rows[1] = make_submission(applied_at=NOW, applied_by_id=7)
    use_case = remove_photo(repository, catalog, FakeAuthorizer(allowed=False), unit_of_work)

    with pytest.raises(PermissionDeniedError):
        use_case(HOME, user_id=7, submission_id=1)

    assert catalog.remove_calls == []
    assert repository.rows[1].applied_at == NOW


def test_remove_deactivates_the_carousel_link_and_clears_the_application(
    repository, catalog, authorizer, unit_of_work
):
    repository.rows[1] = make_submission(applied_at=NOW, applied_by_id=7)
    cover = catalog.append_to_carousel(HOME, product_id=10, media_id=30)

    saved = remove_photo(repository, catalog, authorizer, unit_of_work)(
        HOME, user_id=7, submission_id=1
    )

    assert catalog.remove_calls == [{"store": HOME, "product_id": 10, "media_id": 30}]
    assert catalog.images[cover.id].is_active is False
    assert saved.applied_at is None
    assert saved.applied_by_id is None
    assert saved.result_media_id == 30
    assert unit_of_work.committed == 1


def test_remove_promotes_the_next_image_to_cover(repository, catalog, authorizer, unit_of_work):
    repository.rows[1] = make_submission(applied_at=NOW, applied_by_id=7)
    cover = catalog.append_to_carousel(HOME, product_id=10, media_id=30)
    catalog.media[31] = make_media(media_id=31, content_hash="hash-2")
    next_image = catalog.append_to_carousel(HOME, product_id=10, media_id=31)

    remove_photo(repository, catalog, authorizer, unit_of_work)(HOME, user_id=7, submission_id=1)

    assert catalog.images[cover.id].is_active is False
    assert catalog.images[next_image.id].role.value == "main"
    assert catalog.images[next_image.id].position == 2


def test_remove_refuses_a_submission_that_is_not_applied(
    repository, catalog, authorizer, unit_of_work
):
    with pytest.raises(CannotRemove):
        remove_photo(repository, catalog, authorizer, unit_of_work)(
            HOME, user_id=7, submission_id=1
        )

    assert catalog.remove_calls == []


def test_remove_refuses_an_applied_group_photo_before_touching_the_catalog(
    repository, catalog, authorizer, unit_of_work
):
    repository.rows[1] = make_submission(kind=SubmissionKind.GROUP, applied_at=NOW, applied_by_id=7)

    with pytest.raises(CannotRemove) as error:
        remove_photo(repository, catalog, authorizer, unit_of_work)(
            HOME, user_id=7, submission_id=1
        )

    assert "links" in str(error.value)
    assert catalog.remove_calls == []
    assert repository.rows[1].applied_at == NOW


def test_remove_never_finds_another_stores_submission(
    repository, catalog, authorizer, unit_of_work
):
    repository.rows[1] = make_submission(applied_at=NOW, applied_by_id=7)

    with pytest.raises(NotFoundError):
        remove_photo(repository, catalog, authorizer, unit_of_work)(
            ANIME, user_id=7, submission_id=1
        )

    assert repository.rows[1].applied_at == NOW


def test_redo_authorizes_catalog_manage_in_the_store(repository, queue, authorizer, unit_of_work):
    redo_photo(repository, queue, authorizer, unit_of_work)(
        HOME, user_id=7, submission_id=1, corners=CORNERS, crop=CROP
    )

    assert authorizer.calls == [(7, HOME, MANAGE_CATALOG)]


def test_redo_rejects_a_user_without_catalog_manage(repository, queue, unit_of_work):
    use_case = redo_photo(repository, queue, FakeAuthorizer(allowed=False), unit_of_work)

    with pytest.raises(PermissionDeniedError):
        use_case(HOME, user_id=7, submission_id=1, corners=CORNERS, crop=CROP)

    assert queue.calls == []
    assert repository.rows[1].result_media_id == 30


def test_redo_moves_to_processing_keeps_the_old_media_and_enqueues(
    repository, queue, authorizer, unit_of_work
):
    saved = redo_photo(repository, queue, authorizer, unit_of_work)(
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


def test_redo_keeps_the_stored_corners_and_crop_when_omitted(
    repository, queue, authorizer, unit_of_work
):
    saved = redo_photo(repository, queue, authorizer, unit_of_work)(
        HOME, user_id=7, submission_id=1
    )

    assert saved.corners == CORNERS
    assert saved.crop == CROP
    assert queue.calls == [(HOME, 1)]


def test_redo_from_failed_saves_the_new_corners_and_enqueues_once(
    repository, queue, authorizer, unit_of_work
):
    repository.rows[1] = make_submission(
        status=SubmissionStatus.FAILED,
        result_media_id=None,
        failure_code="quad_out_of_bounds",
        failure_message="Corners outside the photo.",
    )
    new_corners = [{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2}, {"x": 0.8, "y": 0.8}]

    saved = redo_photo(repository, queue, authorizer, unit_of_work)(
        HOME, user_id=7, submission_id=1, corners=new_corners
    )

    assert saved.status is SubmissionStatus.PROCESSING
    assert saved.corners == new_corners
    assert saved.crop == CROP
    assert saved.redos == 1
    assert saved.attempts == 1
    assert saved.failure_code == ""
    assert repository.rows[1].corners == new_corners
    assert queue.calls == [(HOME, 1)]


def test_redo_records_the_failure_when_enqueueing_raises():
    repository = FakePhotoSubmissionRepository(rows=[make_submission()], detached=True)
    queue = FakeProcessingQueue(error=RuntimeError("the broker refused the message"))
    unit_of_work = FakeUnitOfWork(repository=repository)

    saved = redo_photo(repository, queue, FakeAuthorizer(), unit_of_work)(
        HOME,
        user_id=7,
        submission_id=1,
        corners=[{"x": 0.2, "y": 0.2}],
        crop={"x": 2, "y": 2, "width": 6, "height": 8},
    )

    assert saved.status is SubmissionStatus.FAILED
    assert saved.failure_code == "photo_processing_unavailable"
    assert unit_of_work.committed == 1
    assert unit_of_work.rolled_back == 0
    assert queue.calls == [(HOME, 1)]
    stored = repository.rows[1]
    assert stored.status is SubmissionStatus.FAILED
    assert stored.failure_code == "photo_processing_unavailable"
    assert stored.result_media_id is None
    assert stored.redos == 1
    assert stored.corners == [{"x": 0.2, "y": 0.2}]
    assert stored.crop == {"x": 2, "y": 2, "width": 6, "height": 8}


def test_retry_records_the_failure_when_enqueueing_raises():
    repository = FakePhotoSubmissionRepository(
        rows=[make_submission(status=SubmissionStatus.FAILED, attempts=1)],
        detached=True,
    )
    queue = FakeProcessingQueue(error=RuntimeError("the broker refused the message"))
    unit_of_work = FakeUnitOfWork(repository=repository)

    saved = retry_photo(repository, queue, FakeAuthorizer(), unit_of_work)(
        HOME, user_id=7, submission_id=1
    )

    assert saved.status is SubmissionStatus.FAILED
    assert saved.failure_code == "photo_processing_unavailable"
    assert unit_of_work.committed == 1
    assert unit_of_work.rolled_back == 0
    assert queue.calls == [(HOME, 1)]
    stored = repository.rows[1]
    assert stored.status is SubmissionStatus.FAILED
    assert stored.failure_code == "photo_processing_unavailable"
    assert stored.attempts == 2
    assert stored.corners == CORNERS
    assert stored.crop == CROP


def test_redo_refuses_the_sixth_redo_without_enqueueing(
    repository, queue, authorizer, unit_of_work
):
    repository.rows[1] = make_submission(status=SubmissionStatus.FAILED, redos=MAX_REDOS)

    with pytest.raises(RedoExhausted):
        redo_photo(repository, queue, authorizer, unit_of_work)(
            HOME, user_id=7, submission_id=1, corners=CORNERS, crop=CROP
        )

    assert queue.calls == []
    assert repository.rows[1].corners == CORNERS


def test_redo_refuses_a_submission_that_is_still_processing(
    repository, queue, authorizer, unit_of_work
):
    repository.rows[1] = make_submission(status=SubmissionStatus.PROCESSING)

    with pytest.raises(CannotRedo):
        redo_photo(repository, queue, authorizer, unit_of_work)(
            HOME, user_id=7, submission_id=1, corners=CORNERS, crop=CROP
        )

    assert queue.calls == []


def test_redo_never_finds_another_stores_submission(repository, queue, authorizer, unit_of_work):
    with pytest.raises(NotFoundError):
        redo_photo(repository, queue, authorizer, unit_of_work)(
            ANIME, user_id=7, submission_id=1, corners=CORNERS, crop=CROP
        )


def test_retry_authorizes_catalog_manage_in_the_store(repository, queue, authorizer, unit_of_work):
    repository.rows[1] = make_submission(status=SubmissionStatus.FAILED)

    retry_photo(repository, queue, authorizer, unit_of_work)(HOME, user_id=7, submission_id=1)

    assert authorizer.calls == [(7, HOME, MANAGE_CATALOG)]


def test_retry_rejects_a_user_without_catalog_manage(repository, queue, unit_of_work):
    repository.rows[1] = make_submission(status=SubmissionStatus.FAILED)
    use_case = retry_photo(repository, queue, FakeAuthorizer(allowed=False), unit_of_work)

    with pytest.raises(PermissionDeniedError):
        use_case(HOME, user_id=7, submission_id=1)

    assert queue.calls == []


def test_retry_starts_a_new_attempt_and_enqueues(repository, queue, authorizer, unit_of_work):
    repository.rows[1] = make_submission(status=SubmissionStatus.FAILED, attempts=1)

    saved = retry_photo(repository, queue, authorizer, unit_of_work)(
        HOME, user_id=7, submission_id=1
    )

    assert saved.status is SubmissionStatus.PROCESSING
    assert saved.attempts == 2
    assert saved.failure_code == ""
    assert queue.calls == [(HOME, 1)]


@pytest.mark.parametrize(
    "status",
    [SubmissionStatus.UPLOADED, SubmissionStatus.READY, SubmissionStatus.PROCESSING],
)
def test_retry_refuses_a_submission_that_did_not_fail(
    repository, queue, authorizer, unit_of_work, status
):
    repository.rows[1] = make_submission(status=status, result_media_id=None)

    with pytest.raises(CannotStartProcessing):
        retry_photo(repository, queue, authorizer, unit_of_work)(HOME, user_id=7, submission_id=1)

    assert queue.calls == []


def test_retry_refuses_an_exhausted_submission(repository, queue, authorizer, unit_of_work):
    repository.rows[1] = make_submission(status=SubmissionStatus.FAILED, attempts=MAX_ATTEMPTS)

    with pytest.raises(AttemptsExhausted):
        retry_photo(repository, queue, authorizer, unit_of_work)(HOME, user_id=7, submission_id=1)

    assert queue.calls == []


def test_retry_never_finds_another_stores_submission(repository, queue, authorizer, unit_of_work):
    repository.rows[1] = make_submission(status=SubmissionStatus.FAILED)

    with pytest.raises(NotFoundError):
        retry_photo(repository, queue, authorizer, unit_of_work)(ANIME, user_id=7, submission_id=1)


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


def group_catalog(*product_ids):
    return FakeCatalog(
        products=[make_product(product_id) for product_id in product_ids],
        media=[make_media()],
    )


def test_group_apply_authorizes_catalog_manage_in_the_store(repository, authorizer, unit_of_work):
    catalog = group_catalog(10, 11)
    repository.rows[1] = make_submission(kind=SubmissionKind.GROUP)

    apply_photo(repository, catalog, authorizer, unit_of_work)(
        HOME, user_id=7, submission_id=1, product_ids=[10], now=NOW
    )

    assert authorizer.calls == [(7, HOME, MANAGE_CATALOG)]


def test_group_apply_links_the_one_media_to_every_selected_product(
    repository, authorizer, unit_of_work
):
    catalog = group_catalog(10, 11)
    repository.rows[1] = make_submission(kind=SubmissionKind.GROUP, result_media_id=30)

    saved = apply_photo(repository, catalog, authorizer, unit_of_work)(
        HOME, user_id=7, submission_id=1, product_ids=[11, 10], now=NOW
    )

    links = list(catalog.images.values())
    assert {link.product_id for link in links} == {10, 11}
    assert {link.media_id for link in links} == {30}
    assert all(link.is_active for link in links)
    assert saved.applied_at == NOW
    assert saved.applied_by_id == 7
    assert saved.result_media_id == 30
    assert unit_of_work.committed == 1


def test_group_apply_appends_a_gallery_image_when_the_product_has_a_cover(
    repository, authorizer, unit_of_work
):
    catalog = group_catalog(10)
    cover = catalog.append_to_carousel(HOME, product_id=10, media_id=40)
    repository.rows[1] = make_submission(kind=SubmissionKind.GROUP, result_media_id=30)

    apply_photo(repository, catalog, authorizer, unit_of_work)(
        HOME, user_id=7, submission_id=1, product_ids=[10], now=NOW
    )

    appended = next(link for link in catalog.images.values() if link.media_id == 30)
    assert appended.role.value == "gallery"
    assert appended.position == cover.position + 1
    assert catalog.images[cover.id].role.value == "main"


def test_group_apply_refuses_an_empty_selection(repository, authorizer, unit_of_work):
    catalog = group_catalog(10, 11)
    repository.rows[1] = make_submission(kind=SubmissionKind.GROUP)

    with pytest.raises(CannotApply):
        apply_photo(repository, catalog, authorizer, unit_of_work)(
            HOME, user_id=7, submission_id=1, product_ids=[], now=NOW
        )

    assert catalog.images == {}
    assert repository.rows[1].applied_at is None


def test_group_apply_refuses_products_of_another_store(repository, authorizer, unit_of_work):
    catalog = group_catalog(10)
    repository.rows[1] = make_submission(kind=SubmissionKind.GROUP)

    with pytest.raises(StoreMismatch):
        apply_photo(repository, catalog, authorizer, unit_of_work)(
            HOME, user_id=7, submission_id=1, product_ids=[10, 99], now=NOW
        )

    assert catalog.images == {}
    assert repository.rows[1].applied_at is None


def test_group_apply_refuses_a_photo_that_is_not_ready(repository, authorizer, unit_of_work):
    catalog = group_catalog(10)
    repository.rows[1] = make_submission(
        kind=SubmissionKind.GROUP,
        status=SubmissionStatus.FAILED,
        result_media_id=None,
    )

    with pytest.raises(CannotApply):
        apply_photo(repository, catalog, authorizer, unit_of_work)(
            HOME, user_id=7, submission_id=1, product_ids=[10], now=NOW
        )

    assert catalog.images == {}


def test_group_links_change_authorizes_catalog_manage_in_the_store(repository, unit_of_work):
    catalog = group_catalog(10, 11)
    repository.rows[1] = make_submission(kind=SubmissionKind.GROUP, applied_at=NOW, applied_by_id=7)
    authorizer = FakeAuthorizer()

    change_group_links(repository, catalog, authorizer, unit_of_work)(
        HOME, user_id=7, submission_id=1, product_ids=[10]
    )

    assert authorizer.calls == [(7, HOME, MANAGE_CATALOG)]


def test_group_links_add_remove_and_keep_retained_positions(repository, authorizer, unit_of_work):
    catalog = group_catalog(10, 11, 12)
    catalog.append_to_carousel(HOME, product_id=10, media_id=40)
    retained = catalog.append_to_carousel(HOME, product_id=10, media_id=30)
    catalog.append_to_carousel(HOME, product_id=11, media_id=41)
    removed = catalog.append_to_carousel(HOME, product_id=11, media_id=30)
    repository.rows[1] = make_submission(kind=SubmissionKind.GROUP, applied_at=NOW, applied_by_id=7)

    change_group_links(repository, catalog, authorizer, unit_of_work)(
        HOME, user_id=7, submission_id=1, product_ids=[10, 12]
    )

    assert catalog.images[retained.id].is_active is True
    assert catalog.images[retained.id].position == retained.position
    assert catalog.images[removed.id].is_active is False
    assert catalog.images[removed.id].role.value == "gallery"
    added = next(
        link for link in catalog.images.values() if link.product_id == 12 and link.media_id == 30
    )
    assert added.is_active is True
    assert added.role.value == "main"


def test_group_links_reactivate_a_removed_product_without_a_duplicate(
    repository, authorizer, unit_of_work
):
    catalog = group_catalog(10, 11)
    catalog.append_to_carousel(HOME, product_id=11, media_id=41)
    removed = catalog.append_to_carousel(HOME, product_id=11, media_id=30)
    repository.rows[1] = make_submission(kind=SubmissionKind.GROUP, applied_at=NOW, applied_by_id=7)
    use_case = change_group_links(repository, catalog, authorizer, unit_of_work)
    use_case(HOME, user_id=7, submission_id=1, product_ids=[10])

    use_case(HOME, user_id=7, submission_id=1, product_ids=[10, 11])

    restored = catalog.images[removed.id]
    assert restored.id == removed.id
    assert restored.is_active is True
    assert (
        len(
            [
                link
                for link in catalog.images.values()
                if link.product_id == 11 and link.media_id == 30
            ]
        )
        == 1
    )


def test_group_links_can_remove_every_link(repository, authorizer, unit_of_work):
    catalog = group_catalog(10, 11)
    first = catalog.append_to_carousel(HOME, product_id=10, media_id=30)
    second = catalog.append_to_carousel(HOME, product_id=11, media_id=30)
    repository.rows[1] = make_submission(kind=SubmissionKind.GROUP, applied_at=NOW, applied_by_id=7)

    change_group_links(repository, catalog, authorizer, unit_of_work)(
        HOME, user_id=7, submission_id=1, product_ids=[]
    )

    assert catalog.images[first.id].is_active is False
    assert catalog.images[second.id].is_active is False
    assert len(catalog.images) == 2


def test_group_links_refuse_a_submission_that_is_not_applied(repository, authorizer, unit_of_work):
    catalog = group_catalog(10)
    repository.rows[1] = make_submission(kind=SubmissionKind.GROUP)

    with pytest.raises(CannotChangeGroupLinks):
        change_group_links(repository, catalog, authorizer, unit_of_work)(
            HOME, user_id=7, submission_id=1, product_ids=[10]
        )

    assert catalog.images == {}


def test_group_links_refuse_an_individual_photo(repository, authorizer, unit_of_work):
    catalog = group_catalog(10)
    repository.rows[1] = make_submission(applied_at=NOW, applied_by_id=7)

    with pytest.raises(CannotChangeGroupLinks):
        change_group_links(repository, catalog, authorizer, unit_of_work)(
            HOME, user_id=7, submission_id=1, product_ids=[10]
        )

    assert catalog.images == {}


def test_group_links_never_find_another_stores_submission(repository, authorizer, unit_of_work):
    catalog = group_catalog(10)
    repository.rows[1] = make_submission(kind=SubmissionKind.GROUP, applied_at=NOW, applied_by_id=7)

    with pytest.raises(NotFoundError):
        change_group_links(repository, catalog, authorizer, unit_of_work)(
            ANIME, user_id=7, submission_id=1, product_ids=[10]
        )

    assert catalog.images == {}
