"""The Photo submission entity and its state machine.

A submission is one staff upload: it moves uploaded -> processing -> ready or failed,
and a redo moves it from ready back to processing without deleting the previous result.
Applied and discarded are timestamps, not states.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from apps.photos.domain.errors import (
    AttemptsExhausted,
    CannotApply,
    CannotDiscard,
    CannotMarkFailed,
    CannotMarkReady,
    CannotRedo,
    CannotStartProcessing,
    IdempotencyConflict,
    InvalidSubmissionTarget,
)

MAX_ATTEMPTS = 3


class SubmissionStatus(StrEnum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class SubmissionKind(StrEnum):
    RECTANGLE = "rectangle"
    CONTOUR = "contour"
    GROUP = "group"


INDIVIDUAL_KINDS = (SubmissionKind.RECTANGLE, SubmissionKind.CONTOUR)


def validate_kind_target(
    kind: SubmissionKind,
    target_product_id: int | None,
    photographed_variant_id: int | None,
) -> None:
    """An individual photo targets a product; a group photo targets no product or variant."""
    if kind in INDIVIDUAL_KINDS and target_product_id is None:
        raise InvalidSubmissionTarget("A rectangle or contour photo needs a target product.")
    if kind is SubmissionKind.GROUP and target_product_id is not None:
        raise InvalidSubmissionTarget("A group photo has no target product.")
    if kind is SubmissionKind.GROUP and photographed_variant_id is not None:
        raise InvalidSubmissionTarget("A group photo has no photographed variant.")


@dataclass(slots=True)
class PhotoSubmission:
    store_id: int
    created_by_id: int
    kind: SubmissionKind
    idempotency_key: str
    request_fingerprint: str
    id: int | None = None
    version: int = 0
    target_product_id: int | None = None
    photographed_variant_id: int | None = None
    original_key: str = ""
    preview_key: str = ""
    corners: list | None = None
    crop: dict | None = None
    light_correction: bool = True
    pipeline_version: str = ""
    status: SubmissionStatus = SubmissionStatus.UPLOADED
    failure_code: str = ""
    failure_message: str = ""
    attempts: int = 0
    result_media_id: int | None = None
    applied_at: datetime | None = None
    applied_by_id: int | None = None
    discarded_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        self.kind = SubmissionKind(self.kind)
        self.status = SubmissionStatus(self.status)
        validate_kind_target(
            self.kind,
            self.target_product_id,
            self.photographed_variant_id,
        )

    def start_processing(self) -> None:
        """Start an attempt from uploaded or failed, up to MAX_ATTEMPTS."""
        if self.applied_at is not None:
            raise CannotStartProcessing("An applied submission cannot start processing.")
        if self.discarded_at is not None:
            raise CannotStartProcessing("A discarded submission cannot start processing.")
        if self.status not in (SubmissionStatus.UPLOADED, SubmissionStatus.FAILED):
            raise CannotStartProcessing(
                "Only an uploaded or failed submission can start processing."
            )
        if self.attempts >= MAX_ATTEMPTS:
            raise AttemptsExhausted(
                f"This submission already used its {MAX_ATTEMPTS} processing attempts."
            )
        self.attempts += 1
        self.status = SubmissionStatus.PROCESSING
        self.failure_code = ""
        self.failure_message = ""

    def mark_ready(self, result_media_id: int, pipeline_version: str) -> None:
        """Record the Media a processing attempt produced.

        A task that finishes after the submission was discarded still records its result.
        """
        if self.applied_at is not None:
            raise CannotMarkReady("An applied submission cannot become ready.")
        if self.discarded_at is None and self.status is not SubmissionStatus.PROCESSING:
            raise CannotMarkReady("Only a processing submission can become ready.")
        self.status = SubmissionStatus.READY
        self.result_media_id = result_media_id
        self.pipeline_version = pipeline_version
        self.failure_code = ""
        self.failure_message = ""

    def mark_failed(self, code: str, message: str) -> None:
        """Record why a processing attempt failed.

        A task that finishes after the submission was discarded still records its failure.
        """
        if self.applied_at is not None:
            raise CannotMarkFailed("An applied submission cannot fail.")
        if self.discarded_at is None and self.status is not SubmissionStatus.PROCESSING:
            raise CannotMarkFailed("Only a processing submission can fail.")
        self.status = SubmissionStatus.FAILED
        self.failure_code = code
        self.failure_message = message

    def redo(self, corners: list, crop: dict) -> int | None:
        """Move a ready submission back to processing with a new quad or crop.

        Returns the previous result Media id; the Media itself is kept, never deleted.
        """
        if self.applied_at is not None:
            raise CannotRedo("An applied submission cannot be redone.")
        if self.discarded_at is not None:
            raise CannotRedo("A discarded submission cannot be redone.")
        if self.status is not SubmissionStatus.READY:
            raise CannotRedo("Only a ready submission can be redone.")
        previous_result_media_id = self.result_media_id
        self.corners = corners
        self.crop = crop
        self.status = SubmissionStatus.PROCESSING
        self.result_media_id = None
        self.pipeline_version = ""
        self.failure_code = ""
        self.failure_message = ""
        return previous_result_media_id

    def apply(self, user_id: int, now: datetime) -> None:
        """Stamp a ready, undiscarded submission as applied; status stays ready."""
        if self.discarded_at is not None:
            raise CannotApply("A discarded submission cannot be applied.")
        if self.status is not SubmissionStatus.READY:
            raise CannotApply("Only a ready submission can be applied.")
        if self.applied_at is not None:
            raise CannotApply("This submission is already applied.")
        self.applied_at = now
        self.applied_by_id = user_id

    def discard(self, now: datetime) -> None:
        """Stamp an unapplied submission as discarded; it is never deleted."""
        if self.applied_at is not None:
            raise CannotDiscard("An applied submission cannot be discarded.")
        if self.discarded_at is not None:
            raise CannotDiscard("This submission is already discarded.")
        self.discarded_at = now


def resolve_replay(existing: PhotoSubmission | None, fingerprint: str) -> PhotoSubmission | None:
    """Return the submission a replay refers to, or refuse a different payload (ADR-0028)."""
    if existing is None:
        return None
    if existing.request_fingerprint != fingerprint:
        raise IdempotencyConflict("This idempotency key was already used with a different request.")
    return existing
