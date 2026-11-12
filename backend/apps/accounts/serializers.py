from django.core.exceptions import ObjectDoesNotExist
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer


class InvalidCredentials(AuthenticationFailed):
    default_detail = "Invalid email or password."
    default_code = "invalid_credentials"


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Authenticates by email and reports every credential failure the same way."""

    def validate(self, attrs):
        try:
            return super().validate(attrs)
        except AuthenticationFailed as exc:
            raise InvalidCredentials() from exc


class RefreshTokenInvalid(InvalidToken):
    """One answer for every unusable refresh token, so callers cannot tell why it failed."""

    default_detail = "Token is invalid"


class RotatingTokenRefreshSerializer(TokenRefreshSerializer):
    """Rotates the refresh token, and reports a blacklisted, expired or malformed token,
    or one whose user is inactive or gone, the same way."""

    def validate(self, attrs):
        try:
            return super().validate(attrs)
        except (TokenError, AuthenticationFailed, ObjectDoesNotExist) as exc:
            raise RefreshTokenInvalid() from exc


class TokenObtainRequestSerializer(serializers.Serializer):
    email = serializers.CharField(help_text="Email address, matched ignoring case.")
    password = serializers.CharField(write_only=True)


class TokenRefreshRequestSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class TokenPairResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()


class TokenRefreshResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField(
        help_text="Replaces the refresh token sent, which can no longer be used."
    )


class LogoutRequestSerializer(serializers.Serializer):
    refresh = serializers.CharField(help_text="Your refresh token to invalidate.")


class MeUserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    email = serializers.EmailField()


class MeStoreSerializer(serializers.Serializer):
    slug = serializers.CharField()
    name = serializers.CharField()
    accent_color = serializers.CharField(
        help_text="Six-digit hex color the console uses for this store."
    )


class MeMembershipSerializer(serializers.Serializer):
    store = MeStoreSerializer()
    role = serializers.CharField(help_text="The role the user holds in this store.")
    permissions = serializers.ListField(
        child=serializers.CharField(),
        help_text="Permission codes the role allows in this store, sorted alphabetically.",
    )


class MeSerializer(serializers.Serializer):
    user = MeUserSerializer()
    memberships = MeMembershipSerializer(
        many=True,
        help_text="Every store where the user has an active membership.",
    )
