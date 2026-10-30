import logging

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.stores.models import Store

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Create a store. It never updates an existing store."

    def add_arguments(self, parser):
        parser.add_argument("slug")
        parser.add_argument("--name", required=True)
        parser.add_argument("--domain")

    @transaction.atomic
    def handle(self, *args, slug, name, domain=None, **options):
        store = Store(slug=slug, name=name, domain=domain)
        try:
            # Validates the slug rule, normalizes the domain and checks both are unused.
            store.full_clean()
        except ValidationError as error:
            raise CommandError(_describe(error)) from error
        store.save()
        message = f"Created store {store.slug!r} (name={store.name!r}, domain={store.domain!r})."
        logger.info(message)
        self.stdout.write(message)


def _describe(error):
    return " ".join(
        f"{field}: {message}"
        for field, messages in error.message_dict.items()
        for message in messages
    )
