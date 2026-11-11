import importlib
from decimal import Decimal
from io import StringIO

import pytest
from django.apps import apps as global_apps
from django.core.management import call_command
from django.db import connection
from django.db.migrations import RunPython

from apps.catalog.models import (
    Category,
    Design,
    Media,
    Product,
    ProductMedia,
    ProductVariant,
    Supplier,
)
from apps.stores.models import Store

pytestmark = pytest.mark.django_db

MIGRATION_MODULE = "apps.catalog.migrations.0007_productmedia_active_and_unique"
UNIQUE_CONSTRAINT = "catalog_productmedia_unique_product_media"


def migration_module():
    return importlib.import_module(MIGRATION_MODULE)


def make_store(slug="home"):
    return Store.objects.create(slug=slug, name=slug.title())


def make_product(store):
    supplier = Supplier.objects.create(store=store, name="Beka")
    design = Design.objects.create(
        store=store,
        supplier=supplier,
        name="Térmica",
        supplier_design_name="TERMICA",
    )
    category = Category.objects.create(
        store=store,
        name="Frazada",
        slug="frazada",
        sku_code="FRZ",
        shape=Category.Shape.RECTANGLE,
    )
    product = Product.objects.create(store=store, category=category, design=design)
    ProductVariant.objects.create(
        product=product,
        option_values={},
        price=Decimal("499.00"),
        cost=Decimal("200.00"),
    )
    return product


def make_media(store):
    return Media.objects.create(
        store=store,
        storage_key="stores/1/media/photo.jpg",
        content_hash="photo",
        mime_type="image/jpeg",
        width=800,
        height=600,
    )


def test_the_migration_checks_for_duplicates_before_adding_the_constraint():
    module = migration_module()
    operations = module.Migration.operations
    check_index = next(
        index for index, operation in enumerate(operations) if isinstance(operation, RunPython)
    )
    unique_index = next(
        index
        for index, operation in enumerate(operations)
        if getattr(operation, "constraint", None) is not None
        and operation.constraint.name == UNIQUE_CONSTRAINT
    )

    assert check_index < unique_index


def test_the_duplicate_check_is_a_noop_in_reverse():
    operations = migration_module().Migration.operations
    check = next(operation for operation in operations if isinstance(operation, RunPython))

    assert check.reverse_code is RunPython.noop


def test_the_duplicate_check_raises_and_lists_the_duplicate_links():
    home = make_store()
    product = make_product(home)
    media = make_media(home)

    # Drop the constraint before inserting into the table: DDL after a pending
    # trigger on the same table fails, and the surrounding test transaction
    # restores the constraint when it rolls back.
    with connection.cursor() as cursor:
        cursor.execute(f"ALTER TABLE catalog_productmedia DROP CONSTRAINT {UNIQUE_CONSTRAINT}")

    link = ProductMedia.objects.create(product=product, media=media)
    duplicate = ProductMedia.objects.create(
        product=product,
        media=media,
        role=ProductMedia.Role.GALLERY,
        position=2,
    )

    with pytest.raises(RuntimeError) as error:
        migration_module().check_for_duplicate_product_media(global_apps, None)

    message = str(error.value)
    assert "duplicate (product, media) links" in message
    assert f"product {product.pk}" in message
    assert f"media {media.pk}" in message
    assert "never deletes or merges" in message
    assert link.pk is not None
    assert duplicate.pk is not None


def test_the_active_product_media_changes_add_no_extra_migration():
    output = StringIO()

    call_command("makemigrations", "catalog", "--check", "--dry-run", stdout=output)

    assert "No changes detected" in output.getvalue()
