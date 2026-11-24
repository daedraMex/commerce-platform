"""Photo submission rules: pure Python, no Django, DRF or infrastructure imports."""

from apps.photos.domain.errors import (
    AttemptsExhausted,
    CannotApply,
    CannotDiscard,
    CannotMarkFailed,
    CannotMarkReady,
    CannotRedo,
    CannotRemove,
    CannotStartProcessing,
    IdempotencyConflict,
    InvalidSubmissionTarget,
    PhotoSubmissionError,
    RedoExhausted,
)
from apps.photos.domain.submission import (
    MAX_ATTEMPTS,
    MAX_REDOS,
    PhotoSubmission,
    SubmissionKind,
    SubmissionStatus,
    resolve_replay,
)

__all__ = [
    "MAX_ATTEMPTS",
    "MAX_REDOS",
    "AttemptsExhausted",
    "CannotApply",
    "CannotDiscard",
    "CannotMarkFailed",
    "CannotMarkReady",
    "CannotRedo",
    "CannotRemove",
    "CannotStartProcessing",
    "IdempotencyConflict",
    "InvalidSubmissionTarget",
    "PhotoSubmission",
    "PhotoSubmissionError",
    "RedoExhausted",
    "SubmissionKind",
    "SubmissionStatus",
    "resolve_replay",
]
