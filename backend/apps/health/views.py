import logging
from concurrent.futures import ThreadPoolExecutor, wait

import psycopg
import redis
from django.conf import settings
from django.db import models
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
READINESS_DEADLINE_SECONDS = 1
SERVICE_UNAVAILABLE_DETAIL = "One or more dependencies are unavailable."


class CheckStatus(models.TextChoices):
    OK = "ok", "ok"
    ERROR = "error", "error"


def check_database():
    """Open a dedicated PostgreSQL connection and run ``SELECT 1``."""
    config = settings.DATABASES["default"]
    options = dict(config.get("OPTIONS") or {})
    options["options"] = " ".join(
        filter(
            None,
            [
                options.get("options"),
                f"-c statement_timeout={STATEMENT_TIMEOUT_MILLISECONDS}",
            ],
        )
    )
    options["connect_timeout"] = CHECK_TIMEOUT_SECONDS

    with psycopg.connect(
        dbname=config["NAME"],
        user=config["USER"],
        password=config["PASSWORD"],
        host=config["HOST"] or None,
        port=config["PORT"] or None,
        **options,
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
        return CheckStatus.ERROR
    return CheckStatus.OK


def _run_checks(checks):
    executor = ThreadPoolExecutor(max_workers=len(checks), thread_name_prefix="readiness-check")
    try:
        futures = {name: executor.submit(_run_check, name, check) for name, check in checks.items()}
        _, pending = wait(futures.values(), timeout=READINESS_DEADLINE_SECONDS)
    finally:
        executor.shutdown(wait=False)

    results = {}
    for name, future in futures.items():
        if future in pending:
            logger.error(
                "Readiness check %r timed out after %s seconds",
                name,
                READINESS_DEADLINE_SECONDS,
            )
            results[name] = CheckStatus.ERROR
        else:
            results[name] = future.result()
    return results


class ReadinessChecksSerializer(serializers.Serializer):
    database = serializers.ChoiceField(choices=CheckStatus.choices)
    redis = serializers.ChoiceField(choices=CheckStatus.choices)


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
        checks = _run_checks(
            {
                "database": check_database,
                "redis": check_redis,
            }
        )
        if all(result == CheckStatus.OK for result in checks.values()):
            return Response({"status": "ok", "checks": checks})

        return problem_details_response(
            503,
            code="service_unavailable",
            detail=SERVICE_UNAVAILABLE_DETAIL,
            extensions={"checks": checks},
        )
