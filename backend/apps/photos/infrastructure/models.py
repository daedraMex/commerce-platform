from django.conf import settings
from django.db import models

from apps.stores.models import Store


class PhotoSubmission(models.Model):
    """One staff upload of a phone photo, tracked from upload to an applied Media (ADR-0028)."""

    class Kind(models.TextChoices):
        RECTANGLE = "rectangle", "Rectangle"
        CONTOUR = "contour", "Contour"
        GROUP = "group", "Group"

    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        PROCESSING = "processing", "Processing"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="photo_submissions")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="photo_submissions",
    )
    kind = models.CharField(max_length=10, choices=Kind.choices)
    target_product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="photo_submissions",
        null=True,
        blank=True,
    )
    photographed_variant = models.ForeignKey(
        "catalog.ProductVariant",
        on_delete=models.PROTECT,
        related_name="photo_submissions",
        null=True,
        blank=True,
    )
    original_key = models.CharField(max_length=255, blank=True)
    preview_key = models.CharField(max_length=255, blank=True)
    corners = models.JSONField(null=True, blank=True)
    crop = models.JSONField(null=True, blank=True)
    light_correction = models.BooleanField(default=True)
    pipeline_version = models.CharField(max_length=50, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UPLOADED)
    failure_code = models.CharField(max_length=100, blank=True)
    failure_message = models.TextField(blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    version = models.PositiveIntegerField(default=0)
    result_media = models.ForeignKey(
        "catalog.Media",
        on_delete=models.PROTECT,
        related_name="photo_submissions",
        null=True,
        blank=True,
    )
    idempotency_key = models.CharField(max_length=255)
    request_fingerprint = models.CharField(max_length=64)
    applied_at = models.DateTimeField(null=True, blank=True)
    applied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="applied_photo_submissions",
        null=True,
        blank=True,
    )
    discarded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("store", "-created_at", "-pk")
        constraints = [
            models.UniqueConstraint(
                fields=("store", "created_by", "idempotency_key"),
                name="photos_photosubmission_store_creator_key_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["uploaded", "processing", "ready", "failed"]),
                name="photos_photosubmission_status_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        kind="group",
                        target_product__isnull=True,
                        photographed_variant__isnull=True,
                    )
                    | models.Q(
                        kind__in=["rectangle", "contour"],
                        target_product__isnull=False,
                    )
                ),
                name="photos_photosubmission_kind_target_valid",
            ),
            models.CheckConstraint(
                condition=(models.Q(applied_at__isnull=True) | models.Q(discarded_at__isnull=True)),
                name="photos_photosubmission_applied_or_discarded",
            ),
        ]

    def __str__(self):
        return f"{self.store} / {self.kind} / {self.pk or 'new'}"
