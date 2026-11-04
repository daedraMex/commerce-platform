"""Catalog rules as pure functions.

Pure Python: no Django, DRF or infrastructure imports belong here (ADR-0024).
"""

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import product

ATTRIBUTE_TYPES = frozenset({"text", "number", "boolean", "choice"})
SIZE_OPTION_CODE = "size"
SLUG_MAX_LENGTH = 100

_SLUG_SEPARATOR = re.compile(r"[^a-z0-9]+")


class CatalogRuleError(ValueError):
    """A catalog rule rejected a value."""


def _capitalized(value):
    return value[:1].upper() + value[1:]


def _entry_name(index, entry, kind, key):
    code = entry.get(key) if isinstance(entry, Mapping) else None
    if isinstance(code, str) and code:
        return f"{kind} {index} (code='{code}')"
    return f"{kind} {index}"


def _require_string(entry, key, name):
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CatalogRuleError(f"{_capitalized(name)} needs a non-empty '{key}'.")
    return value


def _positive_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def validate_attribute_schema(schema) -> None:
    """Reject an attribute schema that does not match ADR-0024's format."""
    if not isinstance(schema, list):
        raise CatalogRuleError("The attribute schema must be a list.")

    seen_codes = set()
    for index, entry in enumerate(schema):
        name = _entry_name(index, entry, "attribute", "code")
        if not isinstance(entry, Mapping):
            raise CatalogRuleError(f"Attribute {index} must be an object.")

        for key in ("code", "label", "type", "choices", "required"):
            if key not in entry:
                raise CatalogRuleError(f"{_capitalized(name)} is missing '{key}'.")

        code = _require_string(entry, "code", name)
        if code in seen_codes:
            raise CatalogRuleError(f"Attribute {index} repeats the code '{code}'.")
        seen_codes.add(code)
        _require_string(entry, "label", name)

        attribute_type = entry["type"]
        if not isinstance(attribute_type, str) or attribute_type not in ATTRIBUTE_TYPES:
            raise CatalogRuleError(f"{_capitalized(name)} has the unknown type '{attribute_type}'.")

        choices = entry["choices"]
        if not isinstance(choices, list):
            raise CatalogRuleError(f"{_capitalized(name)} needs a list of 'choices'.")
        if attribute_type == "choice" and not choices:
            raise CatalogRuleError(f"{_capitalized(name)} of type choice needs choices.")
        if any(not isinstance(choice, str) or not choice.strip() for choice in choices):
            raise CatalogRuleError(f"{_capitalized(name)} has an empty or non-text choice.")

        if not isinstance(entry["required"], bool):
            raise CatalogRuleError(f"{_capitalized(name)} needs a boolean 'required'.")


def validate_option_schema(schema) -> None:
    """Reject an option schema that does not match ADR-0024's format.

    Size dimensions are the value's bounding box and may be approximate.
    """
    if not isinstance(schema, list):
        raise CatalogRuleError("The option schema must be a list.")

    seen_codes = set()
    for index, entry in enumerate(schema):
        name = _entry_name(index, entry, "option", "code")
        if not isinstance(entry, Mapping):
            raise CatalogRuleError(f"Option {index} must be an object.")

        for key in ("code", "label", "values"):
            if key not in entry:
                raise CatalogRuleError(f"{_capitalized(name)} is missing '{key}'.")

        code = _require_string(entry, "code", name)
        if code in seen_codes:
            raise CatalogRuleError(f"Option {index} repeats the code '{code}'.")
        seen_codes.add(code)
        _require_string(entry, "label", name)

        values = entry["values"]
        if not isinstance(values, list) or not values:
            raise CatalogRuleError(f"{_capitalized(name)} needs a non-empty list of 'values'.")

        # ADR-0024 has no size flag; Phase 4 categories call their size option "size".
        is_size = code.strip().lower() == SIZE_OPTION_CODE
        seen_value_codes = set()
        for value_index, value in enumerate(values):
            value_name = _entry_name(value_index, value, f"value of option '{code}'", "code")
            if not isinstance(value, Mapping):
                raise CatalogRuleError(f"{_capitalized(value_name)} must be an object.")

            for key in ("code", "label"):
                if key not in value:
                    raise CatalogRuleError(f"{_capitalized(value_name)} is missing '{key}'.")

            value_code = _require_string(value, "code", value_name)
            if value_code in seen_value_codes:
                raise CatalogRuleError(
                    f"{_capitalized(value_name)} repeats the code '{value_code}'."
                )
            seen_value_codes.add(value_code)
            _require_string(value, "label", value_name)

            if is_size:
                for dimension in ("width_cm", "height_cm"):
                    if dimension not in value:
                        raise CatalogRuleError(
                            f"{_capitalized(value_name)} is missing '{dimension}'."
                        )
                    if not _positive_number(value[dimension]):
                        raise CatalogRuleError(
                            f"{_capitalized(value_name)} needs a positive '{dimension}'."
                        )
            else:
                for dimension in ("width_cm", "height_cm"):
                    if dimension in value:
                        raise CatalogRuleError(
                            f"{_capitalized(value_name)} has a '{dimension}' but "
                            f"option '{code}' is not a size."
                        )


def sku_suffixes(option_schema) -> frozenset[str]:
    """Every SKU suffix a category can generate, including "" when it has no options."""
    values_by_option = [[value["code"] for value in option["values"]] for option in option_schema]
    if not values_by_option:
        return frozenset({""})
    return frozenset("-".join(combination) for combination in product(*values_by_option))


@dataclass(frozen=True, slots=True)
class OtherCategory:
    name: str
    sku_code: str
    option_schema: Sequence[Mapping[str, object]]


@dataclass(frozen=True, slots=True)
class SkuConflict:
    category: str
    codes: tuple[str, ...]


def find_sku_conflicts(
    *, sku_code: str, option_schema, others: Iterable[OtherCategory]
) -> tuple[SkuConflict, ...]:
    """Report other categories with the same SKU code that can generate the same suffix."""
    own_suffixes = sku_suffixes(option_schema)
    conflicts = []
    normalised_code = sku_code.strip().upper()
    for other in others:
        if other.sku_code.strip().upper() != normalised_code:
            continue
        shared = own_suffixes & sku_suffixes(other.option_schema)
        if shared:
            conflicts.append(SkuConflict(category=other.name, codes=tuple(sorted(shared))))
    return tuple(conflicts)


def slugify(name: str) -> str:
    """Lowercase a name, strip its accents and join its words with single hyphens."""
    decomposed = unicodedata.normalize("NFKD", name)
    without_accents = decomposed.encode("ascii", "ignore").decode("ascii").lower()
    slug = _SLUG_SEPARATOR.sub("-", without_accents).strip("-")
    return slug[:SLUG_MAX_LENGTH].rstrip("-")
