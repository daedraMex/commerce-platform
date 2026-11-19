"""Django implementation of the PhotoSubmissionRepository port (ADR-0022)."""

from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.photos.domain.errors import ConcurrentModification, DuplicateIdempotencyKey
from apps.photos.domain.submission import (
    PhotoSubmission,
    SubmissionKind,
    SubmissionStatus,
)
from apps.photos.infrastructure.models import PhotoSubmission as PhotoSubmissionModel
from apps.shared.domain.store import StoreReference

_UNIQUE_KEY_CONSTRAINT = "photos_photosubmission_store_creator_key_unique"

# Entity fields that map one to one onto model fields; the id and auto timestamps differ.
_MAPPED_FIELDS = (
    "store_id",
    "created_by_id",
    "kind",
    "target_product_id",
    "photographed_variant_id",
    "original_key",
    "preview_key",
    "corners",
    "crop",
    "light_correction",
    "pipeline_version",
    "status",
    "failure_code",
    "failure_message",
    "attempts",
    "version",
    "result_media_id",
    "idempotency_key",
    "request_fingerprint",
    "applied_at",
    "applied_by_id",
    "discarded_at",
)


def _to_entity(row: PhotoSubmissionModel) -> PhotoSubmission:
    return PhotoSubmission(
        id=row.pk,
        store_id=row.store_id,
        created_by_id=row.created_by_id,
        kind=SubmissionKind(row.kind),
        target_product_id=row.target_product_id,
        photographed_variant_id=row.photographed_variant_id,
        original_key=row.original_key,
        preview_key=row.preview_key,
        corners=row.corners,
        crop=row.crop,
        light_correction=row.light_correction,
        pipeline_version=row.pipeline_version,
        status=SubmissionStatus(row.status),
        failure_code=row.failure_code,
        failure_message=row.failure_message,
        attempts=row.attempts,
        version=row.version,
        result_media_id=row.result_media_id,
        idempotency_key=row.idempotency_key,
        request_fingerprint=row.request_fingerprint,
        applied_at=row.applied_at,
        applied_by_id=row.applied_by_id,
        discarded_at=row.discarded_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _apply_entity(row: PhotoSubmissionModel, submission: PhotoSubmission) -> None:
    for field in _MAPPED_FIELDS:
        setattr(row, field, getattr(submission, field))


def _is_duplicate_idempotency_key(error: IntegrityError) -> bool:
    cause = error.__cause__
    constraint = getattr(getattr(cause, "diag", None), "constraint_name", None)
    if constraint == _UNIQUE_KEY_CONSTRAINT:
        return True
    message = str(error)
    return _UNIQUE_KEY_CONSTRAINT in message or (
        "UNIQUE constraint failed" in message and "idempotency_key" in message
    )


class DjangoPhotoSubmissionRepository:
    """Read and write photo submissions, filtering every query by store."""

    def get(self, store: StoreReference, submission_id: int) -> PhotoSubmission | None:
        row = PhotoSubmissionModel.objects.filter(pk=submission_id, store_id=store.id).first()
        return _to_entity(row) if row is not None else None

    def get_for_update(self, store: StoreReference, submission_id: int) -> PhotoSubmission | None:
        row = (
            PhotoSubmissionModel.objects.select_for_update()
            .filter(pk=submission_id, store_id=store.id)
            .first()
        )
        return _to_entity(row) if row is not None else None

    def get_by_idempotency_key(
        self, store: StoreReference, created_by: int, key: str
    ) -> PhotoSubmission | None:
        row = PhotoSubmissionModel.objects.filter(
            store_id=store.id,
            created_by_id=created_by,
            idempotency_key=key,
        ).first()
        return _to_entity(row) if row is not None else None

    def add(self, submission: PhotoSubmission) -> PhotoSubmission:
        row = PhotoSubmissionModel()
        _apply_entity(row, submission)
        try:
            with transaction.atomic():
                row.save()
        except IntegrityError as error:
            if not _is_duplicate_idempotency_key(error):
                raise
            raise DuplicateIdempotencyKey(
                "This idempotency key was already used in this store."
            ) from error
        return _to_entity(row)

    def list_for_product(
        self,
        store: StoreReference,
        product_id: int,
        media_ids: list[int],
    ) -> list[PhotoSubmission]:
        rows = (
            PhotoSubmissionModel.objects.filter(store_id=store.id, discarded_at__isnull=True)
            .filter(Q(target_product_id=product_id) | Q(result_media_id__in=media_ids))
            .order_by("-created_at", "-pk")
        )
        return [_to_entity(row) for row in rows]

    def save(self, submission: PhotoSubmission) -> PhotoSubmission:
        changes = {field: getattr(submission, field) for field in _MAPPED_FIELDS}
        changes["version"] = F("version") + 1
        changes["updated_at"] = timezone.now()
        updated = PhotoSubmissionModel.objects.filter(
            pk=submission.id,
            store_id=submission.store_id,
            version=submission.version,
        ).update(**changes)
        if updated == 0:
            raise ConcurrentModification(
                "This submission was changed by another request; reload it and try again."
            )
        submission.version += 1
        row = PhotoSubmissionModel.objects.get(pk=submission.id, store_id=submission.store_id)
        return _to_entity(row)
