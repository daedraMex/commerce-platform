"""Process one Photo submission into a public Media and its product link (ADR-0028)."""

import hashlib
from dataclasses import dataclass

from apps.catalog.services import MediaRecord, NewMedia
from apps.photos.application.ports import (
    PhotoCatalog,
    PhotoRenderer,
    PhotoSubmissionRepository,
    PrivateMediaReader,
)
from apps.photos.domain.errors import PhotoSubmissionError
from apps.photos.domain.pipeline import PIPELINE_VERSION
from apps.photos.domain.submission import INDIVIDUAL_KINDS, PhotoSubmission
from apps.shared.domain.exceptions import NotFoundError
from apps.shared.domain.store import StoreReference

TRANSIENT_FAILURE_CODE = "processing_unavailable"
TRANSIENT_FAILURE_MESSAGE = "The photo storage is temporarily unavailable; retrying."


class TransientProcessingError(Exception):
    """A processing attempt failed for a reason another attempt may fix."""

    code = TRANSIENT_FAILURE_CODE


@dataclass(frozen=True, slots=True)
class ProcessedPhoto:
    """The ready submission and the Media this processing run produced."""

    submission: PhotoSubmission
    media: MediaRecord


class ProcessPhotoSubmission:
    """Start an attempt, render the original, create Media and link it once."""

    def __init__(
        self,
        *,
        repository: PhotoSubmissionRepository,
        catalog: PhotoCatalog,
        reader: PrivateMediaReader,
        renderer: PhotoRenderer,
    ):
        self._repository = repository
        self._catalog = catalog
        self._reader = reader
        self._renderer = renderer

    def __call__(self, store: StoreReference, *, submission_id: int) -> ProcessedPhoto:
        submission = self._repository.get(store, submission_id)
        if submission is None:
            raise NotFoundError("No photo submission matches this id in this store.")

        submission.start_processing()
        submission = self._repository.save(submission)

        try:
            with self._reader.open(store, submission.original_key) as original:
                rendered = self._renderer.render(submission, original.read())
            media = self._catalog.create_media(store, _new_media(store, rendered))
            self._link_result(store, submission, media)
        except PhotoSubmissionError as error:
            self._mark_failed(submission, error.code, error.message)
            raise
        except OSError as error:
            self._mark_failed(submission, TRANSIENT_FAILURE_CODE, TRANSIENT_FAILURE_MESSAGE)
            raise TransientProcessingError(TRANSIENT_FAILURE_MESSAGE) from error
        except Exception as error:
            self._mark_failed(
                submission,
                "processing_failed",
                "The photo could not be processed.",
            )
            raise error

        submission.mark_ready(media.id, PIPELINE_VERSION)
        return ProcessedPhoto(submission=self._repository.save(submission), media=media)

    def _link_result(
        self, store: StoreReference, submission: PhotoSubmission, media: MediaRecord
    ) -> None:
        if submission.kind not in INDIVIDUAL_KINDS or submission.target_product_id is None:
            return
        self._catalog.set_main_product_image(
            store,
            product_id=submission.target_product_id,
            media_id=media.id,
            variant_id=submission.photographed_variant_id,
        )

    def _mark_failed(self, submission: PhotoSubmission, code: str, message: str) -> None:
        submission.mark_failed(code, message)
        self._repository.save(submission)


def _new_media(store: StoreReference, rendered) -> NewMedia:
    content_hash = hashlib.sha256(rendered.content).hexdigest()
    return NewMedia(
        content=rendered.content,
        content_hash=content_hash,
        storage_key=f"stores/{store.id}/media/{content_hash}.{rendered.extension}",
        mime_type=rendered.mime_type,
        width=rendered.width,
        height=rendered.height,
        metadata=rendered.metadata,
    )
