from apps.photos.infrastructure import processing_queue
from apps.photos.infrastructure.processing_queue import (
    PROCESS_PHOTO_TASK,
    CeleryPhotoProcessingQueue,
)
from apps.shared.domain.store import StoreReference


def test_the_celery_queue_sends_a_store_scoped_task_by_name(monkeypatch):
    sent = []
    monkeypatch.setattr(
        processing_queue.app,
        "send_task",
        lambda name, kwargs: sent.append((name, kwargs)),
    )

    CeleryPhotoProcessingQueue().enqueue(StoreReference(id=7, slug="home"), 42)

    assert sent == [
        (PROCESS_PHOTO_TASK, {"store_id": 7, "submission_id": 42}),
    ]
