import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.stores.models import ACCENT_COLOR_DEFAULT, Store

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("domain", ["Home.Example.com", ""])
def test_the_database_rejects_a_domain_that_skips_normalization(domain):
    store = Store.objects.create(slug="home", name="Home")

    with pytest.raises(IntegrityError), transaction.atomic():
        Store.objects.filter(pk=store.pk).update(domain=domain)


def test_a_valid_hex_accent_color_is_saved_lowercase():
    store = Store(slug="home", name="Home", accent_color="#4F46E5")

    store.full_clean()
    store.save()

    store.refresh_from_db()
    assert store.accent_color == "#4f46e5"


def test_a_new_store_gets_the_platform_accent_color_by_default():
    store = Store.objects.create(slug="home", name="Home")

    assert store.accent_color == ACCENT_COLOR_DEFAULT


@pytest.mark.parametrize("accent_color", ["red", "#fff", "#12345g", "4f46e5"])
def test_full_clean_rejects_an_invalid_accent_color(accent_color):
    store = Store(slug="home", name="Home", accent_color=accent_color)

    with pytest.raises(ValidationError) as error:
        store.full_clean()

    codes = [message.code for message in error.value.error_dict["accent_color"]]
    assert "invalid_accent_color" in codes


def test_full_clean_rejects_a_blank_accent_color():
    store = Store(slug="home", name="Home", accent_color="")

    with pytest.raises(ValidationError) as error:
        store.full_clean()

    assert error.value.error_dict["accent_color"][0].code == "blank"


@pytest.mark.parametrize("accent_color", ["red", "#4F46E5", ""])
def test_the_database_rejects_an_accent_color_that_skips_normalization(accent_color):
    store = Store.objects.create(slug="home", name="Home")

    with pytest.raises(IntegrityError), transaction.atomic():
        Store.objects.filter(pk=store.pk).update(accent_color=accent_color)


def test_a_whatsapp_number_is_saved_as_digits_only():
    store = Store.objects.create(
        slug="home",
        name="Home",
        whatsapp_number="+52 1 55 9876 5432",
    )

    store.refresh_from_db()
    assert store.whatsapp_number == "5215598765432"


@pytest.mark.parametrize("whatsapp_number", ["123", "0123456789", "1234567890123456"])
def test_full_clean_rejects_an_invalid_whatsapp_number(whatsapp_number):
    store = Store(slug="home", name="Home", whatsapp_number=whatsapp_number)

    with pytest.raises(ValidationError) as error:
        store.full_clean()

    codes = [message.code for message in error.value.error_dict["whatsapp_number"]]
    assert "invalid_whatsapp_number" in codes


@pytest.mark.parametrize("whatsapp_number", ["+52 1 55 9876 5432", "0123456789", "123"])
def test_the_database_rejects_a_whatsapp_number_that_skips_normalization(whatsapp_number):
    store = Store.objects.create(slug="home", name="Home")

    with pytest.raises(IntegrityError), transaction.atomic():
        Store.objects.filter(pk=store.pk).update(whatsapp_number=whatsapp_number)
