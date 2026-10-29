from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.accounts.serializers import (
    EmailTokenObtainPairSerializer,
    TokenObtainRequestSerializer,
    TokenPairResponseSerializer,
    TokenRefreshRequestSerializer,
    TokenRefreshResponseSerializer,
)
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
