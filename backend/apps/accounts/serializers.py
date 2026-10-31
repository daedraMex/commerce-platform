from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


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


class StaffStoreSerializer(serializers.Serializer):
    slug = serializers.CharField()
    name = serializers.CharField()


class StaffMeSerializer(serializers.Serializer):
    store = StaffStoreSerializer()
    role = serializers.CharField(help_text="The role the user holds in this store.")
    permissions = serializers.ListField(
        child=serializers.CharField(),
        help_text="Permission codes the role allows in this store, sorted alphabetically.",
    )
