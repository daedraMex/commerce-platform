from django.contrib import admin

from apps.photos.models import PhotoSubmission


@admin.register(PhotoSubmission)
class PhotoSubmissionAdmin(admin.ModelAdmin):
    """Read-only for platform operators: submissions are created by the API, never edited."""

    list_display = (
        "id",
        "store",
        "kind",
        "status",
        "created_by",
        "attempts",
        "applied_at",
        "discarded_at",
        "created_at",
    )
    list_filter = ("store", "status")
    search_fields = ("idempotency_key", "original_key", "preview_key")
    ordering = ("-created_at", "-pk")
    readonly_fields = tuple(field.name for field in PhotoSubmission._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
