from types import SimpleNamespace

import pytest
from celery.exceptions import Retry

from apps.photos.domain.submission import (
    PhotoSubmission,
    SubmissionKind,
    SubmissionStatus,
)
from apps.photos.interfaces import tasks
from apps.shared.domain.exceptions import NotFoundError
from apps.shared.domain.store import StoreReference
from tests.unit.photos.fakes import (
    FakeCatalog,
    FakePhotoProcessor,
    FakePhotoSubmissionRepository,
    FakePrivateMediaReader,
)

ORIGINAL_KEY = "stores/1/photos/originals/original.jpg"


class FakeTaskSelf:
    def __init__(self, retries=0):
        self.request = SimpleNamespace(retries=retries)
        self.max_retries = tasks.process_photo.max_retries
        self.retried = None

    def retry(self, exc=None):
        self.retried = exc
        self.request.retries += 1
        raise Retry()


def make_processing_submission():
    return PhotoSubmission(
        id=1,
        store_id=1,
        created_by_id=7,
        kind=SubmissionKind.RECTANGLE,
        target_product_id=10,
        photographed_variant_id=20,
        idempotency_key="key-1",
        request_fingerprint="a" * 64,
        original_key=ORIGINAL_KEY,
        preview_key="stores/1/photos/previews/preview.jpg",
        status=SubmissionStatus.PROCESSING,
        attempts=1,
    )


def run_task(fake, store_id, submission_id):
    tasks.process_photo.run.__func__(fake, store_id, submission_id)


def test_the_task_runs_the_processing_use_case(monkeypatch):
    calls = []

    class RecordingUseCase:
        def __init__(self, **kwargs):
            pass

        def __call__(self, store, submission_id):
            calls.append((store, submission_id))

    monkeypatch.setattr(tasks, "ProcessPhotoSubmission", RecordingUseCase)

    run_task(FakeTaskSelf(), store_id=7, submission_id=42)

    assert calls == [(StoreReference(id=7, slug=""), 42)]


def test_the_task_retries_a_transient_failure(monkeypatch):
    class ExplodingUseCase:
        def __init__(self, **kwargs):
            pass

        def __call__(self, store, submission_id):
            raise RuntimeError("the database is down")

    monkeypatch.setattr(tasks, "ProcessPhotoSubmission", ExplodingUseCase)
    fake = FakeTaskSelf()

    with pytest.raises(Retry):
        run_task(fake, store_id=7, submission_id=42)

    assert isinstance(fake.retried, RuntimeError)


def test_the_task_does_not_retry_an_unknown_submission(monkeypatch):
    class MissingUseCase:
        def __init__(self, **kwargs):
            pass

        def __call__(self, store, submission_id):
            raise NotFoundError("No photo submission matches this id in this store.")

    monkeypatch.setattr(tasks, "ProcessPhotoSubmission", MissingUseCase)
    fake = FakeTaskSelf()

    run_task(fake, store_id=7, submission_id=42)

    assert fake.retried is None


def test_the_task_retries_transient_failures_with_backoff():
    assert tasks.process_photo.max_retries == 3
    assert tasks.process_photo.retry_backoff is True
    assert tasks.process_photo.retry_backoff_max == 120
    assert tasks.process_photo.retry_jitter is True


def test_the_last_retry_records_the_failure_instead_of_retrying(monkeypatch):
    calls = []

    class ExplodingUseCase:
        def __init__(self, **kwargs):
            pass

        def __call__(self, store, submission_id):
            raise RuntimeError("the database is down")

    class RecordingFailure:
        def __init__(self, **kwargs):
            pass

        def __call__(self, store, submission_id):
            calls.append((store, submission_id))

    monkeypatch.setattr(tasks, "ProcessPhotoSubmission", ExplodingUseCase)
    monkeypatch.setattr(tasks, "FailExhaustedProcessing", RecordingFailure)
    fake = FakeTaskSelf(retries=tasks.process_photo.max_retries)

    run_task(fake, store_id=7, submission_id=42)

    assert fake.retried is None
    assert calls == [(StoreReference(id=7, slug=""), 42)]


def test_a_processor_that_always_fails_ends_failed_after_the_last_retry(monkeypatch):
    repository = FakePhotoSubmissionRepository(rows=[make_processing_submission()])
    processor = FakePhotoProcessor(error=RuntimeError("storage is down"))
    reader = FakePrivateMediaReader(contents={ORIGINAL_KEY: b"the-original"})
    monkeypatch.setattr(tasks, "get_photo_submission_repository", lambda: repository)
    monkeypatch.setattr(tasks, "get_catalog_service", lambda: FakeCatalog())
    monkeypatch.setattr(tasks, "get_photo_processor", lambda: processor)
    monkeypatch.setattr(tasks, "get_private_media_reader", lambda: reader)
    fake = FakeTaskSelf()

    for _ in range(tasks.process_photo.max_retries + 1):
        try:
            run_task(fake, store_id=1, submission_id=1)
        except Retry:
            continue

    saved = repository.rows[1]
    assert saved.status is SubmissionStatus.FAILED
    assert saved.failure_code == "photo_processing_unavailable"
    assert saved.failure_message
    assert saved.attempts == 1
    assert len(processor.calls) == tasks.process_photo.max_retries + 1
    assert fake.request.retries == tasks.process_photo.max_retries
