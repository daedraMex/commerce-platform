from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command

from apps.accounts.models import StoreMembership
from apps.stores.models import Store

pytestmark = pytest.mark.django_db


def run_create_staff_user(*, email, store, role):
    stdout = StringIO()
    call_command(
        "create_staff_user",
        email=email,
        store=store,
        role=role,
        stdout=stdout,
    )
    return stdout.getvalue()


@pytest.fixture
def store_factory():
    def create(slug="home"):
        return Store.objects.create(slug=slug, name=slug.title())

    return create


def test_creates_a_user_and_membership_with_an_unusable_password(store_factory):
    store = store_factory()

    output = run_create_staff_user(email="staff@example.com", store="home", role="warehouse")

    user = get_user_model().objects.get(email="staff@example.com")
    assert user.has_usable_password() is False
    assert user.is_staff is False
    assert user.is_superuser is False
    membership = StoreMembership.objects.get(user=user, store=store)
    assert membership.is_active is True
    assert membership.role.name == "warehouse"
    assert "staff@example.com" in output


def test_a_second_run_is_idempotent(store_factory):
    store_factory()
    run_create_staff_user(email="staff@example.com", store="home", role="warehouse")

    user = get_user_model().objects.get(email="staff@example.com")
    membership = StoreMembership.objects.get(user=user)
    membership_id = membership.pk
    password_hash = user.password

    run_create_staff_user(email="staff@example.com", store="home", role="warehouse")

    user.refresh_from_db()
    membership.refresh_from_db()
    assert get_user_model().objects.count() == 1
    assert StoreMembership.objects.count() == 1
    assert user.password == password_hash
    assert membership.pk == membership_id
    assert membership.role.name == "warehouse"


def test_never_changes_an_existing_password(store_factory):
    store_factory()
    user = get_user_model().objects.create_user(
        email="staff@example.com", password="a-real-password"
    )
    password_hash = user.password

    run_create_staff_user(email="staff@example.com", store="home", role="support")

    user.refresh_from_db()
    assert user.password == password_hash
    assert user.check_password("a-real-password")


def test_keeps_an_existing_staff_flag(store_factory):
    store_factory()
    user = get_user_model().objects.create_user(email="staff@example.com", is_staff=True)

    run_create_staff_user(email="staff@example.com", store="home", role="support")

    user.refresh_from_db()
    assert user.is_staff is True


def test_matches_the_email_regardless_of_case(store_factory):
    store_factory()
    user = get_user_model().objects.create_user(email="staff@example.com")

    run_create_staff_user(email="Staff@Example.com", store="home", role="support")

    assert get_user_model().objects.count() == 1
    assert StoreMembership.objects.get(user=user).role.name == "support"


def test_reactivates_an_inactive_membership_with_the_same_role(store_factory):
    store_factory()
    run_create_staff_user(email="staff@example.com", store="home", role="warehouse")
    membership = StoreMembership.objects.get()
    StoreMembership.objects.filter(pk=membership.pk).update(is_active=False)

    run_create_staff_user(email="staff@example.com", store="home", role="warehouse")

    membership.refresh_from_db()
    assert membership.is_active is True
    assert StoreMembership.objects.count() == 1


def test_refuses_to_escalate_an_existing_role_silently(store_factory):
    store_factory()
    run_create_staff_user(email="staff@example.com", store="home", role="warehouse")

    with pytest.raises(CommandError, match="escalat"):
        run_create_staff_user(email="staff@example.com", store="home", role="owner")

    membership = StoreMembership.objects.get()
    assert membership.role.name == "warehouse"
    assert membership.is_active is True


def test_a_non_escalating_role_change_is_applied_and_reported(store_factory):
    store_factory()
    run_create_staff_user(email="staff@example.com", store="home", role="store_admin")

    output = run_create_staff_user(email="staff@example.com", store="home", role="warehouse")

    membership = StoreMembership.objects.get()
    assert membership.role.name == "warehouse"
    assert "store_admin" in output
    assert "warehouse" in output


def test_rejects_an_unknown_role_and_creates_nothing(store_factory):
    store_factory()

    with pytest.raises(CommandError, match="no-such-role"):
        run_create_staff_user(email="staff@example.com", store="home", role="no-such-role")

    assert not get_user_model().objects.exists()
    assert not StoreMembership.objects.exists()


def test_rejects_an_unknown_store_and_creates_no_user(store_factory):
    with pytest.raises(CommandError, match="nowhere"):
        run_create_staff_user(email="staff@example.com", store="nowhere", role="owner")

    assert not get_user_model().objects.exists()
    assert not StoreMembership.objects.exists()


def test_reports_the_valid_roles_when_given_an_unknown_one(store_factory):
    store_factory()

    with pytest.raises(CommandError, match="owner"):
        run_create_staff_user(email="staff@example.com", store="home", role="nope")
