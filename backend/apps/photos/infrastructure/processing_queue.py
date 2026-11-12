"""Enqueue photo processing only after the submission's transaction commits."""

from django.db import transaction

from apps.shared.domain.store import StoreReference


class CeleryPhotoProcessingQueue:
    """The PhotoProcessingQueue adapter over the Celery task."""

    def enqueue(self, store: StoreReference, submission_id: int) -> None:
        from apps.photos.interfaces.tasks import process_photo_submission

        transaction.on_commit(lambda: process_photo_submission.delay(store.id, submission_id))
