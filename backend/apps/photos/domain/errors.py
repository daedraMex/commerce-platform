"""Domain errors for photo submissions, each with a stable code (ADR-0014)."""

from apps.shared.domain.exceptions import DomainError


class PhotoSubmissionError(DomainError):
    code = "photo_submission_error"


class InvalidSubmissionTarget(PhotoSubmissionError):
    code = "submission_invalid_target"


class IdempotencyConflict(PhotoSubmissionError):
    code = "submission_idempotency_conflict"


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


class CannotDiscard(PhotoSubmissionError):
    code = "submission_cannot_discard"


class ConcurrentModification(PhotoSubmissionError):
    code = "submission_concurrent_modification"


class DuplicateIdempotencyKey(PhotoSubmissionError):
    code = "submission_duplicate_idempotency_key"
