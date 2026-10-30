import pytest

from apps.shared.domain.exceptions import (
    DomainError,
    NotFoundError,
    PermissionDeniedError,
    StoreNotFoundError,
)


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (NotFoundError("Product not found"), "not_found"),
        (PermissionDeniedError("Not allowed"), "permission_denied"),
        (StoreNotFoundError("No such store"), "store_not_found"),
    ],
)
def test_domain_errors_carry_a_message_and_a_stable_code(error, code):
    assert isinstance(error, DomainError)
    assert error.message == str(error)
    assert error.code == code
