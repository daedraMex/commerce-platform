import pytest
from django.db import IntegrityError, transaction

from apps.stores.models import Store

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("domain", ["Home.Example.com", ""])
def test_the_database_rejects_a_domain_that_skips_normalization(domain):
    store = Store.objects.create(slug="home", name="Home")

    with pytest.raises(IntegrityError), transaction.atomic():
        Store.objects.filter(pk=store.pk).update(domain=domain)
