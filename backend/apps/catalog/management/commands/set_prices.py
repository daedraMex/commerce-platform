from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.catalog.management.support import (
    PRICE_FIELDS,
    record_variant_change,
    resolve_operator,
    snapshot,
)
from apps.catalog.models import Category, ProductVariant
from apps.catalog.rules import CatalogRuleError, validate_prices
from apps.stores.models import Store


@dataclass(frozen=True)
class Targets:
    price: Decimal
    compare_at_price: Decimal | None = None
    set_compare_at_price: bool = False
    cost: Decimal = Decimal("0")
    set_cost: bool = False


class Command(BaseCommand):
    help = "Reprice every variant of a category and option value in one step."

    def add_arguments(self, parser):
        parser.add_argument("--store", required=True, help="Store slug.")
        parser.add_argument("--category", required=True, help="Category slug.")
        parser.add_argument("--option-value", help="Option value code, such as MAT.")
        parser.add_argument("--price", required=True)
        compare = parser.add_mutually_exclusive_group()
        compare.add_argument("--compare-at-price")
        compare.add_argument("--clear-compare-at-price", action="store_true")
        parser.add_argument("--cost")
        parser.add_argument("--operator", required=True, help="Email of an active superuser.")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        operator = resolve_operator(options["operator"])
        with transaction.atomic():
            store = _get_store(options["store"])
            category = _get_category(store, options["category"])
            option_value = _option_value(category, options.get("option_value"))
            matches = _matching_variants(category, option_value)
            targets = _targets(options)
            _validate_targets(targets)

            changed = _apply(matches, targets, operator=operator, dry_run=options["dry_run"])
            report = _report(matches, changed)
            if options["dry_run"]:
                report += "Dry run: no prices or log entries were written.\n"
            self.stdout.write(report)


def _get_store(slug):
    try:
        store = Store.objects.get(slug=slug)
    except Store.DoesNotExist as error:
        raise CommandError(f"No store with slug {slug!r}.") from error
    if not store.is_active:
        raise CommandError(f"Store {slug!r} is inactive.")
    return store


def _get_category(store, slug):
    try:
        return Category.objects.get(store=store, slug=slug)
    except Category.DoesNotExist as error:
        raise CommandError(f"No category with slug {slug!r} in store {store.slug!r}.") from error


def _option_value(category, option_value):
    if not category.option_schema:
        return None
    if not option_value:
        raise CommandError(f"The category {category.slug!r} has options; pass --option-value.")
    valid_codes = {value["code"] for option in category.option_schema for value in option["values"]}
    if option_value not in valid_codes:
        raise CommandError(f"The category {category.slug!r} has no option value {option_value!r}.")
    return option_value


def _matching_variants(category, option_value):
    variants = ProductVariant.objects.select_related("product").filter(product__category=category)
    if option_value is None:
        return list(variants)
    return [
        variant for variant in variants if option_value in (variant.option_values or {}).values()
    ]


def _targets(options):
    set_compare_at_price = (
        options["clear_compare_at_price"] or options["compare_at_price"] is not None
    )
    compare_at_price = None
    if not options["clear_compare_at_price"] and options["compare_at_price"] is not None:
        compare_at_price = _decimal(options["compare_at_price"], "compare-at price")

    set_cost = options["cost"] is not None
    cost = _decimal(options["cost"], "cost") if set_cost else Decimal("0")

    return Targets(
        price=_decimal(options["price"], "price"),
        compare_at_price=compare_at_price,
        set_compare_at_price=set_compare_at_price,
        cost=cost,
        set_cost=set_cost,
    )


def _decimal(value, name):
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise CommandError(f"The {name} must be a number, not {value!r}.") from error
    if not number.is_finite():
        raise CommandError(f"The {name} must be a finite number, not {value!r}.")
    try:
        if number != number.quantize(Decimal("0.01")):
            raise CommandError(f"The {name} must have at most two decimal places.")
    except InvalidOperation as error:
        raise CommandError(f"The {name} is out of range.") from error
    return number


def _validate_targets(targets):
    # Validate the price once even when nothing matches; the per-variant check adds the rest.
    compare_at_price = targets.compare_at_price if targets.set_compare_at_price else None
    cost = targets.cost if targets.set_cost else Decimal("0")
    _check_prices(targets.price, compare_at_price, cost)


def _check_prices(price, compare_at_price, cost):
    try:
        validate_prices(price, compare_at_price, cost)
    except CatalogRuleError as error:
        raise CommandError(str(error)) from error


def _apply(matches, targets, *, operator, dry_run):
    changed = []
    for variant in matches:
        compare_at_price = _compare_for(variant, targets)
        cost = _cost_for(variant, targets)
        _check_prices(targets.price, compare_at_price, cost)

        if _already_at(variant, targets):
            continue
        changed.append(variant)
        if dry_run:
            continue

        old_values = snapshot(variant, PRICE_FIELDS)
        variant.price = targets.price
        fields = ["price"]
        if targets.set_compare_at_price:
            variant.compare_at_price = compare_at_price
            fields.append("compare_at_price")
        if targets.set_cost:
            variant.cost = cost
            fields.append("cost")
        variant.save(update_fields=fields)
        record_variant_change(operator, variant, old_values)
    return changed


def _compare_for(variant, targets):
    if targets.set_compare_at_price:
        return targets.compare_at_price
    return variant.compare_at_price


def _cost_for(variant, targets):
    if targets.set_cost:
        return targets.cost
    return variant.cost


def _already_at(variant, targets):
    if variant.price != targets.price:
        return False
    if targets.set_compare_at_price and variant.compare_at_price != targets.compare_at_price:
        return False
    if targets.set_cost and variant.cost != targets.cost:
        return False
    return True


def _report(matched, changed):
    active = sum(1 for variant in matched if variant.is_active)
    inactive = len(matched) - active
    return (
        f"Matched active variants: {active}\n"
        f"Matched inactive variants: {inactive}\n"
        f"Already at these prices: {len(matched) - len(changed)}\n"
        f"Changed variants: {len(changed)}\n"
    )
