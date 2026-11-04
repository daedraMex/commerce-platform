from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Max

from apps.catalog.rules import (
    SLUG_MAX_LENGTH,
    CatalogRuleError,
    OtherCategory,
    find_sku_conflicts,
    slugify,
    validate_attribute_schema,
    validate_option_schema,
)
from apps.stores.models import Store
from apps.stores.services import lock_store


class Supplier(models.Model):
    """A business a store buys products from; deactivated and never deleted."""

    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="suppliers")
    name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("store", "name")

    def __str__(self):
        return self.name


class Design(models.Model):
    """An artwork a store sells, numbered once per store and never renumbered."""

    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="designs")
    number = models.PositiveIntegerField(editable=False)
    name = models.CharField(max_length=200)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="designs")
    supplier_design_name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("store", "number")
        constraints = [
            models.UniqueConstraint(
                fields=("store", "number"), name="catalog_design_store_number_unique"
            ),
            models.UniqueConstraint(
                fields=("supplier", "supplier_design_name"),
                name="catalog_design_supplier_name_unique",
            ),
        ]

    def __str__(self):
        return f"{self.formatted_number} {self.name}"

    def save(self, *args, **kwargs):
        self._validate_supplier_store()

        if self._state.adding:
            # The store row is the lock that serializes number assignment for one store.
            with transaction.atomic():
                lock_store(self.store_id)
                last_number = Design.objects.filter(store_id=self.store_id).aggregate(
                    Max("number")
                )["number__max"]
                self.number = (last_number or 0) + 1
                super().save(*args, **kwargs)
            return

        stored_number = Design.objects.filter(pk=self.pk).values_list("number", flat=True).first()
        if stored_number is not None and stored_number != self.number:
            raise ValidationError({"number": "A design number is never edited."})
        super().save(*args, **kwargs)

    @property
    def formatted_number(self):
        if self.number is None:
            return "Assigned on save"
        return f"{self.number:05d}"

    def clean(self):
        self._validate_supplier_store()

    def _validate_supplier_store(self):
        if not self.store_id or not self.supplier_id:
            return
        if self.supplier.store_id != self.store_id:
            raise ValidationError({"supplier": "The supplier must belong to the design's store."})


class Category(models.Model):
    """The type of a product, flat and declaring its attributes and options (ADR-0024)."""

    class Shape(models.TextChoices):
        RECTANGLE = "rectangle", "Rectangle"
        # Contour is an irregular outline; Phase 4b cuts it out of the background.
        CONTOUR = "contour", "Contour"

    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="categories")
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=SLUG_MAX_LENGTH, blank=True)
    sku_code = models.CharField(max_length=20)
    shape = models.CharField(max_length=10, choices=Shape.choices)
    attribute_schema = models.JSONField(default=list, blank=True)
    option_schema = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("store", "name")
        verbose_name_plural = "categories"
        constraints = [
            models.UniqueConstraint(
                fields=("store", "slug"), name="catalog_category_store_slug_unique"
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def clean(self):
        self.sku_code = (self.sku_code or "").strip().upper()
        self._ensure_slug()
        self._validate_schema()
        self._validate_sku_overlap()

    def _ensure_slug(self):
        self.slug = slugify(self.slug or self.name)
        if not self.slug:
            raise ValidationError({"slug": "Add a name that can produce a slug."})

    def _validate_schema(self):
        try:
            validate_attribute_schema(self.attribute_schema)
        except CatalogRuleError as error:
            raise ValidationError({"attribute_schema": str(error)}) from error
        try:
            validate_option_schema(self.option_schema)
        except CatalogRuleError as error:
            raise ValidationError({"option_schema": str(error)}) from error

    def _validate_sku_overlap(self):
        if not self.store_id or not self.sku_code:
            return
        others = (
            Category.objects.filter(store_id=self.store_id, sku_code__iexact=self.sku_code)
            .exclude(pk=self.pk)
            .only("name", "sku_code", "option_schema")
        )
        conflicts = find_sku_conflicts(
            sku_code=self.sku_code,
            option_schema=self.option_schema,
            others=[
                OtherCategory(
                    name=other.name,
                    sku_code=other.sku_code,
                    option_schema=other.option_schema,
                )
                for other in others
            ],
        )
        if not conflicts:
            return

        descriptions = "; ".join(
            f"{conflict.category} ({', '.join(code or 'no options' for code in conflict.codes)})"
            for conflict in conflicts
        )
        raise ValidationError(
            {
                "option_schema": (
                    f"The SKU suffixes overlap with another category of this store: {descriptions}."
                )
            }
        )
