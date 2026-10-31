import pytest

from apps.accounts.models import StoreMembership
from apps.accounts.services import grant_membership

pytestmark = pytest.mark.django_db


def test_creates_an_active_membership_with_the_role(user, store):
    membership = grant_membership(user=user, store=store, role_name="warehouse")

    assert membership.is_active is True
    assert membership.role.name == "warehouse"
    assert StoreMembership.objects.get(user=user, store=store) == membership


def test_reactivates_an_inactive_membership_with_a_new_role_instead_of_adding_a_row(user, store):
    first = grant_membership(user=user, store=store, role_name="warehouse")
    StoreMembership.objects.filter(pk=first.pk).update(is_active=False)

    membership = grant_membership(user=user, store=store, role_name="support")

    assert membership.pk == first.pk
    membership.refresh_from_db()
    assert membership.is_active is True
    assert membership.role.name == "support"
    assert StoreMembership.objects.count() == 1


def test_rejects_an_unknown_role_and_creates_no_membership(user, store):
    with pytest.raises(ValueError, match="no-such-role"):
        grant_membership(user=user, store=store, role_name="no-such-role")

    assert not StoreMembership.objects.exists()
