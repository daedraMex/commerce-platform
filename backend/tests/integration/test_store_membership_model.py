import pytest
from django.db import IntegrityError, transaction

from apps.accounts.models import Role, StoreMembership
from apps.stores.models import Store

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("first_is_active", [True, False])
def test_the_database_rejects_a_second_membership_in_the_same_store(user, store, first_is_active):
    StoreMembership.objects.create(
        user=user, store=store, role=Role.objects.get(name="owner"), is_active=first_is_active
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        StoreMembership.objects.create(
            user=user, store=store, role=Role.objects.get(name="support")
        )

    assert StoreMembership.objects.count() == 1


def test_one_user_holds_a_membership_in_each_of_two_stores(user, store):
    other_store = Store.objects.create(slug="anime", name="Anime")
    owner = Role.objects.get(name="owner")

    StoreMembership.objects.create(user=user, store=store, role=owner)
    StoreMembership.objects.create(user=user, store=other_store, role=owner)

    assert StoreMembership.objects.filter(user=user).count() == 2
