from datetime import UTC, datetime

import pytest

from apps.catalog.services import (
    CategoryReference,
    ProductRecord,
    VariantRecord,
)
from apps.photos.application.process_photo import ProcessPhotoSubmission
from apps.photos.domain.errors import InvalidImage
from apps.photos.domain.pipeline import PIPELINE_VERSION
from apps.photos.domain.submission import (
    PhotoSubmission,
    SubmissionKind,
    SubmissionStatus,
)
from apps.shared.domain.exceptions import NotFoundError
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
ORIGINAL = b"the-normalized-original"
CORNERS = [
    {"x": 0.1, "y": 0.1},
    {"x": 0.9, "y": 0.1},
    {"x": 0.9, "y": 0.9},
    {"x": 0.1, "y": 0.9},
]
CROP = {"x": 0, "y": 0, "width": 8, "height": 10}


def make_submission(kind=SubmissionKind.RECTANGLE, **overrides):
    values = {
        "id": 1,
        "store_id": HOME.id,
        "created_by_id": 7,
        "kind": kind,
        "target_product_id": 10
        if kind in (SubmissionKind.RECTANGLE, SubmissionKind.CONTOUR)
        else None,
        "photographed_variant_id": 20
        if kind in (SubmissionKind.RECTANGLE, SubmissionKind.CONTOUR)
        else None,
        "idempotency_key": "key-1",
        "request_fingerprint": "a" * 64,
        "original_key": "stores/1/photos/originals/original.jpg",
        "preview_key": "stores/1/photos/previews/preview.jpg",
        "corners": CORNERS if kind is SubmissionKind.RECTANGLE else None,
        "crop": CROP if kind is SubmissionKind.CONTOUR else None,
        "light_correction": True,
        "status": SubmissionStatus.UPLOADED,
        "attempts": 0,
    }
    values.update(overrides)
    return PhotoSubmission(**values)


@pytest.fixture
def repository():
    return FakePhotoSubmissionRepository(rows=[make_submission()])


@pytest.fixture
def catalog():
    return FakeCatalog()


@pytest.fixture
def processor():
    return FakePhotoProcessor()


@pytest.fixture
def reader():
    return FakePrivateMediaReader(contents={"stores/1/photos/originals/original.jpg": ORIGINAL})


@pytest.fixture
def use_case(repository, catalog, processor, reader):
    return ProcessPhotoSubmission(
        repository=repository,
        catalog=catalog,
        processor=processor,
        reader=reader,
    )


def test_processing_starts_the_attempt_and_marks_the_submission_ready(
    repository, catalog, processor, use_case
):
    saved = use_case(HOME, submission_id=1)

    assert saved.status is SubmissionStatus.READY
    assert saved.attempts == 1
    assert saved.pipeline_version == PIPELINE_VERSION
    assert saved.failure_code == ""
    assert saved.result_media_id is not None
    assert repository.rows[1].status is SubmissionStatus.READY

    assert len(processor.calls) == 1
    submission, size, original = processor.calls[0]
    assert original == ORIGINAL
    assert size is None

    assert len(catalog.create_media_calls) == 1
    store, media = catalog.create_media_calls[0]
    assert store == HOME
    assert media.content == b"processed"


def test_a_processing_submission_does_not_start_another_attempt(repository, processor, use_case):
    repository.rows[1] = make_submission(status=SubmissionStatus.PROCESSING, attempts=2)

    saved = use_case(HOME, submission_id=1)

    assert saved.status is SubmissionStatus.READY
    assert saved.attempts == 2
    assert len(processor.calls) == 1


def test_a_discarded_submission_fails_deterministically_without_media(
    repository, catalog, processor, use_case
):
    repository.rows[1] = make_submission(discarded_at=NOW)

    saved = use_case(HOME, submission_id=1)

    assert saved.status is SubmissionStatus.FAILED
    assert saved.failure_code == "photo_submission_discarded"
    assert saved.result_media_id is None
    assert processor.calls == []
    assert catalog.create_media_calls == []


def test_a_missing_original_fails_deterministically_without_media(
    repository, catalog, reader, use_case
):
    reader.contents = {}

    saved = use_case(HOME, submission_id=1)

    assert saved.status is SubmissionStatus.FAILED
    assert saved.failure_code == "photo_original_missing"
    assert saved.result_media_id is None
    assert catalog.create_media_calls == []


def test_a_processor_domain_error_marks_the_submission_failed(
    repository, catalog, processor, use_case
):
    processor.error = InvalidImage("The private original cannot be decoded.")

    saved = use_case(HOME, submission_id=1)

    assert saved.status is SubmissionStatus.FAILED
    assert saved.failure_code == "invalid_image"
    assert saved.result_media_id is None
    assert catalog.create_media_calls == []


@pytest.mark.parametrize(
    "kind",
    [SubmissionKind.RECTANGLE, SubmissionKind.CONTOUR, SubmissionKind.GROUP],
)
def test_processing_never_calls_a_product_image_operation(kind, use_case, repository, catalog):
    repository.rows[1] = make_submission(kind=kind)

    use_case(HOME, submission_id=1)

    assert catalog.append_calls == []
    assert catalog.remove_calls == []


def test_after_success_the_products_active_images_are_unchanged(use_case, repository, catalog):
    from tests.unit.photos.fakes import make_media

    catalog.media = {30: make_media()}

    use_case(HOME, submission_id=1)

    assert list(catalog.images.values()) == []
    assert 30 in catalog.media


def test_a_ready_submission_is_left_unchanged(repository, processor, use_case):
    repository.rows[1] = make_submission(
        status=SubmissionStatus.READY, result_media_id=30, attempts=1
    )

    saved = use_case(HOME, submission_id=1)

    assert saved.status is SubmissionStatus.READY
    assert saved.result_media_id == 30
    assert processor.calls == []


def test_an_unknown_submission_is_not_found(use_case):
    with pytest.raises(NotFoundError):
        use_case(ANIME, submission_id=1)


def test_the_photographed_size_reaches_the_processor(repository, catalog, processor, use_case):
    repository.rows[1] = make_submission(kind=SubmissionKind.CONTOUR)
    size_option = (
        {
            "code": "size",
            "label": "Size",
            "values": [
                {"code": "SM", "label": "Small", "width_cm": 10, "height_cm": 20},
            ],
        },
    )
    catalog.products[10] = ProductRecord(
        id=10,
        store_id=HOME.id,
        name="Frazada",
        slug="frazada",
        category=CategoryReference(id=1, shape="rectangle", option_schema=size_option),
    )
    catalog.variants[20] = VariantRecord(
        id=20,
        store_id=HOME.id,
        product_id=10,
        sku="FRZ-00001-SM",
        option_values={"size": "SM"},
    )

    use_case(HOME, submission_id=1)

    _, size, _ = processor.calls[0]
    assert size == (10.0, 20.0)
