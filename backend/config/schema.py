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


def problem_response(status, *examples):
    """Build an ``extend_schema`` responses entry for problem details errors.

    Each example is a ``(code, detail)`` pair, or ``(code, detail, errors)`` to
    show the validation ``errors`` list. Several examples may share one status,
    so a 401 can document both ``not_authenticated`` and ``token_invalid``.
    """
    rendered = []
    descriptions = []
    for example in examples:
        if not isinstance(example, tuple) or len(example) not in (2, 3):
            raise TypeError("Each example must be a (code, detail[, errors]) tuple.")
        code, detail, *rest = example
        value = {
            "type": "about:blank",
            "title": _title_for(status),
            "status": status,
            "detail": detail,
            "code": code,
        }
        if rest:
            value["errors"] = rest[0]
        rendered.append(
            OpenApiExample(
                code,
                value=value,
                response_only=True,
                media_type=PROBLEM_MEDIA_TYPE,
            )
        )
        descriptions.append(detail)

    return {
        (status, PROBLEM_MEDIA_TYPE): OpenApiResponse(
            response=ProblemDetailsSerializer,
            description=" ".join(descriptions),
            examples=rendered,
        )
    }


def _title_for(status):
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "Error"
