"""Store vocabulary shared by every module.

Pure Python: no Django, DRF or infrastructure imports belong here.
"""

import re
from dataclasses import dataclass

STORE_SLUG_MAX_LENGTH = 50
STORE_SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
_STORE_SLUG_REGEX = re.compile(STORE_SLUG_PATTERN)


def is_valid_store_slug(value: str) -> bool:
    """Return whether ``value`` is a store slug, without normalizing it."""
    return (
        isinstance(value, str)
        and 1 <= len(value) <= STORE_SLUG_MAX_LENGTH
        and _STORE_SLUG_REGEX.fullmatch(value) is not None
    )


@dataclass(frozen=True, slots=True)
class StoreReference:
    """The store a request is scoped to, as far as this phase can know it."""

    slug: str
