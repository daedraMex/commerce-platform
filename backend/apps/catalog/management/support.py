"""Shared support for catalog commands that act on the operator's behalf."""

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth import get_user_model
from django.core.management.base import CommandError

PRICE_FIELDS = ("price", "compare_at_price", "cost")


def resolve_operator(email: str):
    """Return the active superuser named by email, or reject the command before it reads data."""
    User = get_user_model()
    try:
        # The natural key lookup normalizes the email the way the User stores it.
        user = User._default_manager.get_by_natural_key(email)
    except User.DoesNotExist as error:
        raise CommandError(f"No user with email {email!r}.") from error

    if not user.is_active or not user.is_superuser:
        raise CommandError(f"{email!r} is not an active superuser.")
    return user


def snapshot(variant, fields):
    """Capture the values an audit entry compares against, before they change."""
    return {field: getattr(variant, field) for field in fields}


def record_variant_change(operator, variant, old_values):
    """Write one admin log entry with the old and new values of a changed variant."""
    changes = {}
    for field, old in old_values.items():
        new = getattr(variant, field)
        if old != new:
            changes[field] = {"old": _serialise(old), "new": _serialise(new)}
    if not changes:
        return

    # The admin's get_change_message() reads "fields"; the values keep the detail it omits.
    detail = {"fields": list(changes), **changes}
    LogEntry.objects.log_actions(operator.pk, [variant], CHANGE, [{"changed": detail}])


def _serialise(value):
    return None if value is None else str(value)
