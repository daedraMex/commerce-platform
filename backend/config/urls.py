from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path

from apps.catalog.labels import label_redirect

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/<str:version>/", include("config.api_urls")),
]

if (
    settings.DEBUG
    and settings.STORAGES["default"]["BACKEND"] == "django.core.files.storage.FileSystemStorage"
):
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Frozen label links (ADR-0035) live at the root, not under the versioned API.
# Reserved prefixes keep the route from swallowing media, static files, the admin or the API.
urlpatterns += [
    re_path(
        r"^(?!media/|static/|admin/|api/)"
        r"(?P<store_slug>[a-z0-9]+(?:-[a-z0-9]+)*)/(?P<sku>[^/]+)$",
        label_redirect,
        name="label-redirect",
    ),
]
