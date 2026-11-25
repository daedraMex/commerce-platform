import pytest

from apps.photos.application.upload_photo import UploadPhoto, UploadPhotoCommand
from apps.photos.domain.errors import IdempotencyConflict, InvalidSubmissionTarget
from apps.photos.domain.submission import SubmissionKind, SubmissionStatus
from apps.shared.domain.exceptions import PermissionDeniedError
from apps.shared.domain.permissions import MANAGE_CATALOG
from apps.shared.domain.store import StoreReference
from tests.unit.photos.fakes import (
    FakeAuthorizer,
    FakeCatalog,
    FakeMediaUploader,
    FakePhotoSubmissionRepository,
    FakeProcessingQueue,
    make_product,
    make_variant,
)

HOME = StoreReference(id=1, slug="home")
ANIME = StoreReference(id=2, slug="anime")


def command(**overrides):
    values = {
        "store": HOME,
        "user_id": 7,
        "kind": SubmissionKind.GROUP,
        "content": b"photo-bytes",
        "idempotency_key": "key-1",
        "target_product_id": None,
        "photographed_variant_id": None,
        "corners": None,
        "crop": None,
        "light_correction": True,
    }
    values.update(overrides)
    return UploadPhotoCommand(**values)


class LostRaceRepository(FakePhotoSubmissionRepository):
    """Hide the row on the first lookup so the upload reaches the unique constraint."""

    def __init__(self, rows=()):
        super().__init__(rows)
        self.hiding = True

    def get_by_idempotency_key(self, store, created_by, key):
        if self.hiding:
            self.hiding = False
            return None
        return super().get_by_idempotency_key(store, created_by, key)


@pytest.fixture
def repository():
    return FakePhotoSubmissionRepository()


@pytest.fixture
def uploader():
    return FakeMediaUploader()


@pytest.fixture
def catalog():
    product = make_product()
    variant = make_variant()
    return FakeCatalog(products=[product], variants=[variant])


@pytest.fixture
def authorizer():
    return FakeAuthorizer()


@pytest.fixture
def queue():
    return FakeProcessingQueue()


@pytest.fixture
def upload_photo(repository, uploader, catalog, authorizer, queue):
    return UploadPhoto(
        repository=repository,
        uploader=uploader,
        catalog=catalog,
        authorizer=authorizer,
        queue=queue,
    )


def test_upload_authorizes_catalog_manage_in_the_store(upload_photo, authorizer):
    upload_photo(command())

    assert authorizer.calls == [(7, HOME, MANAGE_CATALOG)]


def test_upload_rejects_a_user_without_catalog_manage(repository, uploader, catalog):
    authorizer = FakeAuthorizer(allowed=False)
    use_case = UploadPhoto(
        repository=repository,
        uploader=uploader,
        catalog=catalog,
        authorizer=authorizer,
        queue=FakeProcessingQueue(),
    )

    with pytest.raises(PermissionDeniedError):
        use_case(command())

    assert repository.rows == {}
    assert uploader.calls == []


def test_upload_creates_an_uploaded_submission_with_the_private_keys(
    upload_photo, repository, uploader, catalog
):
    result = upload_photo(
        command(
            kind=SubmissionKind.RECTANGLE,
            target_product_id=10,
            photographed_variant_id=20,
            corners=[{"x": 0.1, "y": 0.1}],
            crop={"x": 0, "y": 0, "width": 800, "height": 1000},
            light_correction=False,
        )
    )

    assert result.created is True
    submission = result.submission
    assert submission.id is not None
    assert submission.status is SubmissionStatus.UPLOADED
    assert submission.store_id == HOME.id
    assert submission.created_by_id == 7
    assert submission.kind is SubmissionKind.RECTANGLE
    assert submission.target_product_id == 10
    assert submission.photographed_variant_id == 20
    assert submission.original_key == "stores/1/photos/originals/test.jpg"
    assert submission.preview_key == "stores/1/photos/previews/test.jpg"
    assert submission.corners == [{"x": 0.1, "y": 0.1}]
    assert submission.crop == {"x": 0, "y": 0, "width": 800, "height": 1000}
    assert submission.light_correction is False
    assert submission.idempotency_key == "key-1"
    assert len(submission.request_fingerprint) == 64
    assert uploader.calls == [(HOME, b"photo-bytes")]
    assert repository.rows[submission.id] == submission


def test_upload_enqueues_the_new_submission_for_processing(upload_photo, queue):
    result = upload_photo(command())

    assert queue.calls == [(HOME, result.submission.id)]


def test_a_replay_does_not_enqueue_again(upload_photo, queue):
    upload_photo(command())
    upload_photo(command())

    assert len(queue.calls) == 1


def test_an_enqueue_failure_leaves_the_upload_failed_without_raising(
    repository, uploader, catalog, authorizer
):
    queue = FakeProcessingQueue(error=RuntimeError("the broker refused the message"))
    use_case = UploadPhoto(
        repository=repository,
        uploader=uploader,
        catalog=catalog,
        authorizer=authorizer,
        queue=queue,
    )

    result = use_case(command())

    assert result.created is True
    assert result.submission.status is SubmissionStatus.FAILED
    assert result.submission.failure_code == "photo_processing_unavailable"
    stored = repository.rows[result.submission.id]
    assert stored.status is SubmissionStatus.FAILED
    assert stored.failure_code == "photo_processing_unavailable"
    assert stored.attempts == 1


def test_the_same_key_and_payload_returns_the_original_without_uploading_again(
    upload_photo, uploader, repository
):
    first = upload_photo(command())
    second = upload_photo(command())

    assert second.created is False
    assert second.submission.id == first.submission.id
    assert len(uploader.calls) == 1
    assert len(repository.rows) == 1


def test_a_lost_idempotency_race_deletes_the_new_files_and_returns_the_replay(
    upload_photo, repository, catalog, authorizer
):
    first = upload_photo(command())
    racing_repository = LostRaceRepository(repository.rows.values())
    loser_uploader = FakeMediaUploader()
    loser_queue = FakeProcessingQueue()
    use_case = UploadPhoto(
        repository=racing_repository,
        uploader=loser_uploader,
        catalog=catalog,
        authorizer=authorizer,
        queue=loser_queue,
    )

    second = use_case(command())

    assert second.created is False
    assert second.submission.id == first.submission.id
    assert loser_uploader.deleted == [
        (HOME, "stores/1/photos/originals/test.jpg"),
        (HOME, "stores/1/photos/previews/test.jpg"),
    ]
    assert loser_queue.calls == []


def test_the_same_payload_twice_has_the_same_fingerprint(upload_photo):
    first = upload_photo(command())
    second = upload_photo(command())

    assert first.submission.request_fingerprint == second.submission.request_fingerprint


def test_the_same_key_with_a_different_payload_conflicts(upload_photo):
    upload_photo(command())

    with pytest.raises(IdempotencyConflict) as error:
        upload_photo(command(content=b"another-photo"))

    assert error.value.code == "idempotency_conflict"


@pytest.mark.parametrize(
    "changed",
    [
        {"kind": SubmissionKind.CONTOUR, "target_product_id": 10},
        {"kind": SubmissionKind.RECTANGLE, "target_product_id": 10},
        {"corners": [{"x": 0.5, "y": 0.5}]},
        {"crop": {"x": 0, "y": 0, "width": 10, "height": 10}},
        {"light_correction": False},
    ],
)
def test_every_request_field_changes_the_fingerprint(upload_photo, changed):
    first = upload_photo(command())
    second = upload_photo(command(idempotency_key="key-2", **changed))

    assert first.submission.request_fingerprint != second.submission.request_fingerprint


def test_the_key_is_scoped_to_the_creator_and_the_store(upload_photo, repository):
    first = upload_photo(command())
    other_creator = upload_photo(command(user_id=8, idempotency_key="key-1"))

    assert first.created is True
    assert other_creator.created is True
    assert first.submission.id != other_creator.submission.id
    assert len(repository.rows) == 2


def test_an_individual_photo_needs_a_target_product(upload_photo):
    with pytest.raises(InvalidSubmissionTarget):
        upload_photo(command(kind=SubmissionKind.RECTANGLE))


def test_the_target_product_must_belong_to_the_store(repository, uploader, authorizer):
    catalog = FakeCatalog(products=[make_product(store=ANIME)])
    use_case = UploadPhoto(
        repository=repository,
        uploader=uploader,
        catalog=catalog,
        authorizer=authorizer,
        queue=FakeProcessingQueue(),
    )

    with pytest.raises(InvalidSubmissionTarget):
        use_case(command(kind=SubmissionKind.RECTANGLE, target_product_id=10))

    assert repository.rows == {}
    assert uploader.calls == []


def test_the_photographed_variant_must_belong_to_the_target_product(
    repository, uploader, authorizer
):
    product = make_product()
    catalog = FakeCatalog(products=[product], variants=[make_variant(product_id=99)])
    use_case = UploadPhoto(
        repository=repository,
        uploader=uploader,
        catalog=catalog,
        authorizer=authorizer,
        queue=FakeProcessingQueue(),
    )

    with pytest.raises(InvalidSubmissionTarget):
        use_case(
            command(
                kind=SubmissionKind.RECTANGLE,
                target_product_id=product.id,
                photographed_variant_id=20,
            )
        )

    assert uploader.calls == []
