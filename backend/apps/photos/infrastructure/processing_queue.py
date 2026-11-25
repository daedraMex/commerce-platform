"""Celery implementation of the PhotoProcessingQueue port (ADR-0028)."""

import logging

from django.db import transaction

from apps.shared.domain.store import StoreReference
from config.celery import app

PROCESS_PHOTO_TASK = "apps.photos.tasks.process_photo"

logger = logging.getLogger(__name__)


class CeleryPhotoProcessingQueue:
    """Send a store-scoped message once the surrounding transaction commits."""

    def enqueue(self, store: StoreReference, submission_id: int) -> None:
        def send():
            try:
                app.send_task(
                    PROCESS_PHOTO_TASK,
                    kwargs={"store_id": store.id, "submission_id": submission_id},
                )
            except Exception:
                logger.exception(
                    "Could not enqueue photo processing for store %s submission %s",
                    store.id,
                    submission_id,
                    extra={"store_id": store.id, "submission_id": submission_id},
                )
                try:
                    _record_unavailable(store, submission_id)
                except Exception:
                    logger.exception(
                        "Could not record dropped photo processing for store %s submission %s",
                        store.id,
                        submission_id,
                        extra={"store_id": store.id, "submission_id": submission_id},
                    )

        if transaction.get_connection().in_atomic_block:
            transaction.on_commit(send)
        else:
            send()


def _record_unavailable(store: StoreReference, submission_id: int) -> None:
    """Mark the submission failed in its own transaction, after the send was lost."""
    from apps.photos.application.fail_exhausted_processing import FailExhaustedProcessing
    from apps.photos.infrastructure.repository import DjangoPhotoSubmissionRepository

    try:
        with transaction.atomic():
            FailExhaustedProcessing(
                repository=DjangoPhotoSubmissionRepository(),
            )(store, submission_id)
    except Exception:
        logger.exception(
            "Could not record unavailable photo processing for store %s submission %s",
            store.id,
            submission_id,
            extra={"store_id": store.id, "submission_id": submission_id},
        )
