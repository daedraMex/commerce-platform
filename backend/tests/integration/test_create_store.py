import logging
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command

from apps.accounts.models import StoreMembership
from apps.stores.models import Store

pytestmark = pytest.mark.django_db


def run_create_store(*args, **options):
    stdout = StringIO()
    call_command("create_store", *args, stdout=stdout, **options)
    return stdout.getvalue()


def test_creates_an_active_store_and_names_it_in_the_output():
    output = run_create_store("home", name="Home")

    store = Store.objects.get(slug="home")
    assert store.name == "Home"
    assert store.is_active is True
    assert "home" in output


@pytest.mark.parametrize("slug", ["Home", "-home", "home_1"])
def test_rejects_a_malformed_slug_and_creates_no_store(slug):
    with pytest.raises(CommandError, match="slug"):
        # "--" ends the options, as on the command line, so "-home" reaches the slug.
        run_create_store("--name=Home", "--", slug)

    assert not Store.objects.exists()


def test_rejects_a_duplicate_slug_and_leaves_the_existing_store_unchanged():
    run_create_store("home", name="Home")

    with pytest.raises(CommandError, match="already exists"):
        run_create_store("home", name="Other", domain="other.example.com")

    store = Store.objects.get(slug="home")
    assert store.name == "Home"
    assert store.domain is None
    assert Store.objects.count() == 1


def test_stores_the_domain_lowercase_so_a_differently_cased_domain_collides():
    run_create_store("home", name="Home", domain="Home.Example.com")

    with pytest.raises(CommandError, match="domain"):
        run_create_store("blankets", name="Blankets", domain="home.example.com")

    assert Store.objects.get(slug="home").domain == "home.example.com"
    assert not Store.objects.filter(slug="blankets").exists()


def test_creates_several_stores_without_a_domain_stored_as_null():
    run_create_store("anime", name="Anime")
    run_create_store("home", name="Home")

    assert list(Store.objects.values_list("domain", flat=True)) == [None, None]


def test_logs_the_created_store_through_the_application_logger(caplog):
    with caplog.at_level(logging.INFO, logger="apps.stores"):
        run_create_store("home", name="Home", domain="home.example.com")

    messages = [record.getMessage() for record in caplog.records]
    assert any("home" in message and "home.example.com" in message for message in messages)


def test_the_application_logger_emits_info_records_outside_tests():
    # caplog lowers levels itself, so check the configured level directly.
    logger = logging.getLogger("apps.stores.management.commands.create_store")

    assert logger.isEnabledFor(logging.INFO)


def test_owner_option_gives_the_new_store_an_active_owner_membership():
    user = get_user_model().objects.create_user(email="a@example.com")

    output = run_create_store("home", name="Home", owner="a@example.com")

    membership = StoreMembership.objects.get(store__slug="home")
    assert membership.user == user
    assert membership.role.name == "owner"
    assert membership.is_active is True
    assert "a@example.com" in output


def test_owner_option_matches_the_email_regardless_of_case():
    user = get_user_model().objects.create_user(email="a@example.com")

    run_create_store("home", name="Home", owner="A@Example.com")

    assert StoreMembership.objects.get(store__slug="home").user == user


def test_owner_with_no_user_fails_and_creates_no_store_membership_or_user():
    with pytest.raises(CommandError, match="nobody@example.com"):
        run_create_store("home", name="Home", owner="nobody@example.com")

    assert not Store.objects.exists()
    assert not StoreMembership.objects.exists()
    assert not get_user_model().objects.exists()


def test_without_owner_the_store_has_no_membership():
    run_create_store("home", name="Home")

    assert not StoreMembership.objects.exists()
