"""Process one uploaded photo into a content-addressed Media (ADR-0028, ADR-0030).

Processing never publishes a photo: it only records a ``ready`` (or ``failed``)
submission. Staff approval (apply) is what later adds the Media to a carousel.
"""

import hashlib

from apps.catalog.services import MediaRecord, NewMedia
from apps.photos.application.ports import (
    PhotoCatalog,
    PhotoProcessor,
    PhotoSubmissionRepository,
    PrivateMediaReader,
)
from apps.photos.domain.errors import OriginalMissing, PhotoSubmissionError
from apps.photos.domain.pipeline import PIPELINE_VERSION
from apps.photos.domain.submission import PhotoSubmission, SubmissionStatus
from apps.shared.domain.exceptions import NotFoundError
from apps.shared.domain.store import StoreReference

DISCARDED_FAILURE_CODE = "photo_submission_discarded"
DISCARDED_FAILURE_MESSAGE = "A discarded submission is never processed."
MEDIA_MIME_TYPE = "image/jpeg"

_SIZE_OPTION_CODE = "size"


class ProcessPhotoSubmission:
    """Load one submission, start its attempt and turn its original into a Media.

    Deterministic failures (discarded, missing original, an undecodable or invalid
    photo) are recorded on the submission and never retried; anything else bubbles
    up so the task can retry with backoff.
    """

    def __init__(
        self,
        *,
        repository: PhotoSubmissionRepository,
        catalog: PhotoCatalog,
        processor: PhotoProcessor,
        reader: PrivateMediaReader,
    ):
        self._repository = repository
        self._catalog = catalog
        self._processor = processor
        self._reader = reader

    def __call__(self, store: StoreReference, submission_id: int) -> PhotoSubmission:
        submission = self._repository.get(store, submission_id)
        if submission is None:
            raise NotFoundError("No photo submission matches this id in this store.")

        if submission.discarded_at is not None:
            submission.mark_failed(DISCARDED_FAILURE_CODE, DISCARDED_FAILURE_MESSAGE)
            return self._repository.save(submission)

        if submission.status is SubmissionStatus.UPLOADED:
            submission.start_processing()
            submission = self._repository.save(submission)
        elif submission.status is not SubmissionStatus.PROCESSING:
            return submission

        try:
            original = self._read_original(store, submission)
            media = self._build_media(store, submission, original)
        except PhotoSubmissionError as error:
            submission.mark_failed(error.code, error.message)
            return self._repository.save(submission)

        submission.mark_ready(media.id, PIPELINE_VERSION)
        return self._repository.save(submission)

    def _read_original(self, store: StoreReference, submission: PhotoSubmission) -> bytes:
        try:
            with self._reader.open(store, submission.original_key) as original:
                return original.read()
        except OSError as error:
            raise OriginalMissing("The private original is missing.") from error

    def _build_media(
        self,
        store: StoreReference,
        submission: PhotoSubmission,
        original: bytes,
    ) -> MediaRecord:
        size = _photographed_size(self._catalog, store, submission)
        processed = self._processor.process(submission, size, original)
        content_hash = hashlib.sha256(processed.content).hexdigest()
        media = NewMedia(
            content=processed.content,
            content_hash=content_hash,
            storage_key=f"stores/{store.id}/media/{content_hash}.jpg",
            mime_type=MEDIA_MIME_TYPE,
            width=processed.width,
            height=processed.height,
            metadata={"format": "JPEG", "bytes": len(processed.content)},
        )
        return self._catalog.create_media(store, media)


def _photographed_size(
    catalog: PhotoCatalog, store: StoreReference, submission
) -> tuple[float, float] | None:
    """The photographed variant's physical (width_cm, height_cm), when it has one."""
    if submission.photographed_variant_id is None:
        return None
    variant = catalog.get_variant(store, submission.photographed_variant_id)
    if variant is None:
        return None
    product = catalog.get_product(store, submission.target_product_id)
    if product is None:
        return None

    for option in product.category.option_schema:
        if str(option.get("code", "")).strip().lower() != _SIZE_OPTION_CODE:
            continue
        value_code = variant.option_values.get(option["code"])
        definition = next(
            (value for value in option.get("values", ()) if value.get("code") == value_code),
            None,
        )
        if definition is None:
            return None
        width = definition.get("width_cm")
        height = definition.get("height_cm")
        if width is None or height is None:
            return None
        return (float(width), float(height))
    return None
