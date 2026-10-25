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

from config.schema import problem_response


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
            **problem_response(500, "internal_error", "An unexpected error occurred."),
        }
    )
    def get(self, request, *args, **kwargs):
        return Response({"status": "ok"})
