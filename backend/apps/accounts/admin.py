from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group
from django.utils.translation import gettext_lazy as _

from apps.accounts.forms import EmailUserChangeForm, EmailUserCreationForm
from apps.accounts.models import Permission, Role, StoreMembership, User
from apps.stores.admin import StoreAdmin
from apps.stores.models import Store

# Store roles replace Django groups; showing both invites confusing one for the other.
admin.site.unregister(Group)


class StoreMembershipInline(admin.TabularInline):
    model = StoreMembership
    extra = 0


class ReadOnlyAdmin(admin.ModelAdmin):
    """The matrix changes only through data migrations (ADR-0021), never by hand."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Permission)
class PermissionAdmin(ReadOnlyAdmin):
    list_display = ("code", "description")


@admin.register(Role)
class RoleAdmin(ReadOnlyAdmin):
    list_display = ("name",)


# stores never imports accounts, so the membership inline is attached to the Store admin here.
admin.site.unregister(Store)


@admin.register(Store)
class StoreWithMembershipsAdmin(StoreAdmin):
    inlines = (StoreMembershipInline,)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = EmailUserChangeForm
    add_form = EmailUserCreationForm

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Personal info"), {"fields": ("first_name", "last_name")}),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2"),
            },
        ),
    )
    list_display = ("email", "first_name", "last_name", "is_staff", "is_active")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("email",)
    inlines = (StoreMembershipInline,)
