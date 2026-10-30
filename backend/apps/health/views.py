import logging

import psycopg
import redis
from django.conf import settings
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiResponse,
    extend_schema,
    inline_serializer,
)
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from config.exceptions import problem_details_response
from config.schema import PROBLEM_MEDIA_TYPE, ProblemDetailsSerializer, problem_response

logger = logging.getLogger(__name__)

CHECK_TIMEOUT_SECONDS = 1
STATEMENT_TIMEOUT_MILLISECONDS = CHECK_TIMEOUT_SECONDS * 1000
SERVICE_UNAVAILABLE_DETAIL = "One or more dependencies are unavailable."


def check_database():
    """Open a dedicated PostgreSQL connection and run ``SELECT 1``."""
    config = settings.DATABASES["default"]
    with psycopg.connect(
        dbname=config["NAME"],
        user=config["USER"],
        password=config["PASSWORD"],
        host=config["HOST"] or None,
        port=config["PORT"] or None,
        connect_timeout=CHECK_TIMEOUT_SECONDS,
        options=f"-c statement_timeout={STATEMENT_TIMEOUT_MILLISECONDS}",
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")


def check_redis():
    """Ping Redis through a client with its own socket timeouts."""
    client = redis.Redis.from_url(
        settings.REDIS_URL,
        socket_connect_timeout=CHECK_TIMEOUT_SECONDS,
        socket_timeout=CHECK_TIMEOUT_SECONDS,
    )
    try:
        client.ping()
    finally:
        client.close()


def _run_check(name, check):
    try:
        check()
    except Exception:
        logger.exception("Readiness check %r failed", name)
        return "error"
    return "ok"


class ReadinessChecksSerializer(serializers.Serializer):
    database = serializers.ChoiceField(choices=("ok", "error"))
    redis = serializers.ChoiceField(choices=("ok", "error"))


class ReadinessProblemDetailsSerializer(ProblemDetailsSerializer):
    checks = ReadinessChecksSerializer()


class LivenessView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        responses={
            200: OpenApiResponse(
                response=inline_serializer(
                    name="LivenessResponse",
                    fields={"status": serializers.CharField()},
                ),
                description="The API process is running.",
                examples=[
                    OpenApiExample(
                        "Liveness success",
                        value={"status": "ok"},
                        response_only=True,
                    )
                ],
            ),
            **problem_response(500, ("internal_error", "An unexpected error occurred.")),
        }
    )
    def get(self, request, *args, **kwargs):
        return Response({"status": "ok"})


class ReadinessView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        responses={
            200: OpenApiResponse(
                response=inline_serializer(
                    name="ReadinessResponse",
                    fields={
                        "status": serializers.CharField(),
                        "checks": ReadinessChecksSerializer(),
                    },
                ),
                description="PostgreSQL and Redis are reachable.",
                examples=[
                    OpenApiExample(
                        "Readiness success",
                        value={
                            "status": "ok",
                            "checks": {"database": "ok", "redis": "ok"},
                        },
                        response_only=True,
                    )
                ],
            ),
            (503, PROBLEM_MEDIA_TYPE): OpenApiResponse(
                response=ReadinessProblemDetailsSerializer,
                description=SERVICE_UNAVAILABLE_DETAIL,
                examples=[
                    OpenApiExample(
                        "service_unavailable",
                        value={
                            "type": "about:blank",
                            "title": "Service Unavailable",
                            "status": 503,
                            "detail": SERVICE_UNAVAILABLE_DETAIL,
                            "code": "service_unavailable",
                            "checks": {"database": "error", "redis": "ok"},
                        },
                        response_only=True,
                        media_type=PROBLEM_MEDIA_TYPE,
                    )
                ],
            ),
        }
    )
    def get(self, request, *args, **kwargs):
        checks = {
            "database": _run_check("database", check_database),
            "redis": _run_check("redis", check_redis),
        }
        if all(result == "ok" for result in checks.values()):
            return Response({"status": "ok", "checks": checks})

        return problem_details_response(
            503,
            code="service_unavailable",
            detail=SERVICE_UNAVAILABLE_DETAIL,
            extra={"checks": checks},
        )
