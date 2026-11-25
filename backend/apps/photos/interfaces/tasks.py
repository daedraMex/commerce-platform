"""Celery tasks that turn a photo submission into a public Media (ADR-0028)."""

import logging

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.photos.application.fail_exhausted_processing import FailExhaustedProcessing
from apps.photos.application.process_photo import ProcessPhotoSubmission
from apps.photos.application.sweep_stale_processing import SweepStaleProcessing
from apps.shared.domain.exceptions import NotFoundError
from apps.shared.domain.store import StoreReference
from config.dependencies import (
    get_catalog_service,
    get_photo_processor,
    get_photo_submission_repository,
    get_private_media_reader,
)

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


@shared_task(
    name="apps.photos.tasks.process_photo",
    bind=True,
    max_retries=MAX_RETRIES,
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
)
def process_photo(self, store_id, submission_id):
    """Process one submission; retry transient failures with backoff, never a domain one."""
    store = StoreReference(id=store_id, slug="")
    try:
        ProcessPhotoSubmission(
            repository=get_photo_submission_repository(),
            catalog=get_catalog_service(),
            processor=get_photo_processor(),
            reader=get_private_media_reader(),
        )(store, submission_id)
    except NotFoundError:
        return
    except Exception as error:
        retries = getattr(getattr(self, "request", None), "retries", 0)
        max_retries = getattr(self, "max_retries", MAX_RETRIES)
        if retries >= max_retries:
            _record_exhausted_failure(store, submission_id)
            return
        raise self.retry(exc=error) from error


def _record_exhausted_failure(store: StoreReference, submission_id: int) -> None:
    try:
        FailExhaustedProcessing(
            repository=get_photo_submission_repository(),
        )(store, submission_id)
    except Exception:
        logger.exception(
            "Could not record exhausted photo processing for store %s submission %s",
            store.id,
            submission_id,
            extra={"store_id": store.id, "submission_id": submission_id},
        )


@shared_task(name="apps.photos.tasks.sweep_stale_photo_processing")
def sweep_stale_photo_processing(store_id=None):
    """Fail processing submissions whose message was lost, for one store or every store."""
    store = StoreReference(id=store_id, slug="") if store_id is not None else None
    SweepStaleProcessing(
        repository=get_photo_submission_repository(),
        stale_after=settings.PHOTO_PROCESSING_STALE_AFTER,
    )(timezone.now(), store=store)
