"""DRF serializers for the staff photo upload and status API."""

from django.urls import reverse
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.catalog.media import media_url, rendition_url
from apps.photos.application.get_photo_submission import PhotoSubmissionView
from apps.photos.domain.submission import SubmissionKind


class UploadPhotoSerializer(serializers.Serializer):
    """The multipart body of one photo upload; the key travels in a header."""

    file = serializers.FileField()
    kind = serializers.ChoiceField(choices=[kind.value for kind in SubmissionKind])
    target_product = serializers.IntegerField(required=False, allow_null=True)
    photographed_variant = serializers.IntegerField(required=False, allow_null=True)
    corners = serializers.JSONField(required=False, allow_null=True)
    crop = serializers.JSONField(required=False, allow_null=True)
    light_correction = serializers.BooleanField(required=False, default=True)


class RedoPhotoSerializer(serializers.Serializer):
    """The new corners or crop of a redo; an omitted field keeps its stored value."""

    corners = serializers.JSONField(required=False, allow_null=True)
    crop = serializers.JSONField(required=False, allow_null=True)


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
