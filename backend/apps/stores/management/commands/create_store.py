import logging

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

# The only stores module allowed to import accounts: an entry point, never a model or service.
from apps.accounts.services import grant_membership
from apps.stores.models import ACCENT_COLOR_DEFAULT, Store

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Create a store with an optional accent color. It never updates an existing store."

    def add_arguments(self, parser):
        parser.add_argument("slug")
        parser.add_argument("--name", required=True)
        parser.add_argument("--domain")
        parser.add_argument(
            "--accent-color",
            default=ACCENT_COLOR_DEFAULT,
            help=f"Store accent color as #RRGGBB (default {ACCENT_COLOR_DEFAULT}).",
        )
        parser.add_argument("--owner", help="Email of an existing User to make the owner.")

    @transaction.atomic
    def handle(self, *args, slug, name, domain=None, accent_color=None, owner=None, **options):
        store = Store(slug=slug, name=name, domain=domain, accent_color=accent_color)
        try:
            # Validates the slug and accent color rules, normalizes the domain, and checks
            # that the slug and domain are unused.
            store.full_clean()
        except ValidationError as error:
            raise CommandError(_describe(error)) from error
        owner_user = _find_user(owner) if owner is not None else None
        store.save()
        message = f"Created store {store.slug!r} (name={store.name!r}, domain={store.domain!r})."
        if owner_user is not None:
            grant_membership(user=owner_user, store=store, role_name="owner")
            message += f" Owner: {owner_user.email}."
        logger.info(message)
        self.stdout.write(message)


def _find_user(email):
    User = get_user_model()
    try:
        # The natural key lookup normalizes the email the way the User stores it.
        return User._default_manager.get_by_natural_key(email)
    except User.DoesNotExist as error:
        raise CommandError(
            f"No user with email {email!r}; create_store never creates one."
        ) from error


def _describe(error):
    return " ".join(
        f"{field}: {message}"
        for field, messages in error.message_dict.items()
        for message in messages
    )
