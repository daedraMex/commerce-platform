from datetime import timedelta

from django.conf import settings

from apps.photos.interfaces import tasks
from apps.shared.domain.store import StoreReference
from tests.unit.photos.fakes import FakePhotoSubmissionRepository


def test_the_sweep_task_uses_the_configured_threshold(monkeypatch, settings):
    settings.PHOTO_PROCESSING_STALE_AFTER = timedelta(minutes=7)
    repository = FakePhotoSubmissionRepository()
    calls = []

    class RecordingSweep:
        def __init__(self, *, repository, stale_after):
            calls.append(("init", repository, stale_after))

        def __call__(self, now, *, store=None):
            calls.append(("run", now, store))

    monkeypatch.setattr(tasks, "SweepStaleProcessing", RecordingSweep)
    monkeypatch.setattr(tasks, "get_photo_submission_repository", lambda: repository)

    tasks.sweep_stale_photo_processing.run()

    assert calls[0] == ("init", repository, timedelta(minutes=7))
    assert calls[1][0] == "run"
    assert calls[1][2] is None


def test_the_sweep_task_can_be_scoped_to_one_store(monkeypatch):
    calls = []

    class RecordingSweep:
        def __init__(self, *, repository, stale_after):
            pass

        def __call__(self, now, *, store=None):
            calls.append(store)

    monkeypatch.setattr(tasks, "SweepStaleProcessing", RecordingSweep)
    monkeypatch.setattr(
        tasks, "get_photo_submission_repository", lambda: FakePhotoSubmissionRepository()
    )

    tasks.sweep_stale_photo_processing.run(store_id=7)

    assert calls == [StoreReference(id=7, slug="")]


def test_the_sweep_is_scheduled_every_five_minutes():
    entry = settings.CELERY_BEAT_SCHEDULE["sweep-stale-photo-processing"]

    assert entry["task"] == "apps.photos.tasks.sweep_stale_photo_processing"
    assert entry["schedule"] == timedelta(minutes=5)
