from io import StringIO

import pytest
from django.contrib.auth import authenticate, get_user_model
from django.core.management import CommandError, call_command

from apps.accounts.management.commands import e2e_seed
from apps.accounts.models import StoreMembership
from apps.catalog.models import Product
from apps.stores.models import Store

pytestmark = pytest.mark.django_db

STAFF_EMAIL = "e2e@example.com"
STAFF_PASSWORD = "e2e-secret-pass"


def run_seed():
    stdout = StringIO()
    call_command("e2e_seed", stdout=stdout)
    return stdout.getvalue()


@pytest.fixture
def seeded_env(monkeypatch, settings):
    settings.DEBUG = True
    monkeypatch.setenv("E2E_SEED_ALLOWED", "1")
    monkeypatch.setenv("E2E_STAFF_EMAIL", STAFF_EMAIL)
    monkeypatch.setenv("E2E_STAFF_PASSWORD", STAFF_PASSWORD)


def test_seeds_the_home_store_with_an_accent_color_and_demo_catalog(seeded_env):
    output = run_seed()

    store = Store.objects.get(slug="home")
    assert store.name == "Home"
    assert store.accent_color == e2e_seed.HOME_STORE_ACCENT_COLOR
    assert Product.objects.filter(store=store).exists()
    assert "Level-2 stack seeded" in output


def test_creates_an_owner_staff_user_that_can_sign_in(seeded_env):
    run_seed()

    user = get_user_model().objects.get(email=STAFF_EMAIL)
    membership = StoreMembership.objects.get(user=user, store__slug="home")
    assert user.is_active is True
    assert user.check_password(STAFF_PASSWORD)
    assert authenticate(email=STAFF_EMAIL, password=STAFF_PASSWORD) == user
    assert membership.role.name == "owner"
    assert membership.is_active is True


def test_is_idempotent(seeded_env):
    run_seed()
    first_products = Product.objects.filter(store__slug="home").count()
    first_users = get_user_model().objects.count()

    run_seed()

    assert Store.objects.filter(slug="home").count() == 1
    assert get_user_model().objects.count() == first_users
    assert Product.objects.filter(store__slug="home").count() == first_products
    assert StoreMembership.objects.filter(store__slug="home").count() == 1


@pytest.mark.parametrize(
    ("debug", "allowed"),
    [
        (False, "1"),
        (True, None),
        (True, "0"),
    ],
)
def test_refuses_without_the_development_flags(monkeypatch, settings, debug, allowed):
    settings.DEBUG = debug
    monkeypatch.setenv("E2E_STAFF_EMAIL", STAFF_EMAIL)
    monkeypatch.setenv("E2E_STAFF_PASSWORD", STAFF_PASSWORD)
    monkeypatch.delenv("E2E_SEED_ALLOWED", raising=False)
    if allowed is not None:
        monkeypatch.setenv("E2E_SEED_ALLOWED", allowed)

    with pytest.raises(CommandError, match="DEBUG|E2E_SEED_ALLOWED"):
        run_seed()

    assert not Store.objects.exists()
    assert not get_user_model().objects.exists()
    assert not Product.objects.exists()


@pytest.mark.parametrize("missing", ["E2E_STAFF_EMAIL", "E2E_STAFF_PASSWORD"])
def test_refuses_without_the_staff_credentials(seeded_env, monkeypatch, missing):
    monkeypatch.delenv(missing)

    with pytest.raises(CommandError, match=missing):
        run_seed()

    assert not Store.objects.exists()
    assert not get_user_model().objects.exists()
