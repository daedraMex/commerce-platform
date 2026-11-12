import pytest

from apps.photos.application.get_photo_submission import GetPhotoSubmission
from apps.photos.domain.submission import PhotoSubmission, SubmissionKind, SubmissionStatus
from apps.shared.domain.exceptions import NotFoundError, PermissionDeniedError
from apps.shared.domain.permissions import MANAGE_CATALOG
from apps.shared.domain.store import StoreReference
from tests.unit.photos.fakes import (
    FakeAuthorizer,
    FakeCatalog,
    FakePhotoSubmissionRepository,
    make_media,
)

HOME = StoreReference(id=1, slug="home")
ANIME = StoreReference(id=2, slug="anime")


def submission(store=HOME, *, submission_id=1, status=SubmissionStatus.READY):
    return PhotoSubmission(
        id=submission_id,
        store_id=store.id,
        created_by_id=7,
        kind=SubmissionKind.GROUP,
        idempotency_key=f"key-{submission_id}",
        request_fingerprint="a" * 64,
        status=status,
        result_media_id=30 if status is SubmissionStatus.READY else None,
    )


@pytest.fixture
def repository():
    row = submission()
    return FakePhotoSubmissionRepository(rows=[row])


@pytest.fixture
def catalog():
    return FakeCatalog(media=[make_media()])


@pytest.fixture
def authorizer():
    return FakeAuthorizer()


@pytest.fixture
def get_submission(repository, catalog, authorizer):
    return GetPhotoSubmission(
        repository=repository,
        catalog=catalog,
        authorizer=authorizer,
    )


def test_status_authorizes_catalog_manage_in_the_store(get_submission, authorizer):
    get_submission(HOME, user_id=7, submission_id=1)

    assert authorizer.calls == [(7, HOME, MANAGE_CATALOG)]


def test_status_rejects_a_user_without_catalog_manage(repository, catalog):
    use_case = GetPhotoSubmission(
        repository=repository,
        catalog=catalog,
        authorizer=FakeAuthorizer(allowed=False),
    )

    with pytest.raises(PermissionDeniedError):
        use_case(HOME, user_id=7, submission_id=1)


def test_status_returns_the_submission_and_its_result_media(get_submission):
    view = get_submission(HOME, user_id=7, submission_id=1)

    assert view.submission.id == 1
    assert view.submission.status is SubmissionStatus.READY
    assert view.result_media.storage_key == "stores/1/media/hash-1.jpg"


def test_status_returns_no_result_media_while_processing(repository, catalog, authorizer):
    repository.rows[1] = submission(status=SubmissionStatus.PROCESSING)
    use_case = GetPhotoSubmission(
        repository=repository,
        catalog=catalog,
        authorizer=authorizer,
    )

    view = use_case(HOME, user_id=7, submission_id=1)

    assert view.result_media is None


def test_status_never_finds_another_stores_submission(get_submission):
    with pytest.raises(NotFoundError) as error:
        get_submission(ANIME, user_id=7, submission_id=1)

    assert error.value.code == "not_found"
