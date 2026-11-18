"""Celery implementation of the PhotoProcessingQueue port (ADR-0028)."""

from django.db import transaction

from apps.shared.domain.store import StoreReference
from config.celery import app

PROCESS_PHOTO_TASK = "apps.photos.tasks.process_photos"


class CeleryPhotoProcessingQueue:
    """Send a store-scoped message once the surrounding transaction commits."""

    def enqueue(self, store: StoreReference, submission_id: int) -> None:
        def send():
            app.send_task(
                PROCESS_PHOTO_TASK,
                kwargs={"store_id": store.id, "submission_id": submission_id},
            )

        if transaction.get_connection().in_atomic_block:
            transaction.on_commit(send)
        else:
            send()
