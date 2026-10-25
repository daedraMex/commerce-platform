from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
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

MISSING_PASSWORD_EXAMPLE = [
    {
        "field": "password",
        "code": "required",
        "detail": "This field is required.",
    }
]

MISSING_REFRESH_EXAMPLE = [
    {
        "field": "refresh",
        "code": "required",
        "detail": "This field is required.",
    }
]


class EmailTokenObtainPairView(TokenObtainPairView):
    serializer_class = EmailTokenObtainPairSerializer

    @extend_schema(
        request=TokenObtainRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=TokenPairResponseSerializer,
                description="A new access and refresh token pair.",
                examples=[TOKEN_PAIR_EXAMPLE],
            ),
            **problem_response(
                400,
                ("validation_error", "Validation failed.", MISSING_PASSWORD_EXAMPLE),
            ),
            **problem_response(
                401,
                ("invalid_credentials", "Invalid email or password."),
            ),
        },
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class EmailTokenRefreshView(TokenRefreshView):
    @extend_schema(
        request=TokenRefreshRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=TokenRefreshResponseSerializer,
                description="A new access token.",
                examples=[ACCESS_TOKEN_EXAMPLE],
            ),
            **problem_response(
                400,
                ("validation_error", "Validation failed.", MISSING_REFRESH_EXAMPLE),
            ),
            **problem_response(
                401,
                ("token_invalid", "Given token not valid for any token type."),
            ),
        },
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)
