"""Seed the stack that the level-2 end-to-end job runs against."""

import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.services import grant_membership
from apps.stores.models import Store

HOME_STORE_SLUG = "home"
HOME_STORE_NAME = "Home"
HOME_STORE_ACCENT_COLOR = "#0ea5e9"


class Command(BaseCommand):
    help = "Create the home store, its demo catalog and the level-2 staff user."

    def handle(self, *args, **options):
        _require_development()
        email = _required_env("E2E_STAFF_EMAIL")
        password = _required_env("E2E_STAFF_PASSWORD")

        with transaction.atomic():
            user = _upsert_staff_user(email, password)
            store = Store.objects.filter(slug=HOME_STORE_SLUG).first()
            if store is None:
                call_command(
                    "create_store",
                    HOME_STORE_SLUG,
                    name=HOME_STORE_NAME,
                    accent_color=HOME_STORE_ACCENT_COLOR,
                    owner=email,
                    stdout=self.stdout,
                )
                store = Store.objects.get(slug=HOME_STORE_SLUG)
            else:
                grant_membership(user=user, store=store, role_name="owner")
            call_command(
                "seed_demo",
                store=HOME_STORE_SLUG,
                operator=email,
                stdout=self.stdout,
            )

        self.stdout.write(f"Level-2 stack seeded: store {HOME_STORE_SLUG!r}, staff {email!r}.")


def _require_development():
    if not settings.DEBUG:
        raise CommandError("e2e_seed only runs when DEBUG is True.")
    if os.environ.get("E2E_SEED_ALLOWED") != "1":
        raise CommandError("e2e_seed requires E2E_SEED_ALLOWED=1.")


def _required_env(name):
    value = os.environ.get(name, "")
    if not value:
        raise CommandError(f"{name} is required.")
    return value


def _upsert_staff_user(email, password):
    User = get_user_model()
    user, _ = User.objects.get_or_create(email=email)
    user.set_password(password)
    user.is_active = True
    user.is_staff = True
    user.is_superuser = True
    user.save()
    return user
