from django.contrib import admin
from django.contrib.admin.apps import AdminConfig


class PlatformAdminSite(admin.AdminSite):
    """Admin site open only to the platform operator, an active superuser (ADR-0012).

    Django model permissions never grant admin access, so store staff cannot use the
    admin to change memberships, roles or feature flags.
    """

    def has_permission(self, request):
        user = request.user
        return user.is_active and user.is_superuser


class PlatformAdminConfig(AdminConfig):
    default_site = "config.admin.PlatformAdminSite"
