"""Shared support for catalog commands that act on the operator's behalf."""

import json

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth import get_user_model
from django.core.management.base import CommandError

from apps.stores.models import Store

PRICE_FIELDS = ("price", "compare_at_price", "cost")


def get_active_store(slug):
    """Return the active store named by slug, or reject the command."""
    try:
        store = Store.objects.get(slug=slug)
    except Store.DoesNotExist as error:
        raise CommandError(f"No store with slug {slug!r}.") from error
    if not store.is_active:
        raise CommandError(f"Store {slug!r} is inactive.")
    return store


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
    detail = variant_change_detail(old_values, variant)
    if detail is None:
        return

    LogEntry.objects.log_actions(operator.pk, [variant], CHANGE, [{"changed": detail}])


def build_variant_change_entry(operator, variant, old_values, *, content_type):
    """Build, but do not save, the admin entry for one changed variant."""
    detail = variant_change_detail(old_values, variant)
    if detail is None:
        return None

    return LogEntry(
        user_id=operator.pk,
        content_type_id=content_type.pk,
        object_id=str(variant.pk),
        object_repr=str(variant)[:200],
        action_flag=CHANGE,
        change_message=json.dumps([{"changed": detail}]),
    )


def variant_change_detail(old_values, variant):
    """Return the changed price fields, or None when no price field changed."""
    changes = {}
    for field, old in old_values.items():
        new = getattr(variant, field)
        if old != new:
            changes[field] = {"old": _serialise(old), "new": _serialise(new)}
    if not changes:
        return None

    # The admin's get_change_message() reads "fields"; the values keep the detail it omits.
    return {"fields": list(changes), **changes}


def _serialise(value):
    return None if value is None else str(value)
