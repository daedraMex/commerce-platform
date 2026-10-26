"""OpenAPI declarations shared by every endpoint."""

from http import HTTPStatus

from drf_spectacular.utils import OpenApiExample, OpenApiResponse
from rest_framework import serializers

PROBLEM_MEDIA_TYPE = "application/problem+json"


class FieldErrorSerializer(serializers.Serializer):
    field = serializers.CharField()
    code = serializers.CharField()
    detail = serializers.CharField()


class ProblemDetailsSerializer(serializers.Serializer):
    type = serializers.CharField()
    title = serializers.CharField()
    status = serializers.IntegerField()
    detail = serializers.CharField()
    code = serializers.CharField()
    errors = FieldErrorSerializer(many=True, required=False)


def problem_response(status, code, detail):
    """Build an ``extend_schema`` responses entry for one problem details error."""
    return {
        (status, PROBLEM_MEDIA_TYPE): OpenApiResponse(
            response=ProblemDetailsSerializer,
            description=detail,
            examples=[
                OpenApiExample(
                    code,
                    value={
                        "type": "about:blank",
                        "title": _title_for(status),
                        "status": status,
                        "detail": detail,
                        "code": code,
                    },
                    response_only=True,
                    media_type=PROBLEM_MEDIA_TYPE,
                )
            ],
        )
    }


def _title_for(status):
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "Error"
