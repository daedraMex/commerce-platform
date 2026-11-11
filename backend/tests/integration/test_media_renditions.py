from decimal import Decimal
from io import StringIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from PIL import Image

from apps.catalog.media import rendition_key, store_media
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
from tests.images import image_bytes

pytestmark = pytest.mark.django_db

PRODUCTS_URL = "/api/v1/catalog/products/"


@pytest.fixture
def media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.MEDIA_BASE_URL = "https://media.example.com"
    return settings.MEDIA_ROOT


def make_store(slug="home"):
    return Store.objects.create(slug=slug, name=slug.title())


def upload_media(store, *, size=(2000, 1000)):
    upload = SimpleUploadedFile(
        "photo.jpg",
        image_bytes("JPEG", size=size),
        content_type="image/jpeg",
    )
    return store_media(store, upload)


def rendition_path(media_root, storage_key, width, version=1):
    return media_root / rendition_key(storage_key, width=width, version=version)


def open_image(path):
    with Image.open(path) as image:
        image.load()
        return image.format, image.size


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
    product = Product.objects.create(
        store=store,
        category=category,
        design=design,
        name="Frazada Térmica",
        slug="frazada-termica",
    )
    ProductVariant.objects.create(
        product=product,
        option_values={},
        price=Decimal("499.00"),
        cost=Decimal("200.00"),
    )
    return product


def test_storing_media_generates_320_and_800_webp_renditions(media_root):
    home = make_store()

    media = upload_media(home)

    thumbnail = rendition_path(media_root, media.storage_key, 320)
    medium = rendition_path(media_root, media.storage_key, 800)
    assert open_image(thumbnail) == ("WEBP", (320, 160))
    assert open_image(medium) == ("WEBP", (800, 400))


def test_a_small_original_is_never_upscaled(media_root):
    home = make_store()

    media = upload_media(home, size=(200, 100))

    thumbnail = rendition_path(media_root, media.storage_key, 320)
    assert open_image(thumbnail) == ("WEBP", (200, 100))


def test_the_regeneration_command_recreates_missing_renditions(media_root):
    home = make_store()
    media = upload_media(home)
    thumbnail = rendition_path(media_root, media.storage_key, 320)
    medium = rendition_path(media_root, media.storage_key, 800)
    thumbnail.unlink()
    medium.unlink()

    output = StringIO()
    call_command("regenerate_renditions", store="home", stdout=output)

    assert thumbnail.is_file()
    assert medium.is_file()
    assert "Renditions written: 2" in output.getvalue()


def test_regenerating_keeps_existing_renditions_by_default(media_root):
    home = make_store()
    media = upload_media(home)
    thumbnail = rendition_path(media_root, media.storage_key, 320)
    original_bytes = thumbnail.read_bytes()

    output = StringIO()
    call_command("regenerate_renditions", store="home", stdout=output)

    assert thumbnail.read_bytes() == original_bytes
    assert "Renditions written: 0" in output.getvalue()
    assert "Renditions kept: 2" in output.getvalue()


def test_a_version_bump_writes_new_keys_and_leaves_the_old_objects(media_root):
    home = make_store()
    media = upload_media(home)
    old_thumbnail = rendition_path(media_root, media.storage_key, 320, version=1)
    old_bytes = old_thumbnail.read_bytes()

    with override_settings(MEDIA_RENDITION_VERSION=2):
        call_command("regenerate_renditions", store="home", stdout=StringIO())

    new_thumbnail = rendition_path(media_root, media.storage_key, 320, version=2)
    assert new_thumbnail.is_file()
    assert new_thumbnail != old_thumbnail
    assert old_thumbnail.read_bytes() == old_bytes


def test_a_size_bump_writes_new_keys_and_leaves_the_old_objects(media_root):
    home = make_store()
    media = upload_media(home)
    old_thumbnail = rendition_path(media_root, media.storage_key, 320)
    old_bytes = old_thumbnail.read_bytes()

    with override_settings(MEDIA_RENDITION_SIZES={"thumbnail": 240, "medium": 800}):
        call_command("regenerate_renditions", store="home", stdout=StringIO())

    new_thumbnail = rendition_path(media_root, media.storage_key, 240)
    assert open_image(new_thumbnail) == ("WEBP", (240, 120))
    assert old_thumbnail.read_bytes() == old_bytes


def test_force_rewrites_a_rendition_under_the_same_key(media_root):
    home = make_store()
    media = upload_media(home)
    thumbnail = rendition_path(media_root, media.storage_key, 320)
    thumbnail.write_bytes(b"not a webp")

    call_command("regenerate_renditions", store="home", force=True, stdout=StringIO())

    assert open_image(thumbnail) == ("WEBP", (320, 160))


def test_the_api_exposes_original_thumbnail_and_medium_urls(client, media_root):
    home = make_store()
    product = make_product(home)
    media = upload_media(home)
    ProductMedia.objects.create(product=product, media=media, role=ProductMedia.Role.MAIN)

    response = client.get(
        f"{PRODUCTS_URL}{product.slug}/",
        HTTP_X_STORE="home",
    )

    assert response.status_code == 200
    image = response.json()["images"][0]
    assert image["url"] == media.public_url
    assert image["thumbnail_url"] == (
        "https://media.example.com/" + rendition_key(media.storage_key, width=320, version=1)
    )
    assert image["medium_url"] == (
        "https://media.example.com/" + rendition_key(media.storage_key, width=800, version=1)
    )


def test_stored_renditions_understand_the_settings():
    from apps.catalog import media as module

    assert module.rendition_sizes()["thumbnail"] == 320
    assert module.rendition_sizes()["medium"] == 800
    assert module.rendition_version() == 1


def test_media_gained_no_rendition_columns():
    field_names = {field.name for field in Media._meta.get_fields()}

    assert not any("rendition" in name for name in field_names)


def test_media_renditions_add_no_migration():
    output = StringIO()

    call_command("makemigrations", "catalog", "--check", "--dry-run", stdout=output)

    assert "No changes detected" in output.getvalue()
