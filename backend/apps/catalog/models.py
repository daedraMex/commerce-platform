from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Max
from django.db.models.functions import Lower

from apps.catalog.rules import (
    SKU_MAX_LENGTH,
    SLUG_MAX_LENGTH,
    ActiveProduct,
    CatalogRuleError,
    OtherCategory,
    VariantInUse,
    build_sku,
    default_product_name,
    find_sku_conflicts,
    format_design_number,
    normalize_sku,
    slugify,
    validate_attribute_schema,
    validate_attribute_schema_change,
    validate_category_sku_code_change,
    validate_option_schema,
    validate_option_schema_change,
    validate_option_values,
    validate_prices,
    validate_product_attributes,
)
from apps.stores.models import Store
from apps.stores.services import lock_store

DESIGNED_SKU_MESSAGE = (
    "A product with a design generates its SKU; type a SKU only for a product without a design."
)


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
            # Case-insensitive per supplier, as ADR-0015 does for email; save() normalizes spacing.
            models.UniqueConstraint(
                "supplier",
                Lower("supplier_design_name"),
                name="catalog_design_supplier_name_unique",
            ),
        ]

    def __str__(self):
        return f"{self.formatted_number} {self.name}"

    def save(self, *args, **kwargs):
        self._normalize_supplier_design_name()
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
        return format_design_number(self.number)

    def clean(self):
        self._normalize_supplier_design_name()
        self._validate_supplier_store()

    def _normalize_supplier_design_name(self):
        # Trim the ends and collapse inner runs, keeping the text otherwise as typed.
        self.supplier_design_name = " ".join((self.supplier_design_name or "").split())

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
        self._validate_schema_change()
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

    def _validate_schema_change(self):
        if self._state.adding or not self.pk:
            return
        stored = (
            Category.objects.filter(pk=self.pk)
            .values("attribute_schema", "option_schema", "sku_code")
            .first()
        )
        if stored is None:
            return

        variants = [
            VariantInUse(sku=variant.sku, option_values=variant.option_values)
            for variant in ProductVariant.objects.filter(product__category_id=self.pk).only(
                "sku", "option_values"
            )
        ]

        try:
            validate_category_sku_code_change(stored["sku_code"], self.sku_code, variants)
        except CatalogRuleError as error:
            raise ValidationError({"sku_code": str(error)}) from error

        active_products = [
            ActiveProduct(name=product.name, attributes=product.attributes)
            for product in self.products.filter(is_active=True).only("name", "attributes")
        ]
        try:
            validate_attribute_schema_change(
                stored["attribute_schema"], self.attribute_schema, active_products
            )
        except CatalogRuleError as error:
            raise ValidationError({"attribute_schema": str(error)}) from error

        try:
            validate_option_schema_change(stored["option_schema"], self.option_schema, variants)
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


class Product(models.Model):
    """One design in one category, sold in one or more variants."""

    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="products")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    design = models.ForeignKey(
        Design,
        on_delete=models.PROTECT,
        related_name="products",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=200, blank=True)
    slug = models.SlugField(max_length=SLUG_MAX_LENGTH, blank=True)
    description = models.TextField(blank=True)
    attributes = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("store", "name")
        constraints = [
            models.UniqueConstraint(
                fields=("store", "slug"), name="catalog_product_store_slug_unique"
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def clean(self):
        category = self.category if self.category_id else None
        design = self.design if self.design_id else None

        if not self.name:
            self.name = default_product_name(
                category.name if category else "", design.name if design else None
            )
        self.slug = slugify(self.slug or self.name)
        if not self.slug:
            raise ValidationError({"slug": "Add a name that can produce a slug."})

        self._validate_store_links(category, design)
        self._validate_attributes()
        self._validate_immutable_links()

    def _validate_store_links(self, category, design):
        if category is not None and category.store_id != self.store_id:
            raise ValidationError({"category": "The category must belong to the product's store."})
        if design is not None and design.store_id != self.store_id:
            raise ValidationError({"design": "The design must belong to the product's store."})

    def _validate_attributes(self):
        if not self.category_id:
            return
        try:
            validate_product_attributes(self.attributes or {}, self.category.attribute_schema)
        except CatalogRuleError as error:
            raise ValidationError({"attributes": str(error)}) from error

    def _validate_immutable_links(self):
        if self.pk is None or not self.variants.exists():
            return
        stored = Product.objects.filter(pk=self.pk).values("category_id", "design_id").first()
        if stored is None:
            return
        if stored["category_id"] != self.category_id or stored["design_id"] != self.design_id:
            raise ValidationError(
                "A product's category and design cannot change once it has variants."
            )


class Collection(models.Model):
    """A hand-picked, ordered group of products that cuts across categories."""

    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="collections")
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=SLUG_MAX_LENGTH, blank=True)
    description = models.TextField(blank=True)
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name="collections",
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("store", "name")
        constraints = [
            models.UniqueConstraint(
                fields=("store", "slug"), name="catalog_collection_store_slug_unique"
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def clean(self):
        self.slug = slugify(self.slug or self.name)
        if not self.slug:
            raise ValidationError({"slug": "Add a name that can produce a slug."})
        self._validate_supplier_store()

    def _validate_supplier_store(self):
        if not self.store_id or not self.supplier_id:
            return
        if self.supplier.store_id != self.store_id:
            raise ValidationError(
                {"supplier": "The supplier must belong to the collection's store."}
            )


class CollectionProduct(models.Model):
    """One product's ordered place inside a collection."""

    collection = models.ForeignKey(Collection, on_delete=models.PROTECT, related_name="memberships")
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="collection_memberships"
    )
    position = models.PositiveIntegerField()

    class Meta:
        ordering = ("collection", "position", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("collection", "product"),
                name="catalog_collectionproduct_collection_product_unique",
            ),
        ]

    def __str__(self):
        return f"{self.collection} / {self.product}"

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def clean(self):
        if not self.collection_id or not self.product_id:
            return
        if self.product.store_id != self.collection.store_id:
            raise ValidationError({"product": "The product must belong to the collection's store."})


class ProductVariant(models.Model):
    """A purchasable version of a product with an immutable SKU and its prices."""

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="variants")
    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="variants")
    sku = models.CharField(max_length=SKU_MAX_LENGTH, blank=True)
    option_values = models.JSONField(default=dict, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    compare_at_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    cost = models.DecimalField(max_digits=10, decimal_places=2)
    weight_grams = models.PositiveIntegerField(null=True, blank=True)
    package_length_cm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    package_width_cm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    package_height_cm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("product", "sku")
        constraints = [
            models.UniqueConstraint(
                "store",
                Lower("sku"),
                name="catalog_productvariant_store_sku_unique",
            ),
            models.UniqueConstraint(
                fields=("product", "option_values"),
                name="catalog_productvariant_product_options_unique",
            ),
        ]

    def __str__(self):
        return self.sku

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def clean(self):
        if not self.product_id:
            return

        product = self.product
        self._validate_store(product)
        self.option_values = self.option_values or {}

        category = product.category
        try:
            validate_option_values(self.option_values, category.option_schema)
        except CatalogRuleError as error:
            raise ValidationError({"option_values": str(error)}) from error

        self.sku = normalize_sku(self.sku)
        if self._state.adding:
            if product.design_id:
                if self.sku:
                    raise ValidationError({"sku": DESIGNED_SKU_MESSAGE})
                self.sku = build_sku(
                    category.sku_code,
                    product.design.number,
                    category.option_schema,
                    self.option_values,
                )
            elif not self.sku:
                raise ValidationError(
                    {
                        "sku": (
                            "Add a SKU by hand for a product without a design; "
                            "it is generated for products with one."
                        )
                    }
                )
        else:
            self._validate_immutable(product)

        try:
            validate_prices(self.price, self.compare_at_price, self.cost)
        except CatalogRuleError as error:
            raise ValidationError(str(error)) from error

    def _validate_store(self, product):
        if self.store_id is None:
            self.store_id = product.store_id
        elif self.store_id != product.store_id:
            raise ValidationError({"store": "A variant's store must equal its product's store."})

    def _validate_immutable(self, product):
        stored = (
            ProductVariant.objects.filter(pk=self.pk)
            .values("product_id", "sku", "option_values")
            .first()
        )
        if stored is None:
            return
        if stored["product_id"] != self.product_id:
            raise ValidationError({"product": "A variant's product never changes."})
        if stored["sku"] != self.sku:
            raise ValidationError({"sku": "A variant's SKU never changes."})
        if stored["option_values"] != self.option_values:
            raise ValidationError({"option_values": "A variant's option values never change."})

    def validate_unique(self, exclude=None):
        # ModelForm validation uses this; direct saves still let the database constraints do it.
        if self.product_id:
            duplicates = ProductVariant.objects.filter(
                product_id=self.product_id, option_values=self.option_values
            )
            if self.pk is not None:
                duplicates = duplicates.exclude(pk=self.pk)
            if duplicates.exists():
                raise ValidationError(
                    {
                        "option_values": (
                            "A variant of this product already has these option values."
                        )
                    }
                )
        if self.store_id and self.sku:
            duplicates = ProductVariant.objects.filter(store_id=self.store_id, sku__iexact=self.sku)
            if self.pk is not None:
                duplicates = duplicates.exclude(pk=self.pk)
            if duplicates.exists():
                raise ValidationError({"sku": "A variant of this store already has this SKU."})
        super().validate_unique(exclude=exclude)
