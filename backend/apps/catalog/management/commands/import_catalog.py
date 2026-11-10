"""Load a store's catalog from a one-row-per-variant CSV."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.management.support import (
    get_active_store,
    import_catalog_from_csv,
    resolve_operator,
)


class Command(BaseCommand):
    help = "Import a store catalog from a one-row-per-variant CSV."

    def add_arguments(self, parser):
        parser.add_argument("--store", required=True, help="Store slug.")
        parser.add_argument("--csv", required=True, help="Path to the CSV file.")
        parser.add_argument("--operator", required=True, help="Email of an active superuser.")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--images", help="Folder holding the image files named in the CSV.")

    def handle(self, *args, **options):
        # The operator is checked before the file, the store or any catalog row is read.
        operator = resolve_operator(options["operator"])
        store = get_active_store(options["store"])
        images_dir = _images_directory(options.get("images"))

        report = import_catalog_from_csv(
            store,
            operator,
            options["csv"],
            dry_run=options["dry_run"],
            images_dir=images_dir,
        )

        self.stdout.write(report.render())
        if report.rejected:
            raise CommandError(f"{report.rejected} row(s) rejected.")


def _images_directory(value):
    if not value:
        return None
    images_dir = Path(value).expanduser()
    if not images_dir.is_dir():
        raise CommandError(
            f"The images folder {str(images_dir)!r} does not exist or is not a directory."
        )
    return images_dir
