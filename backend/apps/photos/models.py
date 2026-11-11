"""Django finds models through ``apps.photos.models``; the model lives in infrastructure."""

from apps.photos.infrastructure.models import PhotoSubmission

__all__ = ["PhotoSubmission"]
