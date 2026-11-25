"""普通用户可见的公司简介和营业执照查询接口。"""

from __future__ import annotations

from typing import ClassVar

from drf_spectacular.utils import extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.adminops.api.serializers import PublicCompanyProfileResponseSerializer
from backend.adminops.company_services import get_public_company_profile


class PublicCompanyProfileView(APIView):
    """无需登录即可查询公开的公司简介和营业执照。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = []
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        summary="查询公开公司简介和营业执照",
        description=(
            "返回公司全称、公司简介和营业执照短期图片地址；不返回管理员、"
            "版本、存储路径或账户敏感信息。"
        ),
        responses={200: PublicCompanyProfileResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(get_public_company_profile(request))
