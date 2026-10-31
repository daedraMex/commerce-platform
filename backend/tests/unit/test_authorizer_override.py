import pytest

from apps.shared.domain.exceptions import PermissionDeniedError
from apps.shared.domain.permissions import ADJUST_INVENTORY
from apps.shared.domain.store import StoreReference
from config.dependencies import get_authorizer


class DenyEverything:
    def require(self, user_id, store, permission):
        raise PermissionDeniedError("Denied by the fake.")


def test_a_fixture_backs_get_authorizer_with_a_fake_without_the_database(override_authorizer):
    override_authorizer(DenyEverything())

    with pytest.raises(PermissionDeniedError, match="Denied by the fake."):
        get_authorizer().require(1, StoreReference(id=1, slug="home"), ADJUST_INVENTORY)
