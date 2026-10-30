from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from django.urls import include, path
from drf_spectacular.utils import extend_schema
from drf_spectacular.views import SpectacularAPIView
from rest_framework import serializers
from rest_framework.exceptions import Throttled
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.shared.domain.exceptions import (
    DomainError,
    NotFoundError,
    PermissionDeniedError,
)
from apps.shared.interfaces.views import StoreScopedMixin
from config.schema import problem_response


class ProtectedView(APIView):
    def get(self, request, *args, **kwargs):
        return Response({"status": "ok"})


class GetOnlyView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        return Response({"status": "ok"})


class DomainPermissionView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        raise PermissionDeniedError("You cannot do this.")


class DomainNotFoundView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        raise NotFoundError("Product not found.")


class ProductNotFound(NotFoundError):
    code = "product_not_found"


class ProductNotFoundView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        raise ProductNotFound("Product not found.")


class UnmappedDomainError(DomainError):
    code = "unmapped_domain_error"


class UnmappedDomainView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        raise UnmappedDomainError("Sensitive unmapped detail.")


class ExplodingView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        raise RuntimeError("Sensitive unexpected detail.")


class ThrottledView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        raise Throttled(wait=7)


class DjangoPermissionView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        raise DjangoPermissionDenied("You cannot do this.")


class DjangoNotFoundView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        raise Http404("Product not found.")


class StoreScopedView(StoreScopedMixin, APIView):
    def get(self, request, *args, **kwargs):
        return Response({"slug": request.store.slug})


class NameSerializer(serializers.Serializer):
    name = serializers.CharField()


class ValidationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = NameSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.validated_data)


class ItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()


class ItemsView(ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = ItemSerializer

    def get_queryset(self):
        return [{"id": item_id} for item_id in range(150)]


class ProblemResponseView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(responses=problem_response(404, ("not_found", "Product not found.")))
    def get(self, request, *args, **kwargs):
        return Response({"status": "ok"})


class MultiProblemResponseView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        responses=problem_response(
            401,
            ("not_authenticated", "Authentication credentials were not provided."),
            ("token_invalid", "Given token not valid for any token type."),
        )
    )
    def get(self, request, *args, **kwargs):
        return Response({"status": "ok"})


urlpatterns = [
    path(
        "api/<str:version>/",
        include(
            [
                path(
                    "schema/",
                    SpectacularAPIView.as_view(permission_classes=[AllowAny]),
                ),
                path("protected/", ProtectedView.as_view()),
                path("get-only/", GetOnlyView.as_view()),
                path("domain-permission/", DomainPermissionView.as_view()),
                path("domain-not-found/", DomainNotFoundView.as_view()),
                path("product-not-found/", ProductNotFoundView.as_view()),
                path("domain-unmapped/", UnmappedDomainView.as_view()),
                path("exploding/", ExplodingView.as_view()),
                path("throttled/", ThrottledView.as_view()),
                path("django-permission/", DjangoPermissionView.as_view()),
                path("django-not-found/", DjangoNotFoundView.as_view()),
                path("validate/", ValidationView.as_view()),
                path("items/", ItemsView.as_view()),
                path("store-scoped/", StoreScopedView.as_view()),
                path("problem-response/", ProblemResponseView.as_view()),
                path("multi-problem-response/", MultiProblemResponseView.as_view()),
            ]
        ),
    ),
]
