from __future__ import annotations

from typing import ClassVar

from drf_spectacular.utils import extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.accounts.authentication import BearerTokenAuthentication
from backend.profiles.api.serializers import (
    CityOptionResponseSerializer,
    InterestTagResponseSerializer,
    ProfileResponseSerializer,
    ProfileSummaryResponseSerializer,
    ProfileUpdateRequestSerializer,
    ProfileUpdateResponseSerializer,
)
from backend.profiles.services import (
    city_payloads,
    interest_tag_payloads,
    profile_payload,
    profile_summary,
    update_profile,
)


class ProfileView(APIView):
    """当前用户个人资料查询和修改接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询当前用户个人资料",
        responses={200: ProfileResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(profile_payload(request.user, request))

    @extend_schema(
        summary="修改当前用户个人资料",
        description="支持局部修改；使用 expected_version 防止并发覆盖，相同内容重复提交不改变版本。",
        request=ProfileUpdateRequestSerializer,
        responses={200: ProfileUpdateResponseSerializer},
    )
    def patch(self, request: Request) -> Response:
        serializer = ProfileUpdateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        expected_version = payload.pop("expected_version")
        result = update_profile(
            user=request.user,
            payload=payload,
            expected_version=expected_version,
        )
        return Response(
            {
                **profile_payload(request.user, request),
                "changed": result.changed,
            }
        )


class ProfileSummaryView(APIView):
    """我的页面订单、收藏和关注数量查询接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="获取我的页面数量汇总",
        operation_id="getProfileSummary",
        responses={200: ProfileSummaryResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(profile_summary(request.user))


class InterestTagOptionsView(APIView):
    """查询可选兴趣标签配置。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = []
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        summary="获取可选兴趣标签",
        responses={200: InterestTagResponseSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        return Response(interest_tag_payloads())


class CityOptionsView(APIView):
    """查询可选城市代码配置。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = []
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        summary="获取可选城市代码",
        responses={200: CityOptionResponseSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        return Response(city_payloads())
