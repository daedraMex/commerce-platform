"""Load a store's catalog from a one-row-per-variant CSV."""

import csv
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.contrib.admin.models import LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.catalog.management.support import (
    PRICE_FIELDS,
    build_variant_change_entry,
    get_active_store,
    resolve_operator,
    snapshot,
)
from apps.catalog.models import (
    Category,
    Collection,
    CollectionProduct,
    Design,
    Product,
    ProductVariant,
    Supplier,
)
from apps.catalog.rules import (
    CatalogRuleError,
    build_sku,
    default_product_name,
    normalize_sku,
    slugify,
    validate_option_values,
    validate_prices,
    validate_product_attributes,
)
from apps.stores.services import lock_store

REQUIRED_COLUMNS = ("category", "supplier", "supplier_design_name", "design_name", "price", "cost")
FIXED_COLUMNS = frozenset(REQUIRED_COLUMNS) | {
    "option_values",
    "compare_at_price",
    "weight_grams",
    "package_length_cm",
    "package_width_cm",
    "package_height_cm",
    "collections",
    "attributes",
    "description",
    "main_image",
    "gallery_images",
}
LIST_SEPARATOR = ";"
PAIR_SEPARATOR = "="
# Mirrors the model fields: DecimalField(max_digits=10, decimal_places=2) for money,
# DecimalField(max_digits=8, decimal_places=2) for package dimensions, and a 32-bit
# PositiveIntegerField for weight.
MAX_MONEY = Decimal("99999999.99")
MAX_DIMENSION = Decimal("999999.99")
MAX_WEIGHT_GRAMS = 2147483647
VARIANT_VALUE_FIELDS = (
    "price",
    "compare_at_price",
    "cost",
    "weight_grams",
    "package_length_cm",
    "package_width_cm",
    "package_height_cm",
)


class RowError(ValueError):
    """One CSV row cannot be imported."""


@dataclass(frozen=True)
class Rejection:
    line: int
    reason: str


@dataclass
class ParsedRow:
    line: int
    category: Category
    supplier: Supplier
    supplier_design_name: str
    design_name: str
    option_values: dict
    price: Decimal
    compare_at_price: Decimal | None
    cost: Decimal
    weight_grams: int | None
    package_length_cm: Decimal | None
    package_width_cm: Decimal | None
    package_height_cm: Decimal | None
    collection_names: tuple[str, ...]
    attributes: dict
    description: str

    @property
    def design_key(self):
        return (self.supplier.pk, self.supplier_design_name.casefold())

    @property
    def product_key(self):
        return (self.design_key, self.category.pk)

    @property
    def option_key(self):
        return tuple(sorted(self.option_values.items()))


@dataclass
class RowPlan:
    row: ParsedRow
    design: Design
    product: Product
    variant: ProductVariant | None
    old_values: dict = field(default_factory=dict)
    changed: bool = False


@dataclass
class Report:
    created: int
    updated: int
    unchanged: int
    rejected: int
    rejections: list
    collections: list
    dry_run: bool

    def render(self):
        lines = [
            f"Rows created: {self.created}",
            f"Rows updated: {self.updated}",
            f"Rows unchanged: {self.unchanged}",
            f"Rows rejected: {self.rejected}",
            f"Collections created: {len(self.collections)}",
        ]
        for name in self.collections:
            lines.append(f"  - {name}")
        for rejection in self.rejections:
            lines.append(f"  Row {rejection.line}: {rejection.reason}")
        if self.dry_run:
            lines.append("Dry run: nothing was written.")
        return "\n".join(lines) + "\n"


class Command(BaseCommand):
    help = "Import a store catalog from a one-row-per-variant CSV."

    def add_arguments(self, parser):
        parser.add_argument("--store", required=True, help="Store slug.")
        parser.add_argument("--csv", required=True, help="Path to the CSV file.")
        parser.add_argument("--operator", required=True, help="Email of an active superuser.")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        # The operator is checked before the file, the store or any catalog row is read.
        operator = resolve_operator(options["operator"])
        store = get_active_store(options["store"])
        dry_run = options["dry_run"]

        rows, rejections = _read_rows(options["csv"], store)
        if dry_run:
            report = _execute(store, rows, rejections, operator, dry_run=True)
        else:
            with transaction.atomic():
                lock_store(store.pk)
                report = _execute(store, rows, rejections, operator, dry_run=False)

        self.stdout.write(report.render())
        if report.rejected:
            raise CommandError(f"{report.rejected} row(s) rejected.")


def _read_rows(path, store):
    categories = {category.slug: category for category in Category.objects.filter(store=store)}
    suppliers = {supplier.name: supplier for supplier in Supplier.objects.filter(store=store)}

    try:
        csv_file = Path(path).open(newline="", encoding="utf-8-sig")
    except OSError as error:
        raise CommandError(f"Cannot read the CSV file {path!r}: {error}.") from error

    with csv_file:
        reader = csv.DictReader(csv_file)
        if reader.fieldnames is None:
            raise CommandError("The CSV file is empty.")
        reader.fieldnames = [name.strip() for name in reader.fieldnames]
        missing = [column for column in REQUIRED_COLUMNS if column not in reader.fieldnames]
        if missing:
            raise CommandError(f"The CSV is missing the column(s): {', '.join(missing)}.")

        rows = []
        rejections = []
        try:
            for raw in reader:
                line = reader.line_num
                if None in raw:
                    rejections.append(Rejection(line, "The row has more cells than the header."))
                    continue
                if not any((value or "").strip() for value in raw.values()):
                    continue
                try:
                    rows.append(_parse_row(raw, line, categories, suppliers))
                except RowError as error:
                    rejections.append(Rejection(line, str(error)))
        except csv.Error as error:
            raise CommandError(f"The CSV file {path!r} is malformed: {error}.") from error

    return rows, rejections


def _parse_row(raw, line, categories, suppliers):
    category_slug = _text(raw, "category")
    if not category_slug:
        raise RowError("The row needs a category.")
    category = categories.get(category_slug)
    if category is None:
        raise RowError(f"Unknown category '{category_slug}'.")

    # Supplier names are matched exactly, so "Beka " never resolves to "Beka".
    supplier_name = raw.get("supplier") or ""
    if not supplier_name.strip():
        raise RowError("The row needs a supplier.")
    supplier = suppliers.get(supplier_name)
    if supplier is None:
        raise RowError(f"Unknown supplier '{supplier_name}'.")

    supplier_design_name = _collapsed(raw.get("supplier_design_name"))
    if not supplier_design_name:
        raise RowError("The row needs a supplier_design_name.")

    design_name = _text(raw, "design_name")
    if not design_name:
        raise RowError("The row needs a design_name.")

    option_values = _option_values(raw, category)
    try:
        validate_option_values(option_values, category.option_schema)
    except CatalogRuleError as error:
        raise RowError(str(error)) from error

    attributes = _attributes(raw, category)
    try:
        validate_product_attributes(attributes, category.attribute_schema)
    except CatalogRuleError as error:
        raise RowError(str(error)) from error

    price = _required_decimal(raw, "price", max_value=MAX_MONEY)
    cost = _required_decimal(raw, "cost", max_value=MAX_MONEY)
    compare_at_price = _optional_decimal(raw, "compare_at_price", max_value=MAX_MONEY)
    try:
        validate_prices(price, compare_at_price, cost)
    except CatalogRuleError as error:
        raise RowError(str(error)) from error

    collection_names = _collection_names(raw)
    for name in collection_names:
        if not slugify(name):
            raise RowError(f"Cannot build a collection slug from {name!r}.")

    return ParsedRow(
        line=line,
        category=category,
        supplier=supplier,
        supplier_design_name=supplier_design_name,
        design_name=design_name,
        option_values=option_values,
        price=price,
        compare_at_price=compare_at_price,
        cost=cost,
        weight_grams=_optional_int(raw, "weight_grams", max_value=MAX_WEIGHT_GRAMS),
        package_length_cm=_optional_decimal(raw, "package_length_cm", max_value=MAX_DIMENSION),
        package_width_cm=_optional_decimal(raw, "package_width_cm", max_value=MAX_DIMENSION),
        package_height_cm=_optional_decimal(raw, "package_height_cm", max_value=MAX_DIMENSION),
        collection_names=collection_names,
        attributes=attributes,
        description=_text(raw, "description"),
    )


def _text(raw, key):
    return (raw.get(key) or "").strip()


def _collapsed(value):
    return " ".join((value or "").split())


def _split_list(value):
    return [part.strip() for part in (value or "").split(LIST_SEPARATOR) if part.strip()]


def _pairs(value, *, single_key=None):
    pairs = {}
    for part in _split_list(value):
        if PAIR_SEPARATOR in part:
            key, item = part.split(PAIR_SEPARATOR, 1)
            key = key.strip()
            if not key:
                raise RowError(f"Malformed pair '{part}': it needs a code before '='.")
            pairs[key] = item.strip()
        elif single_key is not None:
            pairs[single_key] = part
        else:
            raise RowError(f"Malformed pair '{part}': use code=value.")
    return pairs


def _option_values(raw, category):
    option_codes = [option["code"] for option in category.option_schema]
    single_key = option_codes[0] if len(option_codes) == 1 else None
    values = _pairs(raw.get("option_values"), single_key=single_key)

    for code in option_codes:
        if code in raw and code not in FIXED_COLUMNS:
            direct = (raw.get(code) or "").strip()
            if direct:
                values[code] = direct

    return {code: value for code, value in values.items() if value}


def _attributes(raw, category):
    schema_by_code = {entry["code"]: entry for entry in category.attribute_schema}
    values = _pairs(raw.get("attributes"))

    for code in schema_by_code:
        if code in raw and code not in FIXED_COLUMNS:
            direct = (raw.get(code) or "").strip()
            if direct:
                values[code] = direct

    return {
        code: _coerce_attribute(code, value, schema_by_code)
        for code, value in values.items()
        if value != ""
    }


def _coerce_attribute(code, value, schema_by_code):
    entry = schema_by_code.get(code)
    if entry is None:
        return value
    attribute_type = entry["type"]
    if attribute_type == "number":
        number = _as_decimal(value, f"attribute '{code}'")
        return int(number) if number == number.to_integral_value() else float(number)
    if attribute_type == "boolean":
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
        raise RowError(f"The attribute '{code}' must be true or false.")
    return value


def _collection_names(raw):
    seen = []
    for name in _split_list(raw.get("collections")):
        if name not in seen:
            seen.append(name)
    return tuple(seen)


def _required_decimal(raw, key, *, max_value=None):
    value = _text(raw, key)
    if not value:
        raise RowError(f"The {key.replace('_', '-')} is required.")
    return _as_decimal(value, key.replace("_", "-"), max_value=max_value)


def _optional_decimal(raw, key, *, max_value=None):
    value = _text(raw, key)
    if not value:
        return None
    number = _as_decimal(value, key.replace("_", "-"), max_value=max_value)
    if number < 0:
        raise RowError(f"The {key.replace('_', '-')} must not be negative.")
    return number


def _as_decimal(value, name, *, max_value=None):
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise RowError(f"The {name} must be a number, not {value!r}.") from error
    if not number.is_finite():
        raise RowError(f"The {name} must be a finite number, not {value!r}.")
    try:
        if number != number.quantize(Decimal("0.01")):
            raise RowError(f"The {name} must have at most two decimal places.")
    except InvalidOperation as error:
        raise RowError(f"The {name} is out of range.") from error
    if max_value is not None and number > max_value:
        raise RowError(f"The {name} must be at most {max_value}.")
    return number


def _optional_int(raw, key, *, max_value=None):
    value = _text(raw, key)
    if not value:
        return None
    try:
        number = int(value)
    except ValueError as error:
        raise RowError(f"The {key.replace('_', '-')} must be a whole number.") from error
    if number < 0:
        raise RowError(f"The {key.replace('_', '-')} must not be negative.")
    if max_value is not None and number > max_value:
        raise RowError(f"The {key.replace('_', '-')} must be at most {max_value}.")
    return number


def _execute(store, rows, rejections, operator, *, dry_run):
    if rejections:
        return _rejected_report(rejections, dry_run)

    plan = _plan(store, rows, dry_run=dry_run)
    if plan.rejections:
        return _rejected_report(plan.rejections, dry_run)

    existing = [row_plan for row_plan in plan.rows if row_plan.variant is not None]
    created = len(plan.rows) - len(existing)
    updated = sum(1 for row_plan in existing if row_plan.changed)
    unchanged = len(existing) - updated
    if dry_run:
        return Report(created, updated, unchanged, 0, [], plan.new_collections, True)

    _write(plan, operator)
    return Report(
        created,
        updated,
        unchanged,
        0,
        [],
        [collection.name for collection in plan.new_collections],
        False,
    )


def _rejected_report(rejections, dry_run):
    return Report(0, 0, 0, len(rejections), rejections, [], dry_run)


@dataclass
class Plan:
    rows: list
    new_designs: list
    new_products: list
    changed_products: list
    new_collections: list
    collections_by_name: dict
    memberships: list
    existing_memberships: set
    rejections: list


def _plan(store, rows, *, dry_run):
    existing_designs = list(Design.objects.filter(store=store))
    designs_by_key = {
        (design.supplier_id, design.supplier_design_name.casefold()): design
        for design in existing_designs
    }

    designs = {}
    new_designs = []
    for row in rows:
        if row.design_key in designs:
            continue
        design = designs_by_key.get(row.design_key)
        if design is None:
            design = Design(
                store=store,
                name=row.design_name,
                supplier=row.supplier,
                supplier_design_name=row.supplier_design_name,
                is_active=True,
            )
            new_designs.append(design)
        designs[row.design_key] = design

    if not dry_run:
        next_number = max((design.number for design in existing_designs), default=0) + 1
        for design in new_designs:
            design.number = next_number
            next_number += 1

    existing_products = list(Product.objects.filter(store=store).select_related("category"))
    products_by_key = {
        (product.design_id, product.category_id): product
        for product in existing_products
        if product.design_id
    }
    used_product_slugs = {product.slug for product in existing_products}

    products = {}
    product_errors = {}
    new_products = []
    changed_products = []
    changed_product_keys = set()
    for row in rows:
        if row.product_key in products or row.product_key in product_errors:
            continue
        design = designs[row.design_key]
        product = products_by_key.get((design.pk, row.category.pk)) if design.pk else None
        if product is None:
            name = default_product_name(row.category.name, design.name)
            try:
                slug = _unique_slug(name, used_product_slugs)
            except RowError as error:
                product_errors[row.product_key] = str(error)
                continue
            product = Product(
                store=store,
                category=row.category,
                design=design,
                name=name,
                slug=slug,
                attributes=row.attributes,
                description=row.description,
                is_active=True,
            )
            new_products.append(product)
        elif product.attributes != row.attributes or product.description != row.description:
            product.attributes = row.attributes
            product.description = row.description
            product.updated_at = timezone.now()
            changed_products.append(product)
            changed_product_keys.add(row.product_key)
        products[row.product_key] = product

    existing_variants = list(ProductVariant.objects.filter(store=store))
    variants_by_sku = {variant.sku.upper(): variant for variant in existing_variants}

    row_plans = []
    rejections = []
    seen = {}
    for row in rows:
        if row.product_key in product_errors:
            rejections.append(Rejection(row.line, product_errors[row.product_key]))
            continue

        design = designs[row.design_key]
        product = products[row.product_key]

        variant_key = (row.design_key, row.category.pk, row.option_key)
        if variant_key in seen:
            rejections.append(
                Rejection(
                    row.line,
                    f"Duplicate row for {row.category.sku_code}-{design.formatted_number} "
                    f"with the same option values.",
                )
            )
            continue
        seen[variant_key] = row.line

        variant = None
        if design.pk is not None:
            sku = build_sku(
                row.category.sku_code,
                design.number,
                row.category.option_schema,
                row.option_values,
            )
            variant = variants_by_sku.get(normalize_sku(sku))
            if variant is not None:
                if variant.product_id != product.pk:
                    rejections.append(
                        Rejection(row.line, f"The SKU {sku} belongs to another product.")
                    )
                    continue
                if variant.option_values != row.option_values:
                    rejections.append(
                        Rejection(row.line, f"The SKU {sku} has different option values.")
                    )
                    continue

        row_plans.append(
            RowPlan(
                row=row,
                design=design,
                product=product,
                variant=variant,
                old_values=snapshot(variant, PRICE_FIELDS) if variant is not None else {},
            )
        )

    collections_by_name = {
        collection.name: collection for collection in Collection.objects.filter(store=store)
    }
    used_collection_slugs = {collection.slug for collection in collections_by_name.values()}
    new_collections = []
    for row_plan in row_plans:
        for name in row_plan.row.collection_names:
            if name in collections_by_name:
                continue
            collection = Collection(
                store=store,
                name=name,
                slug=_unique_slug(name, used_collection_slugs),
                is_active=True,
            )
            collections_by_name[name] = collection
            new_collections.append(collection)

    memberships = list(CollectionProduct.objects.filter(collection__store=store))
    existing_memberships = {
        (membership.collection_id, membership.product_id) for membership in memberships
    }

    for row_plan in row_plans:
        row_plan.changed = _row_changed(
            row_plan,
            changed_product_keys,
            collections_by_name,
            existing_memberships,
        )

    return Plan(
        rows=row_plans,
        new_designs=new_designs,
        new_products=new_products,
        changed_products=changed_products,
        new_collections=new_collections,
        collections_by_name=collections_by_name,
        memberships=memberships,
        existing_memberships=existing_memberships,
        rejections=rejections,
    )


def _row_changed(row_plan, changed_product_keys, collections_by_name, existing_memberships):
    """Whether this row would change anything already stored."""
    if row_plan.variant is None:
        return False
    if row_plan.row.product_key in changed_product_keys:
        return True
    if any(
        getattr(row_plan.variant, field) != getattr(row_plan.row, field)
        for field in VARIANT_VALUE_FIELDS
    ):
        return True
    for name in row_plan.row.collection_names:
        collection = collections_by_name[name]
        if (collection.pk, row_plan.product.pk) not in existing_memberships:
            return True
    return False


def _write(plan, operator):
    if plan.new_designs:
        Design.objects.bulk_create(plan.new_designs)
    if plan.new_products:
        Product.objects.bulk_create(plan.new_products)
    if plan.changed_products:
        Product.objects.bulk_update(
            plan.changed_products, ["attributes", "description", "updated_at"]
        )

    variants_to_create = []
    variants_to_update = []
    log_entries = []
    content_type = ContentType.objects.get_for_model(ProductVariant)

    for row_plan in plan.rows:
        row = row_plan.row
        if row_plan.variant is None:
            variants_to_create.append(_build_variant(row_plan))
            continue

        variant = row_plan.variant
        changed = False
        for field_name in VARIANT_VALUE_FIELDS:
            value = getattr(row, field_name)
            if getattr(variant, field_name) != value:
                setattr(variant, field_name, value)
                changed = True
        if not changed:
            continue

        variants_to_update.append(variant)
        entry = build_variant_change_entry(
            operator, variant, row_plan.old_values, content_type=content_type
        )
        if entry is not None:
            log_entries.append(entry)

    if variants_to_create:
        ProductVariant.objects.bulk_create(variants_to_create)
    if variants_to_update:
        ProductVariant.objects.bulk_update(variants_to_update, VARIANT_VALUE_FIELDS)

    if plan.new_collections:
        Collection.objects.bulk_create(plan.new_collections)

    memberships_to_create = _build_memberships(plan)
    if memberships_to_create:
        CollectionProduct.objects.bulk_create(memberships_to_create)

    if log_entries:
        LogEntry.objects.bulk_create(log_entries)


def _build_variant(row_plan):
    row = row_plan.row
    sku = build_sku(
        row.category.sku_code,
        row_plan.design.number,
        row.category.option_schema,
        row.option_values,
    )
    return ProductVariant(
        product=row_plan.product,
        store_id=row_plan.product.store_id,
        sku=normalize_sku(sku),
        option_values=row.option_values,
        price=row.price,
        compare_at_price=row.compare_at_price,
        cost=row.cost,
        weight_grams=row.weight_grams,
        package_length_cm=row.package_length_cm,
        package_width_cm=row.package_width_cm,
        package_height_cm=row.package_height_cm,
        is_active=True,
    )


def _build_memberships(plan):
    next_position = {}
    for membership in plan.memberships:
        current = next_position.get(membership.collection_id, 0)
        next_position[membership.collection_id] = max(current, membership.position)

    memberships = []
    for row_plan in plan.rows:
        for name in row_plan.row.collection_names:
            collection = plan.collections_by_name[name]
            key = (collection.pk, row_plan.product.pk)
            if key in plan.existing_memberships:
                continue
            plan.existing_memberships.add(key)
            position = next_position.get(collection.pk, 0) + 1
            next_position[collection.pk] = position
            memberships.append(
                CollectionProduct(
                    collection=collection,
                    product=row_plan.product,
                    position=position,
                )
            )
    return memberships


def _unique_slug(name, used):
    base = slugify(name)
    if not base:
        raise RowError(f"Cannot build a slug from {name!r}.")
    candidate = base
    number = 2
    while candidate in used:
        candidate = f"{base}-{number}"
        number += 1
    used.add(candidate)
    return candidate
