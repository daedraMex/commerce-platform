"""DRF serializers for the staff photo upload and status API."""

import json
import math
from collections.abc import Mapping

from django.urls import reverse
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.catalog.media import media_url, rendition_url
from apps.photos.application.get_photo_submission import PhotoSubmissionView
from apps.photos.application.get_product_images import CarouselImage
from apps.photos.domain.submission import MAX_REDOS, SubmissionKind


def _json_value(value, message):
    """Accept both a JSON body value and the JSON string a multipart field carries."""
    if isinstance(value, (str, bytes)):
        try:
            return json.loads(value)
        except (TypeError, ValueError) as error:
            raise serializers.ValidationError(message) from error
    return value


class FiniteNumberField(serializers.FloatField):
    """A JSON number, rejecting booleans, strings, NaN and infinity."""

    default_error_messages = {"invalid": "The value must be a finite number."}

    def to_internal_value(self, data):
        if isinstance(data, bool) or not isinstance(data, (int, float)):
            self.fail("invalid")
        try:
            is_finite = math.isfinite(data)
        except OverflowError:
            is_finite = False
        if not is_finite:
            self.fail("invalid")
        return data


class PhotoPointSerializer(serializers.Serializer):
    """One `{x, y}` corner of the photographed area."""

    x = FiniteNumberField()
    y = FiniteNumberField()

    def to_internal_value(self, data):
        if not isinstance(data, Mapping) or set(data) != {"x", "y"}:
            raise serializers.ValidationError(
                "Every corner must be an object with only 'x' and 'y'."
            )
        return super().to_internal_value(data)


class PhotoCornersField(serializers.ListField):
    """Exactly four `{x, y}` points, from a JSON list or its multipart string."""

    default_error_messages = {
        "not_a_list": "The corners must be a list of four points.",
        "min_length": "A photo needs exactly four corners.",
        "max_length": "A photo needs exactly four corners.",
    }

    def __init__(self, **kwargs):
        super().__init__(
            child=PhotoPointSerializer(),
            min_length=4,
            max_length=4,
            **kwargs,
        )

    def to_internal_value(self, data):
        data = _json_value(data, "The corners must be a JSON list of four points.")
        if not isinstance(data, list):
            self.fail("not_a_list")
        return super().to_internal_value(data)


class PhotoCropSerializer(serializers.Serializer):
    """The crop rectangle, from a JSON object or its multipart string."""

    x = FiniteNumberField()
    y = FiniteNumberField()
    width = FiniteNumberField()
    height = FiniteNumberField()

    def to_internal_value(self, data):
        data = _json_value(
            data,
            "The crop must be a JSON object with numeric x, y, width and height.",
        )
        if not isinstance(data, Mapping):
            raise serializers.ValidationError(
                "The crop must be an object with numeric x, y, width and height."
            )
        return super().to_internal_value(data)


class PhotoAdjustmentSerializer(serializers.Serializer):
    """The optional corners and crop shared by upload and redo, validated for shape."""

    corners = PhotoCornersField(required=False)
    crop = PhotoCropSerializer(required=False)


class UploadPhotoSerializer(PhotoAdjustmentSerializer):
    """The multipart body of one photo upload; the key travels in a header."""

    file = serializers.FileField()
    kind = serializers.ChoiceField(choices=[kind.value for kind in SubmissionKind])
    target_product = serializers.IntegerField(required=False, allow_null=True)
    photographed_variant = serializers.IntegerField(required=False, allow_null=True)
    light_correction = serializers.BooleanField(required=False, default=True)


class RedoPhotoSerializer(PhotoAdjustmentSerializer):
    """The new corners or crop of a redo; an omitted field keeps its stored value."""


class GroupPhotoApplySerializer(serializers.Serializer):
    """The optional product selection of a group photo's first apply."""

    product_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=True,
        required=False,
    )


class GroupPhotoLinksSerializer(serializers.Serializer):
    """The full product selection a group photo should be linked to."""

    product_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=True,
    )


class PhotoResultMediaSerializer(serializers.Serializer):
    """The public Media a ready submission produced, with its derived renditions."""

    media_id = serializers.IntegerField(source="id")
    url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    medium_url = serializers.SerializerMethodField()
    width = serializers.IntegerField()
    height = serializers.IntegerField()

    @extend_schema_field(serializers.CharField())
    def get_url(self, media):
        return media_url(media.storage_key)

    @extend_schema_field(serializers.CharField())
    def get_thumbnail_url(self, media):
        return rendition_url(media, "thumbnail")

    @extend_schema_field(serializers.CharField())
    def get_medium_url(self, media):
        return rendition_url(media, "medium")


class CarouselImageSerializer(serializers.Serializer):
    """One staff carousel tile with its renditions and the photo submission behind it."""

    id = serializers.IntegerField(allow_null=True)
    media_id = serializers.IntegerField(source="media.id")
    photo_submission_id = serializers.IntegerField(allow_null=True)
    active = serializers.BooleanField()
    role = serializers.CharField(allow_null=True)
    position = serializers.IntegerField(allow_null=True)
    url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    medium_url = serializers.SerializerMethodField()
    alt_text = serializers.CharField(source="media.alt_text")
    width = serializers.IntegerField(source="media.width")
    height = serializers.IntegerField(source="media.height")

    @extend_schema_field(serializers.CharField())
    def get_url(self, image: CarouselImage):
        return media_url(image.media.storage_key)

    @extend_schema_field(serializers.CharField())
    def get_thumbnail_url(self, image: CarouselImage):
        return rendition_url(image.media, "thumbnail")

    @extend_schema_field(serializers.CharField())
    def get_medium_url(self, image: CarouselImage):
        return rendition_url(image.media, "medium")


class ProductCarouselSerializer(serializers.Serializer):
    """A product's carousel: active images in order, then inactive ones."""

    product_id = serializers.IntegerField()
    images = CarouselImageSerializer(many=True)


class ProductImageOrderSerializer(serializers.Serializer):
    """The full ordered list of a product's active image link ids."""

    image_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=True,
    )


class PhotoSubmissionSerializer(serializers.Serializer):
    """One submission's state, readable failure, private preview and result."""

    id = serializers.IntegerField(source="submission.id")
    kind = serializers.CharField(source="submission.kind")
    status = serializers.CharField(source="submission.status")
    failure_code = serializers.CharField(source="submission.failure_code")
    failure_message = serializers.CharField(source="submission.failure_message")
    preview_url = serializers.SerializerMethodField()
    result = serializers.SerializerMethodField()
    linked_product_ids = serializers.ListField(child=serializers.IntegerField(), read_only=True)
    pipeline_version = serializers.CharField(source="submission.pipeline_version")
    attempts = serializers.IntegerField(source="submission.attempts")
    redos = serializers.IntegerField(source="submission.redos")
    redos_remaining = serializers.SerializerMethodField()
    version = serializers.IntegerField(source="submission.version")
    target_product_id = serializers.IntegerField(
        source="submission.target_product_id", allow_null=True
    )
    photographed_variant_id = serializers.IntegerField(
        source="submission.photographed_variant_id", allow_null=True
    )
    light_correction = serializers.BooleanField(source="submission.light_correction")
    corners = serializers.JSONField(source="submission.corners", allow_null=True)
    crop = serializers.JSONField(source="submission.crop", allow_null=True)
    applied_at = serializers.DateTimeField(
        source="submission.applied_at", allow_null=True, required=False
    )
    discarded_at = serializers.DateTimeField(
        source="submission.discarded_at", allow_null=True, required=False
    )
    created_at = serializers.DateTimeField(source="submission.created_at")
    updated_at = serializers.DateTimeField(source="submission.updated_at")

    @extend_schema_field(serializers.IntegerField())
    def get_redos_remaining(self, view):
        return max(MAX_REDOS - view.submission.redos, 0)

    @extend_schema_field(serializers.CharField())
    def get_preview_url(self, view):
        request = self.context.get("request")
        version = getattr(request, "version", "v1")
        return reverse(
            "staff-photo-preview",
            kwargs={"version": version, "pk": view.submission.id},
        )

    @extend_schema_field(PhotoResultMediaSerializer(allow_null=True))
    def get_result(self, view: PhotoSubmissionView):
        if view.result_media is None:
            return None
        return PhotoResultMediaSerializer(view.result_media).data
