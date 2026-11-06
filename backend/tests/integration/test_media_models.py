from decimal import Decimal
from io import BytesIO

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.urls import reverse
from PIL import Image

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


def make_store(slug, name=None):
    return Store.objects.create(slug=slug, name=name or slug.title())


def make_product(store, *, name="Frazada Jack Todos", slug="frazada-jack-todos"):
    supplier = Supplier.objects.filter(store=store).first() or Supplier.objects.create(
        store=store, name="Beka"
    )
    design = Design.objects.create(
        store=store,
        supplier=supplier,
        name="Jack Todos",
        supplier_design_name=f"JACK TODOS {Design.objects.count()}",
    )
    category = Category.objects.filter(store=store).first() or Category.objects.create(
        store=store,
        name="Frazada",
        slug="frazada",
        sku_code="FRZ",
        shape=Category.Shape.RECTANGLE,
    )
    return Product.objects.create(
        store=store, category=category, design=design, name=name, slug=slug
    )


def make_variant(product, *, sku=None):
    return ProductVariant.objects.create(
        product=product,
        option_values={},
        sku=sku if sku is not None else "",
        price=Decimal("199.00"),
        cost=Decimal("80.00"),
    )


def make_media(store, *, key="stores/1/media/abc.jpg", content_hash="abc"):
    return Media.objects.create(
        store=store,
        storage_key=key,
        content_hash=content_hash,
        mime_type="image/jpeg",
        width=10,
        height=20,
    )


def image_bytes(image_format="JPEG", size=(12, 8), color=(20, 30, 40)):
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format=image_format)
    return buffer.getvalue()


@pytest.fixture
def media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.MEDIA_BASE_URL = "https://media.example.com"
    return settings.MEDIA_ROOT


def upload(admin_client_by_email, store, *, name, content, content_type):
    return admin_client_by_email.post(
        "/admin/catalog/media/add/",
        {
            "store": str(store.pk),
            "file": SimpleUploadedFile(name, content, content_type=content_type),
            "alt_text": "A blanket",
        },
    )


@pytest.mark.parametrize(
    ("image_format", "content_type", "mime_type", "extension"),
    [
        ("JPEG", "image/jpeg", "image/jpeg", "jpg"),
        ("PNG", "image/png", "image/png", "png"),
        ("WEBP", "image/webp", "image/webp", "webp"),
    ],
)
def test_uploading_an_image_reads_its_dimensions_and_mime_type(
    admin_client_by_email, media_root, image_format, content_type, mime_type, extension
):
    home = make_store("home")

    response = upload(
        admin_client_by_email,
        home,
        name=f"original-{image_format}.{extension}",
        content=image_bytes(image_format, (12, 8)),
        content_type=content_type,
    )

    assert response.status_code == 302
    media = Media.objects.get()
    assert media.store == home
    assert media.width == 12
    assert media.height == 8
    assert media.mime_type == mime_type
    assert media.alt_text == "A blanket"
    assert media.storage_key.startswith(f"stores/{home.pk}/media/")
    assert media.storage_key.endswith(f".{extension}")
    assert "original" not in media.storage_key
    assert (media_root / media.storage_key).is_file()


def test_the_storage_key_is_content_addressed(admin_client_by_email, media_root):
    home = make_store("home")

    upload(
        admin_client_by_email,
        home,
        name="photo.jpg",
        content=image_bytes("JPEG"),
        content_type="image/jpeg",
    )

    media = Media.objects.get()
    assert media.storage_key == f"stores/{home.pk}/media/{media.content_hash}.jpg"


def test_uploading_the_same_file_twice_reuses_one_media(admin_client_by_email, media_root):
    home = make_store("home")
    content = image_bytes("PNG")

    upload(admin_client_by_email, home, name="one.png", content=content, content_type="image/png")
    response = upload(
        admin_client_by_email, home, name="two.png", content=content, content_type="image/png"
    )

    assert response.status_code == 302
    assert Media.objects.count() == 1
    assert len(list(media_root.rglob("*.png"))) == 1


def test_the_same_file_in_two_stores_is_two_media(admin_client_by_email, media_root):
    home = make_store("home")
    anime = make_store("anime")
    content = image_bytes("JPEG")

    upload(
        admin_client_by_email, home, name="photo.jpg", content=content, content_type="image/jpeg"
    )
    upload(
        admin_client_by_email,
        anime,
        name="photo.jpg",
        content=content,
        content_type="image/jpeg",
    )

    assert Media.objects.count() == 2
    assert {media.store_id for media in Media.objects.all()} == {home.pk, anime.pk}


def test_a_gif_is_rejected(admin_client_by_email, media_root):
    home = make_store("home")

    response = upload(
        admin_client_by_email,
        home,
        name="photo.gif",
        content=image_bytes("GIF"),
        content_type="image/gif",
    )

    assert response.status_code == 200
    assert b"JPEG, PNG or WebP" in response.content
    assert not Media.objects.exists()


def test_a_non_image_file_is_rejected(admin_client_by_email, media_root):
    home = make_store("home")

    response = upload(
        admin_client_by_email,
        home,
        name="notes.txt",
        content=b"not an image",
        content_type="text/plain",
    )

    assert response.status_code == 200
    assert b"JPEG, PNG or WebP" in response.content
    assert not Media.objects.exists()


def test_a_file_over_ten_megabytes_is_rejected(admin_client_by_email, media_root):
    home = make_store("home")

    response = upload(
        admin_client_by_email,
        home,
        name="huge.jpg",
        content=b"x" * (10 * 1024 * 1024 + 1),
        content_type="image/jpeg",
    )

    assert response.status_code == 200
    assert b"10 MB" in response.content
    assert not Media.objects.exists()


def test_a_content_hash_is_unique_per_store():
    home = make_store("home")
    anime = make_store("anime")
    make_media(home, key="stores/1/media/abc.jpg", content_hash="abc")

    with pytest.raises(IntegrityError), transaction.atomic():
        make_media(home, key="stores/1/media/other.jpg", content_hash="abc")

    assert make_media(anime, key="stores/2/media/abc.jpg", content_hash="abc").pk is not None


def test_media_builds_its_public_url_from_the_storage_key(media_root):
    home = make_store("home")
    media = make_media(home, key="stores/1/media/abc.jpg")

    assert media.public_url == "https://media.example.com/stores/1/media/abc.jpg"


def test_a_product_has_at_most_one_main_image():
    home = make_store("home")
    product = make_product(home)
    first = make_media(home, key="stores/1/media/first.jpg", content_hash="first")
    second = make_media(home, key="stores/1/media/second.jpg", content_hash="second")
    ProductMedia.objects.create(product=product, media=first, role=ProductMedia.Role.MAIN)

    with pytest.raises(IntegrityError), transaction.atomic():
        ProductMedia.objects.create(product=product, media=second, role=ProductMedia.Role.MAIN)


def test_a_product_can_link_media_of_its_own_store():
    home = make_store("home")
    product = make_product(home)
    media = make_media(home)

    link = ProductMedia.objects.create(product=product, media=media, role=ProductMedia.Role.MAIN)

    assert link.position == 1


def test_a_product_cannot_link_media_of_another_store():
    home = make_store("home")
    anime = make_store("anime")
    product = make_product(home)
    media = make_media(anime, key="stores/2/media/abc.jpg")

    with pytest.raises(ValidationError):
        ProductMedia.objects.create(product=product, media=media)

    assert not ProductMedia.objects.exists()


def test_a_product_cannot_link_a_variant_of_another_product():
    home = make_store("home")
    product = make_product(home)
    other = make_product(home, name="Other", slug="other")
    variant = make_variant(other)
    media = make_media(home)

    with pytest.raises(ValidationError):
        ProductMedia.objects.create(product=product, variant=variant, media=media)

    assert not ProductMedia.objects.exists()


def test_deleting_a_product_media_leaves_the_media():
    home = make_store("home")
    product = make_product(home)
    media = make_media(home)
    link = ProductMedia.objects.create(product=product, media=media)

    link.delete()

    assert not ProductMedia.objects.exists()
    assert Media.objects.filter(pk=media.pk).exists()


@pytest.mark.parametrize("url_name", ["admin:catalog_media_changelist", "admin:catalog_media_add"])
def test_media_admin_is_reachable_by_superusers_only(client, url_name):
    staff = get_user_model().objects.create_user(email="staff@example.com", is_staff=True)
    staff.user_permissions.set(Permission.objects.all())
    client.force_login(staff)

    response = client.get(reverse(url_name))

    assert response.status_code == 302
    assert response.url.startswith(reverse("admin:login"))
