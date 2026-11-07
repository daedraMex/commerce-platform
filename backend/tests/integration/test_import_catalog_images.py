import csv
from io import BytesIO, StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
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

FIELDNAMES = [
    "category",
    "supplier",
    "supplier_design_name",
    "design_name",
    "option_values",
    "price",
    "compare_at_price",
    "cost",
    "weight_grams",
    "package_length_cm",
    "package_width_cm",
    "package_height_cm",
    "collections",
    "attributes",
    "description",
    "main_image",
    "gallery_images",
]


@pytest.fixture
def media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    return settings.MEDIA_ROOT


def make_store(slug="home"):
    return Store.objects.create(slug=slug, name=slug.title())


def make_superuser(email="operator@example.com"):
    return get_user_model().objects.create_user(
        email=email,
        password="s3cret-pass",
        is_active=True,
        is_superuser=True,
        is_staff=True,
    )


def make_category(store):
    return Category.objects.create(
        store=store,
        name="Frazada",
        slug="frazada",
        sku_code="FRZ",
        shape=Category.Shape.RECTANGLE,
        option_schema=[
            {
                "code": "size",
                "label": "Size",
                "values": [
                    {"code": "IND", "label": "Individual", "width_cm": 80, "height_cm": 80},
                    {"code": "MAT", "label": "Matrimonial", "width_cm": 160, "height_cm": 210},
                ],
            }
        ],
        attribute_schema=[
            {
                "code": "material",
                "label": "Material",
                "type": "text",
                "choices": [],
                "required": True,
            }
        ],
    )


def make_supplier(store, name="Beka"):
    return Supplier.objects.create(store=store, name=name)


def row(**overrides):
    values = {
        "category": "frazada",
        "supplier": "Beka",
        "supplier_design_name": "JACK TODOS",
        "design_name": "Jack Todos",
        "option_values": "size=IND",
        "price": "199.00",
        "compare_at_price": "",
        "cost": "80.00",
        "weight_grams": "",
        "package_length_cm": "",
        "package_width_cm": "",
        "package_height_cm": "",
        "collections": "",
        "attributes": "material=Flannel premier",
        "description": "",
        "main_image": "",
        "gallery_images": "",
    }
    values.update(overrides)
    return values


def write_csv(tmp_path, rows, filename="catalog.csv"):
    path = tmp_path / filename
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_image(directory, name, *, size=(10, 20), image_format="JPEG", color=(20, 30, 40)):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format=image_format)
    path.write_bytes(buffer.getvalue())
    return path


def run_import(*args, **options):
    stdout = StringIO()
    call_command("import_catalog", *args, stdout=stdout, **options)
    return stdout.getvalue()


def run_import_expecting_error(*args, **options):
    stdout = StringIO()
    with pytest.raises(CommandError):
        call_command("import_catalog", *args, stdout=stdout, **options)
    return stdout.getvalue()


def ordered_links(product):
    return list(product.product_media.select_related("media").order_by("position", "pk"))


def test_rows_naming_files_create_media_and_product_media_with_roles_and_positions(
    tmp_path, media_root
):
    home = make_store()
    make_superuser()
    make_category(home)
    make_supplier(home)
    images = tmp_path / "images"
    write_image(images, "main.jpg", size=(10, 20))
    write_image(images, "gallery-1.jpg", size=(30, 40))
    write_image(images, "gallery-2.jpg", size=(50, 60))
    path = write_csv(
        tmp_path,
        [row(main_image="main.jpg", gallery_images="gallery-1.jpg;gallery-2.jpg")],
    )

    output = run_import(
        store="home",
        csv=str(path),
        operator="operator@example.com",
        images=str(images),
    )

    product = Product.objects.get()
    links = ordered_links(product)
    assert [
        (link.role, link.position, (link.media.width, link.media.height)) for link in links
    ] == [
        ("main", 1, (10, 20)),
        ("gallery", 2, (30, 40)),
        ("gallery", 3, (50, 60)),
    ]
    assert Media.objects.filter(store=home).count() == 3
    for media in Media.objects.all():
        assert media.storage_key.startswith(f"stores/{home.pk}/media/")
        assert (media_root / media.storage_key).is_file()
    assert "Rows created: 1" in output
    assert "Rows rejected: 0" in output


def test_a_file_named_twice_is_stored_once_and_reimporting_adds_nothing(tmp_path, media_root):
    home = make_store()
    make_superuser()
    make_category(home)
    make_supplier(home)
    images = tmp_path / "images"
    write_image(images, "main.jpg", size=(10, 20))
    write_image(images, "gallery.jpg", size=(30, 40))
    path = write_csv(
        tmp_path,
        [row(main_image="main.jpg", gallery_images="gallery.jpg;gallery.jpg")],
    )

    run_import(store="home", csv=str(path), operator="operator@example.com", images=str(images))
    first_output = run_import(
        store="home", csv=str(path), operator="operator@example.com", images=str(images)
    )

    assert Media.objects.count() == 2
    assert ProductMedia.objects.count() == 2
    assert "Rows created: 0" in first_output
    assert "Rows updated: 0" in first_output
    assert "Rows unchanged: 1" in first_output
    stored_files = [path for path in media_root.rglob("*") if path.is_file()]
    assert len(stored_files) == 2


def test_a_missing_file_rejects_the_row_and_writes_nothing(tmp_path, media_root):
    home = make_store()
    make_superuser()
    make_category(home)
    make_supplier(home)
    images = tmp_path / "images"
    write_image(images, "main.jpg")
    path = write_csv(
        tmp_path,
        [
            row(supplier_design_name="GOOD", design_name="Good", main_image="main.jpg"),
            row(supplier_design_name="BAD", design_name="Bad", main_image="absent.jpg"),
        ],
    )

    output = run_import_expecting_error(
        store="home",
        csv=str(path),
        operator="operator@example.com",
        images=str(images),
    )

    assert "Rows rejected: 1" in output
    assert "Row 3:" in output
    assert "absent.jpg" in output
    assert not Media.objects.exists()
    assert not ProductMedia.objects.exists()
    assert not Design.objects.exists()
    assert not Product.objects.exists()


def test_an_unsupported_file_rejects_the_row_and_writes_nothing(tmp_path, media_root):
    home = make_store()
    make_superuser()
    make_category(home)
    make_supplier(home)
    images = tmp_path / "images"
    write_image(images, "animated.gif", image_format="GIF")
    path = write_csv(tmp_path, [row(main_image="animated.gif")])

    output = run_import_expecting_error(
        store="home", csv=str(path), operator="operator@example.com", images=str(images)
    )

    assert "Row 2:" in output
    assert "JPEG, PNG or WebP" in output
    assert not Media.objects.exists()
    assert not Product.objects.exists()


def test_a_file_over_ten_megabytes_rejects_the_row_and_writes_nothing(tmp_path, media_root):
    home = make_store()
    make_superuser()
    make_category(home)
    make_supplier(home)
    images = tmp_path / "images"
    images.mkdir()
    (images / "huge.jpg").write_bytes(b"x" * (10 * 1024 * 1024 + 1))
    path = write_csv(tmp_path, [row(main_image="huge.jpg")])

    output = run_import_expecting_error(
        store="home", csv=str(path), operator="operator@example.com", images=str(images)
    )

    assert "Row 2:" in output
    assert "10 MB" in output
    assert not Media.objects.exists()
    assert not Product.objects.exists()


def test_two_main_images_for_one_product_in_the_file_reject_the_row(tmp_path, media_root):
    home = make_store()
    make_superuser()
    make_category(home)
    make_supplier(home)
    images = tmp_path / "images"
    write_image(images, "first.jpg", size=(10, 20))
    write_image(images, "second.jpg", size=(30, 40))
    path = write_csv(
        tmp_path,
        [
            row(option_values="size=IND", main_image="first.jpg"),
            row(option_values="size=MAT", main_image="second.jpg"),
        ],
    )

    output = run_import_expecting_error(
        store="home", csv=str(path), operator="operator@example.com", images=str(images)
    )

    assert "Rows rejected: 1" in output
    assert "Row 3:" in output
    assert "main image" in output
    assert not Media.objects.exists()
    assert not ProductMedia.objects.exists()
    assert not Product.objects.exists()


def test_dry_run_with_images_validates_without_storing_anything(tmp_path, media_root):
    home = make_store()
    make_superuser()
    make_category(home)
    make_supplier(home)
    images = tmp_path / "images"
    write_image(images, "main.jpg")
    write_image(images, "gallery.jpg")
    path = write_csv(tmp_path, [row(main_image="main.jpg", gallery_images="gallery.jpg")])

    output = run_import(
        store="home",
        csv=str(path),
        operator="operator@example.com",
        images=str(images),
        dry_run=True,
    )

    assert "Rows created: 1" in output
    assert "Dry run" in output
    assert not Media.objects.exists()
    assert not ProductMedia.objects.exists()
    assert not Design.objects.exists()
    assert not Product.objects.exists()
    assert not media_root.exists() or not any(media_root.rglob("*"))


def test_dry_run_with_a_missing_file_rejects_the_row(tmp_path, media_root):
    home = make_store()
    make_superuser()
    make_category(home)
    make_supplier(home)
    images = tmp_path / "images"
    images.mkdir()
    path = write_csv(tmp_path, [row(main_image="absent.jpg")])

    output = run_import_expecting_error(
        store="home",
        csv=str(path),
        operator="operator@example.com",
        images=str(images),
        dry_run=True,
    )

    assert "Rows rejected: 1" in output
    assert "absent.jpg" in output
    assert not Media.objects.exists()


def test_without_images_the_image_columns_are_ignored(tmp_path, media_root):
    home = make_store()
    make_superuser()
    make_category(home)
    make_supplier(home)
    path = write_csv(
        tmp_path,
        [row(main_image="missing.jpg", gallery_images="also-missing.jpg")],
    )

    output = run_import(store="home", csv=str(path), operator="operator@example.com")

    assert "Rows created: 1" in output
    assert "Rows rejected: 0" in output
    assert not Media.objects.exists()
    assert not ProductMedia.objects.exists()
    assert ProductVariant.objects.get().sku == "FRZ-00001-IND"


def test_an_images_folder_that_does_not_exist_rejects_the_command(tmp_path, media_root):
    home = make_store()
    make_superuser()
    make_category(home)
    make_supplier(home)
    path = write_csv(tmp_path, [row(main_image="main.jpg")])

    with pytest.raises(CommandError, match="images folder"):
        call_command(
            "import_catalog",
            store="home",
            csv=str(path),
            operator="operator@example.com",
            images=str(tmp_path / "missing"),
            stdout=StringIO(),
        )

    assert not Design.objects.exists()


def test_importing_images_in_one_store_never_touches_another(tmp_path, media_root):
    home = make_store("home")
    anime = make_store("anime")
    make_superuser()
    for store in (home, anime):
        make_category(store)
        make_supplier(store)
    images = tmp_path / "images"
    write_image(images, "main.jpg")
    home_csv = write_csv(tmp_path, [row(main_image="main.jpg")], filename="home.csv")
    anime_csv = write_csv(tmp_path, [row(main_image="main.jpg")], filename="anime.csv")

    run_import(store="home", csv=str(home_csv), operator="operator@example.com", images=str(images))
    run_import(
        store="anime", csv=str(anime_csv), operator="operator@example.com", images=str(images)
    )

    assert Media.objects.filter(store=home).count() == 1
    assert Media.objects.filter(store=anime).count() == 1
    assert Media.objects.get(store=home).storage_key.startswith(f"stores/{home.pk}/media/")
    assert Media.objects.get(store=anime).storage_key.startswith(f"stores/{anime.pk}/media/")
    for product in Product.objects.all():
        for link in product.product_media.all():
            assert link.media.store_id == product.store_id


def test_reimport_applies_a_changed_gallery_order(tmp_path, media_root):
    home = make_store()
    make_superuser()
    make_category(home)
    make_supplier(home)
    images = tmp_path / "images"
    write_image(images, "first.jpg", size=(10, 20))
    write_image(images, "second.jpg", size=(30, 40))
    first = write_csv(tmp_path, [row(gallery_images="first.jpg;second.jpg")], filename="first.csv")
    run_import(store="home", csv=str(first), operator="operator@example.com", images=str(images))

    second = write_csv(
        tmp_path, [row(gallery_images="second.jpg;first.jpg")], filename="second.csv"
    )
    output = run_import(
        store="home", csv=str(second), operator="operator@example.com", images=str(images)
    )

    links = ordered_links(Product.objects.get())
    assert [
        (link.role, link.position, (link.media.width, link.media.height)) for link in links
    ] == [
        ("gallery", 1, (30, 40)),
        ("gallery", 2, (10, 20)),
    ]
    assert "Rows updated: 1" in output


def test_reimport_moves_an_existing_gallery_file_to_main(tmp_path, media_root):
    home = make_store()
    make_superuser()
    make_category(home)
    make_supplier(home)
    images = tmp_path / "images"
    write_image(images, "photo.jpg", size=(10, 20))
    first = write_csv(tmp_path, [row(gallery_images="photo.jpg")], filename="first.csv")
    run_import(store="home", csv=str(first), operator="operator@example.com", images=str(images))

    second = write_csv(tmp_path, [row(main_image="photo.jpg")], filename="second.csv")
    output = run_import(
        store="home", csv=str(second), operator="operator@example.com", images=str(images)
    )

    links = ordered_links(Product.objects.get())
    assert [(link.role, link.position) for link in links] == [("main", 1)]
    assert "Rows updated: 1" in output


def test_a_large_import_with_images_runs_a_bounded_number_of_queries(
    tmp_path, media_root, django_assert_max_num_queries
):
    home = make_store()
    make_superuser()
    make_category(home)
    make_supplier(home)
    images = tmp_path / "images"
    write_image(images, "main.jpg", size=(10, 20))
    write_image(images, "gallery.jpg", size=(30, 40))
    rows = [
        row(
            supplier_design_name=f"DESIGN {number}",
            design_name=f"Design {number}",
            option_values="size=IND",
            main_image="main.jpg",
            gallery_images="gallery.jpg",
        )
        for number in range(1, 501)
    ]
    path = write_csv(tmp_path, rows)

    with django_assert_max_num_queries(40):
        output = run_import(
            store="home",
            csv=str(path),
            operator="operator@example.com",
            images=str(images),
        )

    assert "Rows created: 500" in output
    assert Media.objects.count() == 2
    assert ProductMedia.objects.count() == 1000
