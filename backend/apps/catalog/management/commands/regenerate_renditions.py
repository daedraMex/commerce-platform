"""Create the missing derived WebP renditions of a store's public media."""

from django.core.management.base import BaseCommand

from apps.catalog.management.support import get_active_store
from apps.catalog.media import MediaRuleError, store_renditions
from apps.catalog.models import Media


class Command(BaseCommand):
    help = (
        "Create missing WebP renditions for a store's media. Existing renditions "
        "are never rewritten; bump MEDIA_RENDITION_VERSION to change the encoding."
    )

    def add_arguments(self, parser):
        parser.add_argument("--store", required=True, help="Store slug.")

    def handle(self, *args, **options):
        store = get_active_store(options["store"])
        written = kept = failed = 0

        for media in Media.objects.filter(store=store).order_by("pk"):
            try:
                renditions = store_renditions(media.storage_key)
            except MediaRuleError as error:
                failed += 1
                self.stderr.write(f"{media.storage_key}: {error}")
                continue
            written += sum(1 for rendition in renditions if rendition.written)
            kept += sum(1 for rendition in renditions if not rendition.written)

        self.stdout.write(
            f"Media: {Media.objects.filter(store=store).count()}\n"
            f"Renditions written: {written}\n"
            f"Renditions kept: {kept}\n"
            f"Media failed: {failed}\n"
        )
