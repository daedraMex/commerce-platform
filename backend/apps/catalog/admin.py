from django.contrib import admin

from apps.catalog.models import Category, Design, Supplier


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
    readonly_fields = ("slug",)
