from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/<str:version>/", include("config.api_urls")),
]

if (
    settings.DEBUG
    and settings.STORAGES["default"]["BACKEND"] == "django.core.files.storage.FileSystemStorage"
):
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
