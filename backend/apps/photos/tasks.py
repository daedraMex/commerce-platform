"""Celery discovers each app's tasks module; the task itself lives in interfaces."""

from apps.photos.interfaces.tasks import process_photo_submission

__all__ = ["process_photo_submission"]
