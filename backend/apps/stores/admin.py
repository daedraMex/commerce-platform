from django.contrib import admin

from apps.stores.models import Store


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "domain", "is_active")
    list_filter = ("is_active",)
    search_fields = ("slug", "name", "domain")
    ordering = ("slug",)

    def has_delete_permission(self, request, obj=None):
        # Stores are deactivated, never deleted.
        return False
