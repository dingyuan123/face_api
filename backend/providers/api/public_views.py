from __future__ import annotations

from typing import ClassVar

from drf_spectacular.utils import extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.accounts.authentication import BearerTokenAuthentication
from backend.providers.api.public_serializers import ProviderPublicResponseSerializer
from backend.providers.public_services import provider_public_payload


class PublicProviderProfileView(APIView):
    """首页卡片点击后的公开服务者资料页。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        summary="查看公开服务者资料",
        responses={200: ProviderPublicResponseSerializer},
    )
    def get(self, request: Request, provider_public_id: str) -> Response:
        return Response(
            provider_public_payload(
                provider_public_id=provider_public_id,
                viewer=request.user if request.user.is_authenticated else None,
                request=request,
            )
        )
