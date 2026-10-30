"""Domain errors shared by every module.

Pure Python: no Django, DRF or infrastructure imports belong here.
"""


class DomainError(Exception):
    """Base class for errors raised by use cases and the domain."""

    code = "domain_error"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class NotFoundError(DomainError):
    code = "not_found"


class PermissionDeniedError(DomainError):
    code = "permission_denied"


class StoreHeaderMissingError(DomainError):
    code = "store_header_missing"


class StoreHeaderInvalidError(DomainError):
    code = "store_header_invalid"
