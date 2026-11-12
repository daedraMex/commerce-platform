import hashlib

import pytest

from apps.photos.application.process_photo_submission import (
    ProcessPhotoSubmission,
    TransientProcessingError,
)
from apps.photos.domain.errors import InvalidImage
from apps.photos.domain.pipeline import PIPELINE_VERSION
from apps.photos.domain.submission import PhotoSubmission, SubmissionKind, SubmissionStatus
from apps.shared.domain.exceptions import NotFoundError
from tests.unit.photos.fakes import (
    HOME,
    FakeCatalog,
    FakePhotoSubmissionRepository,
    FakePrivateMediaReader,
    FakeRenderer,
    make_product,
    make_variant,
)

ORIGINAL_KEY = "stores/1/photos/originals/test.jpg"


def make_submission(**overrides):
    values = {
        "store_id": HOME.id,
        "created_by_id": 7,
        "kind": SubmissionKind.GROUP,
        "idempotency_key": "key-1",
        "request_fingerprint": "a" * 64,
        "original_key": ORIGINAL_KEY,
        "preview_key": "stores/1/photos/previews/test.jpg",
    }
    values.update(overrides)
    return PhotoSubmission(**values)


@pytest.fixture
def repository():
    return FakePhotoSubmissionRepository()


@pytest.fixture
def catalog():
    return FakeCatalog(products=[make_product()], variants=[make_variant()])


@pytest.fixture
def reader():
    return FakePrivateMediaReader(files={(HOME.id, ORIGINAL_KEY): b"private original"})


@pytest.fixture
def renderer():
    return FakeRenderer()


@pytest.fixture
def process(repository, catalog, reader, renderer):
    return ProcessPhotoSubmission(
        repository=repository,
        catalog=catalog,
        reader=reader,
        renderer=renderer,
    )


@pytest.mark.parametrize(
    ("kind", "target_product_id", "variant_id"),
    [
        (SubmissionKind.RECTANGLE, 10, 20),
        (SubmissionKind.CONTOUR, 10, 20),
        (SubmissionKind.GROUP, None, None),
    ],
)
def test_processing_creates_media_and_marks_the_submission_ready(
    process, repository, catalog, renderer, kind, target_product_id, variant_id
):
    submission = repository.add(
        make_submission(
            kind=kind,
            target_product_id=target_product_id,
            photographed_variant_id=variant_id,
        )
    )

    result = process(HOME, submission_id=submission.id)

    assert result.submission.status is SubmissionStatus.READY
    assert result.submission.attempts == 1
    assert result.submission.pipeline_version == PIPELINE_VERSION
    assert result.submission.result_media_id == result.media.id
    assert result.media.store_id == HOME.id
    assert result.media.content_hash == hashlib.sha256(b"rendered-photo").hexdigest()
    assert result.media.storage_key == f"stores/1/media/{result.media.content_hash}.jpg"
    assert result.media.width == 800
    assert result.media.height == 1000
    assert repository.get(HOME, submission.id) == result.submission
    assert renderer.calls[0][1] == b"private original"


def test_an_individual_photo_becomes_the_products_main_image(process, repository, catalog):
    submission = repository.add(
        make_submission(
            kind=SubmissionKind.RECTANGLE,
            target_product_id=10,
            photographed_variant_id=20,
        )
    )

    result = process(HOME, submission_id=submission.id)

    assert catalog.links == [(10, result.media.id, 20)]


def test_a_group_photo_creates_media_without_a_product_link(process, repository, catalog):
    submission = repository.add(make_submission(kind=SubmissionKind.GROUP))

    process(HOME, submission_id=submission.id)

    assert catalog.links == []


def test_a_deterministic_failure_records_the_domain_code(process, repository, renderer):
    submission = repository.add(
        make_submission(kind=SubmissionKind.RECTANGLE, target_product_id=10)
    )
    renderer.error = InvalidImage("The private original is not an image this service can read.")

    with pytest.raises(InvalidImage):
        process(HOME, submission_id=submission.id)

    failed = repository.get(HOME, submission.id)
    assert failed.status is SubmissionStatus.FAILED
    assert failed.failure_code == "invalid_image"
    assert failed.attempts == 1


def test_a_transient_failure_records_a_code_and_can_be_retried(process, repository, renderer):
    submission = repository.add(make_submission(kind=SubmissionKind.GROUP))
    renderer.error = OSError("storage is down")

    with pytest.raises(TransientProcessingError):
        process(HOME, submission_id=submission.id)

    failed = repository.get(HOME, submission.id)
    assert failed.status is SubmissionStatus.FAILED
    assert failed.failure_code == "processing_unavailable"

    renderer.error = None
    result = process(HOME, submission_id=submission.id)

    assert result.submission.status is SubmissionStatus.READY
    assert result.submission.attempts == 2


def test_retries_reuse_the_media_created_before_a_link_failure(repository, reader, renderer):
    class FailingLinkCatalog(FakeCatalog):
        fail_link = True

        def set_main_product_image(self, store, *, product_id, media_id, variant_id=None):
            if self.fail_link:
                raise OSError("the catalog is down")
            return super().set_main_product_image(
                store,
                product_id=product_id,
                media_id=media_id,
                variant_id=variant_id,
            )

    catalog = FailingLinkCatalog(products=[make_product()], variants=[make_variant()])
    process = ProcessPhotoSubmission(
        repository=repository,
        catalog=catalog,
        reader=reader,
        renderer=renderer,
    )
    submission = repository.add(
        make_submission(
            kind=SubmissionKind.RECTANGLE,
            target_product_id=10,
            photographed_variant_id=20,
        )
    )

    with pytest.raises(TransientProcessingError):
        process(HOME, submission_id=submission.id)
    catalog.fail_link = False
    result = process(HOME, submission_id=submission.id)

    assert len(catalog.created_media) == 1
    assert catalog.links == [(10, result.media.id, 20)]


def test_a_submission_from_another_store_is_not_processed(process, repository):
    submission = repository.add(make_submission(store_id=2))

    with pytest.raises(NotFoundError):
        process(HOME, submission_id=submission.id)


def test_processing_clears_the_previous_failure_when_an_attempt_starts(
    process, repository, renderer
):
    submission = repository.add(
        make_submission(
            kind=SubmissionKind.GROUP,
            status=SubmissionStatus.FAILED,
            failure_code="processing_unavailable",
            failure_message="Retry me",
        )
    )

    result = process(HOME, submission_id=submission.id)

    assert result.submission.failure_code == ""
    assert result.submission.failure_message == ""
