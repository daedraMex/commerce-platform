"""Domain errors for photo submissions, each with a stable code (ADR-0014)."""

from apps.shared.domain.exceptions import DomainError


class PhotoSubmissionError(DomainError):
    code = "photo_submission_error"


class InvalidSubmissionTarget(PhotoSubmissionError):
    code = "submission_invalid_target"


class IdempotencyConflict(PhotoSubmissionError):
    code = "idempotency_conflict"


class CannotStartProcessing(PhotoSubmissionError):
    code = "submission_cannot_start_processing"


class AttemptsExhausted(PhotoSubmissionError):
    code = "submission_attempts_exhausted"


class CannotMarkReady(PhotoSubmissionError):
    code = "submission_cannot_mark_ready"


class CannotMarkFailed(PhotoSubmissionError):
    code = "submission_cannot_mark_failed"


class CannotRedo(PhotoSubmissionError):
    code = "submission_cannot_redo"


class CannotApply(PhotoSubmissionError):
    code = "submission_cannot_apply"


class CannotRemove(PhotoSubmissionError):
    code = "submission_cannot_remove"


class CannotChangeGroupLinks(PhotoSubmissionError):
    code = "submission_cannot_change_links"


class CannotDiscard(PhotoSubmissionError):
    code = "submission_cannot_discard"


class ConcurrentModification(PhotoSubmissionError):
    code = "submission_concurrent_modification"


class DuplicateIdempotencyKey(PhotoSubmissionError):
    code = "submission_duplicate_idempotency_key"


class QuadValidationError(PhotoSubmissionError):
    """Staff corners cannot describe the photographed product."""

    code = "quad_invalid"


class InvalidQuadCorners(QuadValidationError):
    code = "quad_invalid_corners"


class QuadOutOfBounds(QuadValidationError):
    code = "quad_out_of_bounds"


class QuadSelfIntersecting(QuadValidationError):
    code = "quad_self_intersecting"


class QuadNonConvex(QuadValidationError):
    code = "quad_non_convex"


class QuadTooSmall(QuadValidationError):
    code = "quad_too_small"


class CropSourceMissing(PhotoSubmissionError):
    """A crop needs a photographed size or four corners to choose its ratio."""

    code = "crop_missing_source"


class InvalidPhotographedSize(PhotoSubmissionError):
    """A photographed size must be a positive (width, height) pair."""

    code = "crop_invalid_size"


class InvalidChannelMeans(PhotoSubmissionError):
    """Light correction needs one non-negative mean per colour channel."""

    code = "light_invalid_channel_means"


class InvalidImage(PhotoSubmissionError):
    """An upload is not a decodable image."""

    code = "invalid_image"


class OriginalMissing(PhotoSubmissionError):
    """A submission's private original file is gone, so it can never be processed."""

    code = "photo_original_missing"


class InvalidCrop(PhotoSubmissionError):
    """A contour photo's crop rectangle is missing or malformed."""

    code = "crop_invalid"


class ImageTooLarge(PhotoSubmissionError):
    """An upload is larger than the accepted number of bytes."""

    code = "too_large"


class TooManyPixels(PhotoSubmissionError):
    """An upload declares more pixels than decoders may allocate."""

    code = "too_many_pixels"
