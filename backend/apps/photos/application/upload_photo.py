"""Create a Photo submission from one staff upload, idempotently (ADR-0028)."""

from dataclasses import dataclass

from apps.photos.application.fingerprints import photo_request_fingerprint
from apps.photos.application.ports import (
    MediaUploader,
    PhotoCatalog,
    PhotoProcessingQueue,
    PhotoSubmissionRepository,
)
from apps.photos.domain.errors import DuplicateIdempotencyKey, InvalidSubmissionTarget
from apps.photos.domain.submission import (
    INDIVIDUAL_KINDS,
    PhotoSubmission,
    SubmissionKind,
    resolve_replay,
)
from apps.shared.domain.permissions import MANAGE_CATALOG
from apps.shared.domain.ports import Authorizer
from apps.shared.domain.store import StoreReference


@dataclass(frozen=True, slots=True)
class UploadPhotoCommand:
    """Everything one multipart photo upload carries."""

    store: StoreReference
    user_id: int
    kind: SubmissionKind
    content: bytes
    idempotency_key: str
    target_product_id: int | None = None
    photographed_variant_id: int | None = None
    corners: list | None = None
    crop: dict | None = None
    light_correction: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", SubmissionKind(self.kind))


@dataclass(frozen=True, slots=True)
class UploadPhotoResult:
    """The submission a replay or a new upload refers to, and whether it was created now."""

    submission: PhotoSubmission
    created: bool


class UploadPhoto:
    """Authorize, normalize and store an upload once per store, creator and key."""

    def __init__(
        self,
        *,
        repository: PhotoSubmissionRepository,
        uploader: MediaUploader,
        catalog: PhotoCatalog,
        authorizer: Authorizer,
        queue: PhotoProcessingQueue,
    ):
        self._repository = repository
        self._uploader = uploader
        self._catalog = catalog
        self._authorizer = authorizer
        self._queue = queue

    def __call__(self, command: UploadPhotoCommand) -> UploadPhotoResult:
        self._authorizer.require(command.user_id, command.store, MANAGE_CATALOG)

        fingerprint = photo_request_fingerprint(
            kind=command.kind,
            target_product_id=command.target_product_id,
            photographed_variant_id=command.photographed_variant_id,
            corners=command.corners,
            crop=command.crop,
            light_correction=command.light_correction,
            content=command.content,
        )
        existing = self._repository.get_by_idempotency_key(
            command.store, command.user_id, command.idempotency_key
        )
        replay = resolve_replay(existing, fingerprint)
        if replay is not None:
            return UploadPhotoResult(submission=replay, created=False)

        submission = PhotoSubmission(
            store_id=command.store.id,
            created_by_id=command.user_id,
            kind=command.kind,
            target_product_id=command.target_product_id,
            photographed_variant_id=command.photographed_variant_id,
            corners=command.corners,
            crop=command.crop,
            light_correction=command.light_correction,
            idempotency_key=command.idempotency_key,
            request_fingerprint=fingerprint,
        )
        self._validate_target(command)
        uploaded = self._uploader.upload(command.store, command.content)
        submission.original_key = uploaded.original_key
        submission.preview_key = uploaded.preview_key

        try:
            saved = self._repository.add(submission)
        except DuplicateIdempotencyKey:
            existing = self._repository.get_by_idempotency_key(
                command.store, command.user_id, command.idempotency_key
            )
            replay = resolve_replay(existing, fingerprint)
            if replay is None:
                raise
            return UploadPhotoResult(submission=replay, created=False)
        self._queue.enqueue(command.store, saved.id)
        return UploadPhotoResult(submission=saved, created=True)

    def _validate_target(self, command: UploadPhotoCommand) -> None:
        if command.kind not in INDIVIDUAL_KINDS:
            return

        product = self._catalog.get_product(command.store, command.target_product_id)
        if product is None:
            raise InvalidSubmissionTarget("The target product does not belong to this store.")
        if command.photographed_variant_id is None:
            return

        variant = self._catalog.get_variant(command.store, command.photographed_variant_id)
        if variant is None or variant.product_id != product.id:
            raise InvalidSubmissionTarget(
                "The photographed variant does not belong to the target product."
            )
