from django.urls import include, path, re_path
from drf_spectacular.utils import extend_schema
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny


@extend_schema(exclude=True)
@api_view(["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
@permission_classes([AllowAny])
def api_not_found(request, *args, **kwargs):
    raise NotFound("No resource matches this route.")


urlpatterns = [
    path(
        "schema/",
        SpectacularAPIView.as_view(permission_classes=[AllowAny]),
        name="schema",
    ),
    path(
        "docs/",
        SpectacularSwaggerView.as_view(permission_classes=[AllowAny]),
        name="docs",
    ),
    path("health/", include("apps.health.urls")),
    re_path(r"^.*$", api_not_found),
]
