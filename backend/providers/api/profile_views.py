from __future__ import annotations

from typing import ClassVar

from drf_spectacular.utils import extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.accounts.authentication import BearerTokenAuthentication
from backend.providers.api.profile_serializers import (
    ProviderProfileInputSerializer,
    ProviderProfileResponseSerializer,
    ProviderProfileUpdateResponseSerializer,
)
from backend.providers.profile_services import (
    provider_profile_payload,
    update_provider_profile,
)


class ProviderProfileView(APIView):
    """服务者资料查询和修改接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询当前服务者资料",
        responses={200: ProviderProfileResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(provider_profile_payload(request.user, request))

    @extend_schema(
        summary="修改当前服务者资料",
        description="支持创建和局部修改；使用 expected_version 防止并发覆盖。",
        request=ProviderProfileInputSerializer,
        responses={200: ProviderProfileUpdateResponseSerializer},
    )
    def patch(self, request: Request) -> Response:
        serializer = ProviderProfileInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        expected_version = payload.pop("expected_version")
        result = update_provider_profile(
            user=request.user,
            payload=payload,
            expected_version=expected_version,
        )
        return Response(
            {
                **provider_profile_payload(request.user, request),
                "changed": result.changed,
            }
        )
