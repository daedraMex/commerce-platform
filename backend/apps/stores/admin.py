from django.contrib import admin

from apps.stores.models import Store, StoreFeatureFlag


class StoreFeatureFlagInline(admin.TabularInline):
    """The only place flags change: the platform operator turns them on or off per store.

    The platform operator is the superuser (ADR-0012), so Django permissions never grant access.
    """

    model = StoreFeatureFlag
    extra = 0

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "domain", "whatsapp_number", "accent_color", "is_active")
    list_filter = ("is_active",)
    search_fields = ("slug", "name", "domain", "whatsapp_number")
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
