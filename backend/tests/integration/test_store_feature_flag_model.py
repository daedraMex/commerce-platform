import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.stores.models import StoreFeatureFlag

pytestmark = pytest.mark.django_db


def test_the_database_rejects_a_second_flag_with_the_same_store_and_code(store):
    StoreFeatureFlag.objects.create(store=store, code="instagram-publishing")

    with pytest.raises(IntegrityError), transaction.atomic():
        StoreFeatureFlag.objects.create(store=store, code="instagram-publishing", enabled=True)


@pytest.mark.parametrize("code", ["Instagram", "instagram_publishing", "-instagram", "a" * 51])
def test_a_code_that_breaks_the_slug_rule_is_rejected(store, code):
    flag = StoreFeatureFlag(store=store, code=code)

    with pytest.raises(ValidationError) as error:
        flag.full_clean()

    assert "invalid_feature_flag_code" in [e.code for e in error.value.error_dict["code"]]
