"""Load a store's catalog definition: its categories and suppliers."""

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.management.definition import (
    DefinitionError,
    apply_catalog_definition,
    load_catalog_definition,
)
from apps.catalog.management.support import get_active_store


class Command(BaseCommand):
    help = "Create or update a store's categories and suppliers from its catalog definition."

    def add_arguments(self, parser):
        parser.add_argument("--store", required=True, help="Store slug.")
        parser.add_argument(
            "--file", required=True, help="Path to the catalog definition JSON file."
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        store = get_active_store(options["store"])
        try:
            definition = load_catalog_definition(options["file"], store_slug=store.slug)
            report = apply_catalog_definition(store, definition, dry_run=options["dry_run"])
        except DefinitionError as error:
            raise CommandError(str(error)) from error

        self.stdout.write(report.render())
