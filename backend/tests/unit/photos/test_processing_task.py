import pytest
from celery.exceptions import Retry

from apps.photos.interfaces import tasks
from apps.shared.domain.exceptions import NotFoundError
from apps.shared.domain.store import StoreReference


class FakeTaskSelf:
    def __init__(self):
        self.retried = None

    def retry(self, exc=None):
        self.retried = exc
        raise Retry()


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
