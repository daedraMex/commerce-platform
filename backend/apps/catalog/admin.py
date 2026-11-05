import json

from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet

from apps.catalog.models import (
    DESIGNED_SKU_MESSAGE,
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
    normalize_sku,
    validate_option_values,
    validate_prices,
)


class NoDeleteAdmin(admin.ModelAdmin):
    """Catalog rows are deactivated, never deleted."""

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Supplier)
class SupplierAdmin(NoDeleteAdmin):
    list_display = ("name", "store", "is_active")
    list_filter = ("store", "is_active")
    search_fields = ("name",)
    ordering = ("store", "name")


@admin.register(Design)
class DesignAdmin(NoDeleteAdmin):
    list_display = (
        "design_number",
        "name",
        "store",
        "supplier",
        "supplier_design_name",
        "is_active",
    )
    list_filter = ("store", "is_active")
    search_fields = ("name", "supplier_design_name")
    ordering = ("store", "number")
    readonly_fields = ("design_number",)
    fields = (
        "store",
        "design_number",
        "name",
        "supplier",
        "supplier_design_name",
        "is_active",
    )

    @admin.display(description="Number", ordering="number")
    def design_number(self, obj):
        return obj.formatted_number if obj is not None else "Assigned on save"


@admin.register(Category)
class CategoryAdmin(NoDeleteAdmin):
    list_display = ("name", "store", "slug", "sku_code", "shape", "is_active")
    list_filter = ("store", "shape", "is_active")
    search_fields = ("name", "slug", "sku_code")
    ordering = ("store", "name")


class ProductVariantInlineForm(forms.ModelForm):
    class Meta:
        model = ProductVariant
        fields = (
            "sku",
            "option_values",
            "price",
            "compare_at_price",
            "cost",
            "weight_grams",
            "package_length_cm",
            "package_width_cm",
            "package_height_cm",
            "is_active",
        )

    def clean(self):
        cleaned_data = super().clean()
        if {"price", "compare_at_price", "cost"} <= set(cleaned_data):
            try:
                validate_prices(
                    cleaned_data["price"],
                    cleaned_data["compare_at_price"],
                    cleaned_data["cost"],
                )
            except CatalogRuleError as error:
                raise ValidationError(str(error)) from error
        return cleaned_data


class ProductVariantInlineFormSet(BaseInlineFormSet):
    """Lock immutable fields and validate against the parent product's category."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        generates_sku = self._parent_has_design()
        for form in self.forms:
            if form.instance.pk:
                form.fields["sku"].disabled = True
                form.fields["option_values"].disabled = True
            elif generates_sku:
                form.fields["sku"].disabled = True

    @property
    def empty_form(self):
        form = super().empty_form
        if self._parent_has_design():
            form.fields["sku"].disabled = True
        return form

    def _parent_has_design(self):
        if self.instance and self.instance.design_id:
            return True
        # On the add page the parent is not saved yet, so read the submitted design.
        return bool(self.data and self.data.get("design"))

    def clean(self):
        super().clean()
        product = self.instance
        category = product.category if product.category_id else None
        if category is None:
            return

        existing_keys = {}
        if product.pk:
            existing_keys = {
                json.dumps(variant.option_values, sort_keys=True): variant.pk
                for variant in product.variants.all()
            }

        new_keys = set()
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue

            option_values = form.cleaned_data.get("option_values") or {}
            try:
                validate_option_values(option_values, category.option_schema)
            except CatalogRuleError as error:
                form.add_error("option_values", str(error))
                continue

            key = json.dumps(option_values, sort_keys=True)
            own_pk = form.instance.pk
            raw_sku = (self.data.get(form.add_prefix("sku")) if self.data else "") or ""
            if own_pk is None and product.design_id and raw_sku.strip():
                form.add_error("sku", DESIGNED_SKU_MESSAGE)
                continue
            if key in new_keys or (key in existing_keys and existing_keys[key] != own_pk):
                form.add_error(
                    "option_values",
                    "A variant of this product already has these option values.",
                )
                continue
            if own_pk is None:
                new_keys.add(key)

            sku = normalize_sku(form.cleaned_data.get("sku") or "")
            if not product.design_id and not sku:
                form.add_error("sku", "Add a SKU by hand for a product without a design.")
            elif sku:
                duplicates = ProductVariant.objects.filter(
                    store_id=product.store_id, sku__iexact=sku
                )
                if own_pk is not None:
                    duplicates = duplicates.exclude(pk=own_pk)
                if duplicates.exists():
                    form.add_error("sku", "A variant of this store already has this SKU.")


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    form = ProductVariantInlineForm
    formset = ProductVariantInlineFormSet
    extra = 0
    can_delete = False
    fields = (
        "sku",
        "option_values",
        "price",
        "compare_at_price",
        "cost",
        "weight_grams",
        "package_length_cm",
        "package_width_cm",
        "package_height_cm",
        "is_active",
    )

    def has_delete_permission(self, request, obj=None):
        return False


class CollectionProductInlineFormSet(BaseInlineFormSet):
    """Reject products of another store before the parent collection is saved."""

    def clean(self):
        super().clean()
        collection = self.instance
        if not collection.store_id:
            return
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            product = form.cleaned_data.get("product")
            if product is not None and product.store_id != collection.store_id:
                form.add_error("product", "The product must belong to the collection's store.")


class CollectionProductInline(admin.TabularInline):
    model = CollectionProduct
    formset = CollectionProductInlineFormSet
    extra = 0
    fields = ("product", "position")
    ordering = ("position",)
    can_delete = False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Collection)
class CollectionAdmin(NoDeleteAdmin):
    list_display = ("name", "store", "slug", "supplier", "is_active")
    list_filter = ("store", "is_active")
    search_fields = ("name", "slug")
    ordering = ("store", "name")
    fields = ("store", "name", "slug", "description", "supplier", "is_active")
    inlines = (CollectionProductInline,)


@admin.register(Product)
class ProductAdmin(NoDeleteAdmin):
    list_display = ("name", "category", "design", "store", "is_active")
    list_filter = ("store", "category", "is_active")
    search_fields = ("name", "variants__sku", "design__supplier_design_name")
    ordering = ("store", "name")
    readonly_fields = ("created_at", "updated_at")
    fields = (
        "store",
        "category",
        "design",
        "name",
        "slug",
        "description",
        "attributes",
        "is_active",
        "created_at",
        "updated_at",
    )
    inlines = (ProductVariantInline,)

    def get_readonly_fields(self, request, obj=None):
        readonly = list(self.readonly_fields)
        # Its variants' SKUs were generated from these, so they cannot move.
        if obj is not None and obj.pk and obj.variants.exists():
            readonly.extend(["category", "design"])
        return readonly

    def get_search_results(self, request, queryset, search_term):
        results, may_have_duplicates = super().get_search_results(request, queryset, search_term)
        # Design numbers are integers, so let "00012" find design number 12.
        # Both sides keep the changelist filters (store, is_active) already applied.
        term = (search_term or "").strip()
        if term.isdigit():
            results = results | queryset.filter(design__number=int(term))
            may_have_duplicates = True
        return results.distinct(), may_have_duplicates
