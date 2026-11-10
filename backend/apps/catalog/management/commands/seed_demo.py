"""Fill an existing store with a small, bundled demo catalog."""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.catalog.management.commands.import_catalog import import_catalog_from_csv
from apps.catalog.management.support import get_active_store, resolve_operator
from apps.catalog.models import Category, Supplier

DEMO_CSV_PATH = Path(__file__).with_name("demo_catalog.csv")
DEMO_SUPPLIER_NAME = "Paper Lantern Studio"
DEMO_CATEGORIES = (
    {
        "name": "Sticker Sheets",
        "slug": "demo-sticker-sheets",
        "sku_code": "DMS",
        "option_schema": [
            {
                "code": "size",
                "label": "Size",
                "values": [
                    {"code": "SM", "label": "Small", "width_cm": 10, "height_cm": 10},
                    {"code": "LG", "label": "Large", "width_cm": 15, "height_cm": 15},
                ],
            }
        ],
    },
    {
        "name": "Notebooks",
        "slug": "demo-notebooks",
        "sku_code": "DMN",
        "option_schema": [
            {
                "code": "ruling",
                "label": "Ruling",
                "values": [
                    {"code": "DOT", "label": "Dotted"},
                    {"code": "LIN", "label": "Lined"},
                ],
            }
        ],
    },
)


class Command(BaseCommand):
    help = "Load a bundled demo catalog into an existing store. Development only."

    def add_arguments(self, parser):
        parser.add_argument("--store", required=True, help="Store slug.")
        parser.add_argument("--operator", required=True, help="Email of an active superuser.")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo only runs when DEBUG is True.")

        # The operator is checked before the store or any catalog row is touched.
        operator = resolve_operator(options["operator"])
        store = get_active_store(options["store"])

        with transaction.atomic():
            _ensure_demo_categories_and_supplier(store)
            report = import_catalog_from_csv(store, operator, DEMO_CSV_PATH)
            self.stdout.write(report.render())
            if report.rejected:
                raise CommandError(f"{report.rejected} row(s) rejected.")


def _ensure_demo_categories_and_supplier(store):
    for definition in DEMO_CATEGORIES:
        Category.objects.get_or_create(
            store=store,
            slug=definition["slug"],
            defaults={
                "name": definition["name"],
                "sku_code": definition["sku_code"],
                "shape": Category.Shape.RECTANGLE,
                "option_schema": definition["option_schema"],
                "attribute_schema": [],
                "is_active": True,
            },
        )
    Supplier.objects.get_or_create(store=store, name=DEMO_SUPPLIER_NAME)
