import logging

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


def test_a_failed_send_records_the_submission_as_unavailable(monkeypatch, caplog):
    def refuse(name, kwargs):
        raise RuntimeError("the broker refused the message")

    recorded = []
    monkeypatch.setattr(processing_queue.app, "send_task", refuse)
    monkeypatch.setattr(
        processing_queue,
        "_record_unavailable",
        lambda store, submission_id: recorded.append((store, submission_id)),
    )

    with caplog.at_level(logging.ERROR, logger=processing_queue.__name__):
        CeleryPhotoProcessingQueue().enqueue(StoreReference(id=7, slug="home"), 42)

    assert recorded == [(StoreReference(id=7, slug="home"), 42)]
    assert caplog.records
    assert caplog.records[0].store_id == 7
    assert caplog.records[0].submission_id == 42


def test_a_failure_to_record_the_dropped_message_is_logged_not_raised(monkeypatch, caplog):
    def refuse(name, kwargs):
        raise RuntimeError("the broker refused the message")

    def also_fail(store, submission_id):
        raise RuntimeError("the database is down")

    monkeypatch.setattr(processing_queue.app, "send_task", refuse)
    monkeypatch.setattr(processing_queue, "_record_unavailable", also_fail)

    with caplog.at_level(logging.ERROR, logger=processing_queue.__name__):
        CeleryPhotoProcessingQueue().enqueue(StoreReference(id=7, slug="home"), 42)

    assert caplog.records
    assert caplog.records[-1].store_id == 7
    assert caplog.records[-1].submission_id == 42
