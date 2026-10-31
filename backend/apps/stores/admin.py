from django.contrib import admin

from apps.stores.models import Store, StoreFeatureFlag


class StoreFeatureFlagInline(admin.TabularInline):
    # The only place flags change: the platform operator toggles them per store (ADR-0013).
    model = StoreFeatureFlag
    extra = 0


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "domain", "is_active")
    list_filter = ("is_active",)
    search_fields = ("slug", "name", "domain")
    ordering = ("slug",)
    inlines = (StoreFeatureFlagInline,)

    def get_readonly_fields(self, request, obj=None):
        # Clients address a store by its slug, so renaming it would silently break them.
        if obj is not None:
            return ("slug",)
        return ()

    def has_delete_permission(self, request, obj=None):
        # Stores are deactivated, never deleted.
        return False
