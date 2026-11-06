from __future__ import annotations

from typing import ClassVar

from django.core.cache import cache
from django.db import connection
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.renderers import build_error_envelope


class LiveHealthView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = []
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(auth=[], summary="进程存活检查", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        return Response({"status": "ok", "service": "jianmianliao-api"})


class ReadyHealthView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = []
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        summary="依赖就绪检查",
        responses={200: OpenApiTypes.OBJECT, 503: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request) -> Response:
        checks = {"database": _check_database(), "cache": _check_cache()}
        if all(checks.values()):
            return Response({"status": "ready", "checks": checks})
        return Response(
            build_error_envelope(
                ErrorCode.SERVICE_UNAVAILABLE,
                ERROR_MESSAGES[ErrorCode.SERVICE_UNAVAILABLE],
                checks,
            ),
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


def _check_database() -> bool:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return False
    return True


def _check_cache() -> bool:
    key = "health:ready"
    try:
        cache.set(key, "ok", timeout=5)
        return cache.get(key) == "ok"
    except Exception:
        return False
