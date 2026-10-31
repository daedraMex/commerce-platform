from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.accounts.permissions import IsStoreStaff
from apps.accounts.serializers import (
    EmailTokenObtainPairSerializer,
    StaffMeSerializer,
    TokenObtainRequestSerializer,
    TokenPairResponseSerializer,
    TokenRefreshRequestSerializer,
    TokenRefreshResponseSerializer,
)
from apps.accounts.services import get_active_membership
from apps.shared.interfaces.views import StoreScopedMixin
from config.schema import problem_response

TOKEN_PAIR_EXAMPLE = OpenApiExample(
    "Token pair",
    value={
        "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.access",
        "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.refresh",
    },
    response_only=True,
)

ACCESS_TOKEN_EXAMPLE = OpenApiExample(
    "Access token",
    value={"access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.access"},
    response_only=True,
)


def _missing_field_errors(field):
    return [
        {
            "field": field,
            "code": "required",
            "detail": "This field is required.",
        }
    ]


@extend_schema_view(
    post=extend_schema(
        request=TokenObtainRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=TokenPairResponseSerializer,
                description="A new access and refresh token pair.",
                examples=[TOKEN_PAIR_EXAMPLE],
            ),
            **problem_response(
                400,
                (
                    "validation_error",
                    "Validation failed.",
                    _missing_field_errors("password"),
                ),
            ),
            **problem_response(
                401,
                ("invalid_credentials", "Invalid email or password."),
            ),
        },
    )
)
class EmailTokenObtainPairView(TokenObtainPairView):
    serializer_class = EmailTokenObtainPairSerializer


@extend_schema_view(
    post=extend_schema(
        request=TokenRefreshRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=TokenRefreshResponseSerializer,
                description="A new access token.",
                examples=[ACCESS_TOKEN_EXAMPLE],
            ),
            **problem_response(
                400,
                (
                    "validation_error",
                    "Validation failed.",
                    _missing_field_errors("refresh"),
                ),
            ),
            **problem_response(
                401,
                ("token_invalid", "Token is invalid"),
            ),
        },
    )
)
class EmailTokenRefreshView(TokenRefreshView):
    pass


STAFF_ME_EXAMPLE = OpenApiExample(
    "Store admin",
    value={
        "store": {"slug": "home", "name": "Home"},
        "role": "store_admin",
        "permissions": [
            "catalog.manage",
            "inventory.adjust",
            "orders.place_manual",
            "social.approve_post",
        ],
    },
    response_only=True,
)

STORE_HEADER_PARAMETER = OpenApiParameter(
    "X-Store",
    location=OpenApiParameter.HEADER,
    required=True,
    description="Slug of the store the request is scoped to, such as home.",
)


@extend_schema_view(
    get=extend_schema(
        parameters=[STORE_HEADER_PARAMETER],
        responses={
            200: OpenApiResponse(
                response=StaffMeSerializer,
                description="Your role and permissions in the store.",
                examples=[STAFF_ME_EXAMPLE],
            ),
            **problem_response(
                400,
                ("store_header_missing", "The X-Store header is required."),
                ("store_header_invalid", "The X-Store header is not a valid store slug."),
                ("store_not_found", "No active store matches the X-Store header."),
            ),
            **problem_response(
                401,
                ("not_authenticated", "Authentication credentials were not provided."),
                ("token_invalid", "Given token not valid for any token type"),
            ),
            **problem_response(
                403,
                ("permission_denied", IsStoreStaff.message),
            ),
        },
    )
)
class StaffMeView(StoreScopedMixin, APIView):
    store_permission_classes = [IsStoreStaff]

    def get(self, request, *args, **kwargs):
        membership = get_active_membership(user=request.user, store_id=request.store.id)
        data = {
            "store": {"slug": membership.store.slug, "name": membership.store.name},
            "role": membership.role.name,
            "permissions": sorted(
                permission.code for permission in membership.role.permissions.all()
            ),
        }
        return Response(StaffMeSerializer(data).data)
