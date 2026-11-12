"""Staff endpoints to upload, read, apply, redo, retry and discard photo submissions."""

from django.http import FileResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.photos.application.apply_photo import ApplyPhoto
from apps.photos.application.discard_photo import DiscardPhoto
from apps.photos.application.get_photo_submission import GetPhotoSubmission, PhotoSubmissionView
from apps.photos.application.redo_photo import RedoPhoto
from apps.photos.application.retry_photo import RetryPhoto
from apps.photos.application.upload_photo import UploadPhoto, UploadPhotoCommand
from apps.photos.interfaces.serializers import (
    PhotoSubmissionSerializer,
    RedoPhotoSerializer,
    UploadPhotoSerializer,
)
from apps.shared.domain.exceptions import NotFoundError
from apps.shared.interfaces.views import StoreScopedMixin
from config.dependencies import (
    get_authorizer,
    get_catalog_service,
    get_media_uploader,
    get_photo_processing_queue,
    get_photo_submission_repository,
    get_private_media_reader,
)
from config.schema import problem_response

STORE_HEADER_PARAMETER = OpenApiParameter(
    "X-Store",
    location=OpenApiParameter.HEADER,
    required=True,
    description="Slug of the store the request is scoped to, such as home.",
)

IDEMPOTENCY_KEY_PARAMETER = OpenApiParameter(
    "Idempotency-Key",
    location=OpenApiParameter.HEADER,
    required=True,
    description=(
        "Client key that makes a repeated upload return the original submission. "
        "Reusing it with a different payload returns 409 idempotency_conflict."
    ),
)

STORE_ERRORS = problem_response(
    400,
    ("store_header_missing", "The X-Store header is required."),
    ("store_header_invalid", "The X-Store header is not a valid store slug."),
    ("store_not_found", "No active store matches the X-Store header."),
)

UPLOAD_ERRORS = problem_response(
    400,
    ("store_header_missing", "The X-Store header is required."),
    ("store_header_invalid", "The X-Store header is not a valid store slug."),
    ("store_not_found", "No active store matches the X-Store header."),
    ("validation_error", "Validation failed."),
    ("submission_invalid_target", "A rectangle or contour photo needs a target product."),
    ("invalid_image", "The file is not an image this service can read."),
    ("too_large", "The photo is larger than 25 MB."),
    ("too_many_pixels", "The photo has more than 50 megapixels."),
)

PHOTO_SUBMISSION_EXAMPLE = OpenApiExample(
    "Ready photo submission",
    value={
        "id": 12,
        "kind": "rectangle",
        "status": "ready",
        "failure_code": "",
        "failure_message": "",
        "preview_url": "/api/v1/staff/photos/12/preview/",
        "result": {
            "media_id": 44,
            "url": "https://media.example.com/stores/1/media/abc123.jpg",
            "thumbnail_url": (
                "https://media.example.com/stores/1/media/renditions/abc123-320w-v1.webp"
            ),
            "medium_url": (
                "https://media.example.com/stores/1/media/renditions/abc123-800w-v1.webp"
            ),
            "width": 1200,
            "height": 1500,
        },
        "pipeline_version": "2026-11-11.2",
        "attempts": 1,
        "version": 4,
        "applied_at": "2026-11-12T09:32:00Z",
        "discarded_at": None,
        "target_product_id": 7,
        "photographed_variant_id": 3,
        "light_correction": True,
        "corners": [
            {"x": 0.1, "y": 0.1},
            {"x": 0.9, "y": 0.1},
            {"x": 0.9, "y": 0.9},
            {"x": 0.1, "y": 0.9},
        ],
        "crop": {"x": 120, "y": 180, "width": 960, "height": 1200},
        "created_at": "2026-11-12T09:30:00Z",
        "updated_at": "2026-11-12T09:31:15Z",
    },
    response_only=True,
)

UPLOAD_REQUEST_EXAMPLE = OpenApiExample(
    "Rectangle blanket photo",
    value={
        "file": "<binary JPEG>",
        "kind": "rectangle",
        "target_product": 7,
        "photographed_variant": 3,
        "corners": [
            {"x": 0.1, "y": 0.1},
            {"x": 0.9, "y": 0.1},
            {"x": 0.9, "y": 0.9},
            {"x": 0.1, "y": 0.9},
        ],
        "crop": {"x": 120, "y": 180, "width": 960, "height": 1200},
        "light_correction": True,
    },
    request_only=True,
)

AUTH_ERRORS = {
    **problem_response(
        401,
        ("not_authenticated", "Authentication credentials were not provided."),
        ("token_invalid", "Given token not valid for any token type"),
    ),
}

MANAGE_CATALOG_ERRORS = problem_response(
    403,
    ("permission_denied", "You do not have permission to manage the catalog."),
)


def _submission_view(store, submission):
    result_media = None
    if submission.result_media_id is not None:
        result_media = get_catalog_service().get_media(store, submission.result_media_id)
    return PhotoSubmissionView(submission=submission, result_media=result_media)


def _idempotency_key(request):
    key = request.headers.get("Idempotency-Key") or request.data.get("idempotency_key")
    if not isinstance(key, str) or not key.strip():
        raise ValidationError({"Idempotency-Key": ["This header is required."]})
    key = key.strip()
    if len(key) > 255:
        raise ValidationError({"Idempotency-Key": ["Use at most 255 characters."]})
    return key


FIELDS_WITH_ALIASES = (
    ("target", "target_product"),
    ("target_product_id", "target_product"),
    ("variant", "photographed_variant"),
    ("photographed_variant_id", "photographed_variant"),
    ("light", "light_correction"),
)


def _upload_payload(request):
    payload = request.data.copy()
    for alias, canonical in FIELDS_WITH_ALIASES:
        if alias in payload and canonical not in payload:
            payload[canonical] = payload[alias]
    return payload


@extend_schema(
    parameters=[STORE_HEADER_PARAMETER, IDEMPOTENCY_KEY_PARAMETER],
    request=UploadPhotoSerializer,
    responses={
        201: OpenApiResponse(
            response=PhotoSubmissionSerializer,
            description="The new photo submission, with its private preview URL.",
            examples=[PHOTO_SUBMISSION_EXAMPLE],
        ),
        200: OpenApiResponse(
            response=PhotoSubmissionSerializer,
            description="The original submission a repeated idempotency key refers to.",
            examples=[PHOTO_SUBMISSION_EXAMPLE],
        ),
        **UPLOAD_ERRORS,
        **AUTH_ERRORS,
        **MANAGE_CATALOG_ERRORS,
        **problem_response(
            409,
            (
                "idempotency_conflict",
                "This idempotency key was already used with a different request.",
            ),
        ),
    },
)
class StaffPhotoUploadView(StoreScopedMixin, APIView):
    """Accept one multipart photo and create its submission idempotently."""

    def post(self, request, *args, **kwargs):
        serializer = UploadPhotoSerializer(data=_upload_payload(request))
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        command = UploadPhotoCommand(
            store=request.store,
            user_id=request.user.id,
            kind=data["kind"],
            content=data["file"].read(),
            idempotency_key=_idempotency_key(request),
            target_product_id=data.get("target_product"),
            photographed_variant_id=data.get("photographed_variant"),
            corners=data.get("corners"),
            crop=data.get("crop"),
            light_correction=data["light_correction"],
        )
        result = UploadPhoto(
            repository=get_photo_submission_repository(),
            uploader=get_media_uploader(),
            catalog=get_catalog_service(),
            authorizer=get_authorizer(),
        )(command)

        body = PhotoSubmissionSerializer(
            _submission_view(request.store, result.submission),
            context={"request": request},
        ).data
        response_status = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
        return Response(body, status=response_status)


@extend_schema(
    parameters=[STORE_HEADER_PARAMETER],
    responses={
        200: OpenApiResponse(
            response=PhotoSubmissionSerializer,
            description="The submission's status, failure, private preview and result Media.",
            examples=[PHOTO_SUBMISSION_EXAMPLE],
        ),
        **STORE_ERRORS,
        **AUTH_ERRORS,
        **MANAGE_CATALOG_ERRORS,
        **problem_response(
            404, ("not_found", "No photo submission matches this id in this store.")
        ),
    },
)
class StaffPhotoDetailView(StoreScopedMixin, APIView):
    """Return one submission of the request's store."""

    def get(self, request, pk, *args, **kwargs):
        view = GetPhotoSubmission(
            repository=get_photo_submission_repository(),
            catalog=get_catalog_service(),
            authorizer=get_authorizer(),
        )(request.store, user_id=request.user.id, submission_id=pk)
        return Response(PhotoSubmissionSerializer(view, context={"request": request}).data)


@extend_schema(
    parameters=[STORE_HEADER_PARAMETER],
    responses={
        (200, "image/jpeg"): OpenApiResponse(
            response=OpenApiTypes.BINARY,
            description="The downscaled private preview of the uploaded original.",
        ),
        **STORE_ERRORS,
        **AUTH_ERRORS,
        **MANAGE_CATALOG_ERRORS,
        **problem_response(
            404, ("not_found", "No photo submission matches this id in this store.")
        ),
    },
)
class StaffPhotoPreviewView(StoreScopedMixin, APIView):
    """Stream the private preview after the same authorization as the status endpoint."""

    def get(self, request, pk, *args, **kwargs):
        view = GetPhotoSubmission(
            repository=get_photo_submission_repository(),
            catalog=get_catalog_service(),
            authorizer=get_authorizer(),
        )(request.store, user_id=request.user.id, submission_id=pk)
        submission = view.submission
        if not submission.preview_key:
            raise NotFoundError("This photo submission has no preview yet.")
        try:
            preview = get_private_media_reader().open(request.store, submission.preview_key)
        except OSError as error:
            raise NotFoundError("The preview file is not available.") from error
        return FileResponse(preview, content_type="image/jpeg")


ACTION_ERRORS = {
    **STORE_ERRORS,
    **AUTH_ERRORS,
    **MANAGE_CATALOG_ERRORS,
    **problem_response(404, ("not_found", "No photo submission matches this id in this store.")),
}


def _action_body(request, submission):
    return PhotoSubmissionSerializer(
        _submission_view(request.store, submission),
        context={"request": request},
    ).data


@extend_schema(
    request=None,
    parameters=[STORE_HEADER_PARAMETER],
    responses={
        200: OpenApiResponse(
            response=PhotoSubmissionSerializer,
            description="The applied submission, now the product's active main image.",
            examples=[PHOTO_SUBMISSION_EXAMPLE],
        ),
        **ACTION_ERRORS,
        **problem_response(
            409,
            (
                "submission_cannot_apply",
                "Only a ready individual photo can be applied.",
            ),
        ),
    },
)
class StaffPhotoApplyView(StoreScopedMixin, APIView):
    """Link a ready individual photo as the product's active main image."""

    def post(self, request, pk, *args, **kwargs):
        submission = ApplyPhoto(
            repository=get_photo_submission_repository(),
            catalog=get_catalog_service(),
            authorizer=get_authorizer(),
        )(request.store, user_id=request.user.id, submission_id=pk)
        return Response(_action_body(request, submission))


@extend_schema(
    parameters=[STORE_HEADER_PARAMETER],
    request=RedoPhotoSerializer,
    responses={
        200: OpenApiResponse(
            response=PhotoSubmissionSerializer,
            description="The submission back in processing with a new attempt queued.",
            examples=[PHOTO_SUBMISSION_EXAMPLE],
        ),
        **ACTION_ERRORS,
        **problem_response(
            400,
            ("validation_error", "Validation failed."),
        ),
        **problem_response(
            409,
            (
                "submission_cannot_redo",
                "Only a ready photo can be redone.",
            ),
        ),
    },
)
class StaffPhotoRedoView(StoreScopedMixin, APIView):
    """Redo a ready photo with new corners or crop, keeping the previous result Media."""

    def post(self, request, pk, *args, **kwargs):
        serializer = RedoPhotoSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        submission = RedoPhoto(
            repository=get_photo_submission_repository(),
            queue=get_photo_processing_queue(),
            authorizer=get_authorizer(),
        )(
            request.store,
            user_id=request.user.id,
            submission_id=pk,
            corners=data.get("corners"),
            crop=data.get("crop"),
        )
        return Response(_action_body(request, submission))


@extend_schema(
    request=None,
    parameters=[STORE_HEADER_PARAMETER],
    responses={
        200: OpenApiResponse(
            response=PhotoSubmissionSerializer,
            description="The failed submission with a new processing attempt queued.",
            examples=[PHOTO_SUBMISSION_EXAMPLE],
        ),
        **ACTION_ERRORS,
        **problem_response(
            409,
            (
                "submission_cannot_start_processing",
                "Only a failed photo can be retried.",
            ),
            (
                "submission_attempts_exhausted",
                "This submission already used its processing attempts.",
            ),
        ),
    },
)
class StaffPhotoRetryView(StoreScopedMixin, APIView):
    """Retry a failed photo submission with another processing attempt."""

    def post(self, request, pk, *args, **kwargs):
        submission = RetryPhoto(
            repository=get_photo_submission_repository(),
            queue=get_photo_processing_queue(),
            authorizer=get_authorizer(),
        )(request.store, user_id=request.user.id, submission_id=pk)
        return Response(_action_body(request, submission))


@extend_schema(
    request=None,
    parameters=[STORE_HEADER_PARAMETER],
    responses={
        200: OpenApiResponse(
            response=PhotoSubmissionSerializer,
            description="The discarded submission; only its private files were removed.",
            examples=[PHOTO_SUBMISSION_EXAMPLE],
        ),
        **ACTION_ERRORS,
        **problem_response(
            409,
            (
                "submission_cannot_discard",
                "An applied or already discarded photo cannot be discarded.",
            ),
        ),
    },
)
class StaffPhotoDiscardView(StoreScopedMixin, APIView):
    """Discard an unapplied submission, deleting only its private original and preview."""

    def post(self, request, pk, *args, **kwargs):
        submission = DiscardPhoto(
            repository=get_photo_submission_repository(),
            uploader=get_media_uploader(),
            authorizer=get_authorizer(),
        )(request.store, user_id=request.user.id, submission_id=pk)
        return Response(_action_body(request, submission))
