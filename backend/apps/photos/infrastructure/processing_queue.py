"""Celery implementation of the PhotoProcessingQueue port (ADR-0028)."""

from apps.shared.domain.store import StoreReference
from config.celery import app

PROCESS_PHOTO_TASK = "apps.photos.tasks.process_photo"


class CeleryPhotoProcessingQueue:
    """Send a store-scoped message that the photo processing worker consumes."""

    def enqueue(self, store: StoreReference, submission_id: int) -> None:
        app.send_task(
            PROCESS_PHOTO_TASK,
            kwargs={"store_id": store.id, "submission_id": submission_id},
        )
