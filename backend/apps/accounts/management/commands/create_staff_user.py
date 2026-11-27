"""Create a staff login and grant its store membership without touching passwords."""

import logging

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Role, StoreMembership
from apps.stores.services import get_store_by_slug

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Create a staff user with an unusable password if absent and grant or keep its "
        "store membership. It never resets a password or silently escalates a role."
    )

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--store", required=True)
        parser.add_argument("--role", required=True)

    @transaction.atomic
    def handle(self, *args, email, store, role, **options):
        role_object = _find_role(role)
        store_object = _find_store(store)
        user, created = _get_or_create_user(email)
        membership_message = _ensure_membership(user, store_object, role_object)
        status = "created" if created else "already exists"
        message = f"User {user.email!r} {status}; {membership_message}."
        logger.info(message)
        self.stdout.write(message)


def _find_role(name):
    try:
        return Role.objects.get(name=name)
    except Role.DoesNotExist as error:
        valid_roles = ", ".join(Role.objects.order_by("name").values_list("name", flat=True))
        raise CommandError(f"Unknown role {name!r}. Valid roles: {valid_roles}.") from error


def _find_store(slug):
    store = get_store_by_slug(slug)
    if store is None:
        raise CommandError(f"Unknown store {slug!r}.")
    return store


def _get_or_create_user(email):
    User = get_user_model()
    email = User.objects.normalize_email(email)
    if not email:
        raise CommandError("--email must not be empty.")
    user = User.objects.filter(email=email).first()
    if user is not None:
        return user, False
    # create_user with no password stores an unusable one and defaults is_staff to False.
    return User.objects.create_user(email=email), True


def _ensure_membership(user, store, role):
    membership = StoreMembership.objects.filter(user=user, store=store).first()
    if membership is None:
        StoreMembership.objects.create(user=user, store=store, role=role, is_active=True)
        return f"granted role {role.name!r} in store {store.slug!r}"
    if membership.role_id == role.pk:
        if not membership.is_active:
            membership.is_active = True
            membership.save(update_fields=["is_active"])
            return f"reactivated role {role.name!r} in store {store.slug!r}"
        return f"kept role {role.name!r} in store {store.slug!r}"
    _refuse_escalation(current=membership.role, requested=role)
    previous = membership.role.name
    membership.role = role
    membership.is_active = True
    membership.save(update_fields=["role", "is_active"])
    return f"changed role from {previous!r} to {role.name!r} in store {store.slug!r}"


def _refuse_escalation(*, current, requested):
    # A role escalation is gaining a permission the current role does not grant.
    added = set(requested.permissions.values_list("code", flat=True)) - set(
        current.permissions.values_list("code", flat=True)
    )
    if added:
        raise CommandError(
            f"Refusing to escalate role {current.name!r} to {requested.name!r}: it would "
            f"add {', '.join(sorted(added))}. Change the membership deliberately."
        )
