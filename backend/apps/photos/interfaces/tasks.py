"""Celery tasks that turn a photo submission into a public Media (ADR-0028)."""

from celery import shared_task

from apps.photos.application.process_photo import ProcessPhotoSubmission
from apps.shared.domain.exceptions import NotFoundError
from apps.shared.domain.store import StoreReference
from config.dependencies import (
    get_catalog_service,
    get_photo_processor,
    get_photo_submission_repository,
    get_private_media_reader,
)


@shared_task(
    name="apps.photos.tasks.process_photo",
    bind=True,
    max_retries=3,
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
        raise self.retry(exc=error) from error
