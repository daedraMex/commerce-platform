from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from django.urls import include, path
from rest_framework import serializers
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.shared.domain.exceptions import NotFoundError, PermissionDeniedError


class ProtectedView(APIView):
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


class DjangoPermissionView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        raise DjangoPermissionDenied("You cannot do this.")


class DjangoNotFoundView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        raise Http404("Product not found.")


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


urlpatterns = [
    path(
        "api/<str:version>/",
        include(
            [
                path("protected/", ProtectedView.as_view()),
                path("domain-permission/", DomainPermissionView.as_view()),
                path("domain-not-found/", DomainNotFoundView.as_view()),
                path("django-permission/", DjangoPermissionView.as_view()),
                path("django-not-found/", DjangoNotFoundView.as_view()),
                path("validate/", ValidationView.as_view()),
                path("items/", ItemsView.as_view()),
            ]
        ),
    ),
]
