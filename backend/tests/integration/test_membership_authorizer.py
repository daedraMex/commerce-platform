import pytest
from django.contrib.auth import get_user_model

from apps.accounts.models import StoreMembership
from apps.accounts.services import grant_membership
from apps.shared.domain.exceptions import PermissionDeniedError
from apps.shared.domain.permissions import REFUND_ORDER
from apps.shared.domain.store import StoreReference
from apps.stores.models import Store
from config.dependencies import get_authorizer

pytestmark = pytest.mark.django_db


def reference(store):
    return StoreReference(id=store.id, slug=store.slug)


def test_passes_for_a_role_that_holds_the_permission(user, store):
    grant_membership(user=user, store=store, role_name="owner")

    assert get_authorizer().require(user.id, reference(store), REFUND_ORDER) is None


def test_denies_a_role_without_the_permission(user, store):
    grant_membership(user=user, store=store, role_name="store_admin")

    with pytest.raises(PermissionDeniedError):
        get_authorizer().require(user.id, reference(store), REFUND_ORDER)


def test_denies_a_membership_in_another_store(user, store):
    other_store = Store.objects.create(slug="anime", name="Anime")
    grant_membership(user=user, store=other_store, role_name="owner")

    with pytest.raises(PermissionDeniedError):
        get_authorizer().require(user.id, reference(store), REFUND_ORDER)


def test_denies_an_inactive_membership(user, store):
    membership = grant_membership(user=user, store=store, role_name="owner")
    StoreMembership.objects.filter(pk=membership.pk).update(is_active=False)

    with pytest.raises(PermissionDeniedError):
        get_authorizer().require(user.id, reference(store), REFUND_ORDER)


def test_denies_a_superuser_without_a_membership(store):
    superuser = get_user_model().objects.create_superuser(
        email="operator@example.com", password="s3cret-pass"
    )

    with pytest.raises(PermissionDeniedError):
        get_authorizer().require(superuser.id, reference(store), REFUND_ORDER)
