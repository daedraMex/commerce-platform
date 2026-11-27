"""Parse and apply a store's versioned catalog definition file.

The catalog definition is the small JSON file that lists a store's suppliers and
categories before ``import_catalog`` loads its rows (GLOSSARY.md, ADR-0024). It is
idempotent: rows are created or updated by identity, and rows missing from the file
are never deleted or deactivated.
"""

import json
from collections.abc import Mapping
from copy import copy
from dataclasses import dataclass
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.catalog.models import Category, Supplier
from apps.catalog.rules import (
    CatalogRuleError,
    OtherCategory,
    find_sku_conflicts,
    slugify,
    validate_attribute_schema,
    validate_option_schema,
)
from apps.stores.services import lock_store

SUPPORTED_VERSION = 1
PLACEHOLDER_SUPPLIER_NAME = "Por definir"
SUPPLIER_MAX_LENGTH = Supplier._meta.get_field("name").max_length


class DefinitionError(ValueError):
    """A catalog definition file cannot be read or applied."""


@dataclass(frozen=True)
class CategoryDefinition:
    slug: str
    name: str
    sku_code: str
    shape: str
    option_schema: list
    attribute_schema: list

    def values(self):
        return {
            "name": self.name,
            "sku_code": self.sku_code,
            "shape": self.shape,
            "option_schema": self.option_schema,
            "attribute_schema": self.attribute_schema,
        }


@dataclass(frozen=True)
class CatalogDefinition:
    version: int
    suppliers: tuple[str, ...]
    categories: tuple[CategoryDefinition, ...]


@dataclass
class SupplierPlan:
    name: str
    exists: bool

    @property
    def action(self):
        return "unchanged" if self.exists else "create"


@dataclass
class CategoryPlan:
    definition: CategoryDefinition
    instance: Category
    changes: dict
    action: str


@dataclass
class SchemaReport:
    store_slug: str
    categories: list
    suppliers: list
    dry_run: bool

    def render(self):
        created = sum(1 for plan in self.categories if plan.action == "create")
        updated = sum(1 for plan in self.categories if plan.action == "update")
        unchanged = sum(1 for plan in self.categories if plan.action == "unchanged")
        suppliers_created = sum(1 for plan in self.suppliers if plan.action == "create")
        suppliers_unchanged = sum(1 for plan in self.suppliers if plan.action == "unchanged")

        lines = [
            f"Store: {self.store_slug}",
            f"Categories created: {created}",
            f"Categories updated: {updated}",
            f"Categories unchanged: {unchanged}",
            f"Suppliers created: {suppliers_created}",
            f"Suppliers unchanged: {suppliers_unchanged}",
            "",
        ]

        for plan in self.categories:
            if plan.action == "create":
                lines.append(f"Category '{plan.definition.slug}' (create):")
                for field, value in plan.definition.values().items():
                    lines.append(f"  {field}: {_show(value)}")
            elif plan.action == "update":
                lines.append(f"Category '{plan.definition.slug}' (update):")
                for field, (old, new) in plan.changes.items():
                    lines.append(f"  {field}: {_show(old)} -> {_show(new)}")
            else:
                lines.append(f"Category '{plan.definition.slug}' (unchanged)")

        for plan in self.suppliers:
            lines.append(f"Supplier '{plan.name}' ({plan.action})")

        if self.dry_run:
            lines.append("")
            lines.append("Dry run: nothing was written.")
        return "\n".join(lines) + "\n"


def _show(value):
    if isinstance(value, str):
        return repr(value)
    return json.dumps(value, ensure_ascii=False)


def load_catalog_definition(path, *, store_slug):
    """Read a catalog definition file and return its validated content."""
    file_path = Path(path).expanduser()
    try:
        text = file_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as error:
        raise DefinitionError(
            f"The catalog definition file {path!r} is not valid UTF-8: {error}."
        ) from error
    except OSError as error:
        raise DefinitionError(
            f"Cannot read the catalog definition file {path!r}: {error}."
        ) from error

    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise DefinitionError(
            f"The catalog definition file {path!r} is not valid JSON: "
            f"{error.msg} at line {error.lineno}, column {error.colno}."
        ) from error

    return parse_catalog_definition(data, store_slug=store_slug)


def parse_catalog_definition(data, *, store_slug):
    """Validate the shape of a catalog definition and normalize its values."""
    if not isinstance(data, Mapping):
        raise DefinitionError("The catalog definition must be a JSON object.")

    version = data.get("version", SUPPORTED_VERSION)
    if isinstance(version, bool) or version != SUPPORTED_VERSION:
        raise DefinitionError(
            f"Unsupported catalog definition version {version!r}; "
            f"this command supports version {SUPPORTED_VERSION}."
        )

    named_store = data.get("store")
    if named_store is not None:
        if not isinstance(named_store, str) or not named_store.strip():
            raise DefinitionError("The catalog definition's 'store' must be a non-empty text.")
        if named_store.strip() != store_slug:
            raise DefinitionError(
                f"The catalog definition is for store {named_store.strip()!r}, not {store_slug!r}."
            )

    if "suppliers" not in data:
        raise DefinitionError("The catalog definition is missing the 'suppliers' list.")
    if "categories" not in data:
        raise DefinitionError("The catalog definition is missing the 'categories' list.")

    suppliers = _parse_suppliers(data["suppliers"])
    categories = _parse_categories(data["categories"])
    return CatalogDefinition(version=version, suppliers=suppliers, categories=categories)


def _parse_suppliers(value):
    if not isinstance(value, list):
        raise DefinitionError("The catalog definition's 'suppliers' must be a list.")

    names = []
    for index, entry in enumerate(value, start=1):
        if isinstance(entry, str):
            name = entry.strip()
        elif isinstance(entry, Mapping):
            name = entry.get("name")
            if not isinstance(name, str):
                raise DefinitionError(f"Supplier {index} needs a non-empty 'name'.")
            name = name.strip()
        else:
            raise DefinitionError(f"Supplier {index} must be a name or an object with a 'name'.")

        if not name:
            raise DefinitionError(f"Supplier {index} needs a non-empty name.")
        if len(name) > SUPPLIER_MAX_LENGTH:
            raise DefinitionError(
                f"Supplier {index} is longer than {SUPPLIER_MAX_LENGTH} characters."
            )
        if name in names:
            raise DefinitionError(f"Supplier {name!r} is listed twice.")
        names.append(name)

    if PLACEHOLDER_SUPPLIER_NAME not in names:
        names.append(PLACEHOLDER_SUPPLIER_NAME)
    return tuple(names)


def _parse_categories(value):
    if isinstance(value, Mapping):
        entries = []
        for index, (slug_key, entry) in enumerate(value.items(), start=1):
            if not isinstance(entry, Mapping):
                raise DefinitionError(f"Category {index} must be a JSON object.")
            entry = dict(entry)
            declared_slug = entry.get("slug")
            if declared_slug is not None and slugify(str(declared_slug)) != slugify(str(slug_key)):
                raise DefinitionError(
                    f"Category {index} is keyed as {slug_key!r} but declares "
                    f"the slug {declared_slug!r}."
                )
            entry["slug"] = slug_key
            entries.append((index, entry))
    elif isinstance(value, list):
        entries = list(enumerate(value, start=1))
    else:
        raise DefinitionError("The catalog definition's 'categories' must be a list.")

    categories = []
    seen_slugs = set()
    for index, entry in entries:
        if not isinstance(entry, Mapping):
            raise DefinitionError(f"Category {index} must be a JSON object.")
        category = _parse_category(index, entry)
        if category.slug in seen_slugs:
            raise DefinitionError(f"Category slug {category.slug!r} is listed twice.")
        seen_slugs.add(category.slug)
        categories.append(category)
    return tuple(categories)


def _parse_category(index, entry):
    raw_slug = _required_text(entry, "slug", f"Category {index}")
    slug = slugify(raw_slug)
    if not slug:
        raise DefinitionError(f"Category {index} has a slug that cannot be normalized.")

    name = _required_text(entry, "name", f"Category {index} ({slug})")
    sku_code = _required_text(entry, "sku_code", f"Category {index} ({slug})").upper()

    raw_shape = entry.get("shape", Category.Shape.RECTANGLE)
    if not isinstance(raw_shape, str):
        raise DefinitionError(f"Category {index} ({slug}) has a non-text 'shape'.")
    shape = raw_shape.strip().lower()
    if shape not in Category.Shape.values:
        choices = ", ".join(Category.Shape.values)
        raise DefinitionError(
            f"Category {index} ({slug}) has the unknown shape {raw_shape!r}; use one of: {choices}."
        )

    option_schema = entry.get("option_schema", [])
    try:
        validate_option_schema(option_schema)
    except CatalogRuleError as error:
        raise DefinitionError(
            f"Category {index} ({slug}) has an invalid option schema: {error}"
        ) from error

    attribute_schema = entry.get("attribute_schema", [])
    try:
        validate_attribute_schema(attribute_schema)
    except CatalogRuleError as error:
        raise DefinitionError(
            f"Category {index} ({slug}) has an invalid attribute schema: {error}"
        ) from error

    return CategoryDefinition(
        slug=slug,
        name=name,
        sku_code=sku_code,
        shape=shape,
        option_schema=option_schema,
        attribute_schema=attribute_schema,
    )


def _required_text(entry, key, label):
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DefinitionError(f"{label} needs a non-empty '{key}'.")
    return value.strip()


def apply_catalog_definition(store, definition, *, dry_run=False):
    """Create or update the store's suppliers and categories, returning the report."""
    if dry_run:
        return _plan_and_report(store, definition, dry_run=True)

    with transaction.atomic():
        lock_store(store.pk)
        report = _plan_and_report(store, definition, dry_run=False)
        for plan in report.suppliers:
            if plan.exists:
                continue
            Supplier.objects.create(store=store, name=plan.name)
        for plan in report.categories:
            if plan.action == "create":
                plan.instance.save()
            elif plan.action == "update":
                plan.instance.save()
    return report


def _plan_and_report(store, definition, *, dry_run):
    existing_suppliers = {
        supplier.name for supplier in Supplier.objects.filter(store=store).only("name")
    }
    supplier_plans = [
        SupplierPlan(name=name, exists=name in existing_suppliers) for name in definition.suppliers
    ]

    existing_categories = {
        category.slug: category for category in Category.objects.filter(store=store)
    }
    category_plans = []
    for category in definition.categories:
        existing = existing_categories.get(category.slug)
        if existing is None:
            instance = Category(store=store, slug=category.slug, **category.values())
            _validate_category(category, instance, create=True)
            category_plans.append(
                CategoryPlan(
                    definition=category,
                    instance=instance,
                    changes={},
                    action="create",
                )
            )
            continue

        changes = _changes(existing, category)
        instance = copy(existing)
        for field, value in category.values().items():
            setattr(instance, field, value)
        if changes:
            _validate_category(category, instance, create=False)
        category_plans.append(
            CategoryPlan(
                definition=category,
                instance=instance,
                changes=changes,
                action="update" if changes else "unchanged",
            )
        )

    _validate_sku_conflicts(category_plans)
    return SchemaReport(
        store_slug=store.slug,
        categories=category_plans,
        suppliers=supplier_plans,
        dry_run=dry_run,
    )


def _changes(existing, category):
    changes = {}
    for field, value in category.values().items():
        stored = getattr(existing, field)
        if stored != value:
            changes[field] = (stored, value)
    return changes


def _validate_category(category, instance, *, create):
    try:
        instance.full_clean()
    except ValidationError as error:
        detail = _validation_message(error)
        action = "create" if create else "update"
        raise DefinitionError(f"Cannot {action} category {category.slug!r}: {detail}") from error


def _validate_sku_conflicts(category_plans):
    desired = [
        OtherCategory(
            name=plan.definition.name,
            sku_code=plan.definition.sku_code,
            option_schema=plan.definition.option_schema,
        )
        for plan in category_plans
    ]
    for index, plan in enumerate(category_plans):
        others = [other for position, other in enumerate(desired) if position != index]
        conflicts = find_sku_conflicts(
            sku_code=plan.definition.sku_code,
            option_schema=plan.definition.option_schema,
            others=others,
        )
        if not conflicts:
            continue
        descriptions = "; ".join(
            f"{conflict.category} ({', '.join(code or 'no options' for code in conflict.codes)})"
            for conflict in conflicts
        )
        raise DefinitionError(
            f"Category {plan.definition.slug!r} has SKU suffixes that overlap with another "
            f"category in the file: {descriptions}."
        )


def _validation_message(error):
    if hasattr(error, "message_dict"):
        parts = []
        for field, messages in error.message_dict.items():
            parts.append(f"{field}: {'; '.join(messages)}")
        return "; ".join(parts)
    return "; ".join(error.messages)
