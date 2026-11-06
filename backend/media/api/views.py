from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.http import FileResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.accounts.authentication import BearerTokenAuthentication
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.media.api.serializers import (
    MediaAssetResponseSerializer,
    MediaUploadRequestSerializer,
)
from backend.media.services import (
    get_accessible_media,
    media_payload,
    open_media,
    upload_image,
    validate_media_display_token,
)


class MediaUploadView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]
    parser_classes: ClassVar[list[type]] = [MultiPartParser, FormParser]

    @extend_schema(
        summary="上传服务者申请图片",
        description=(
            "开发阶段保存到服务端本地存储并移除图片 EXIF; 后续可通过存储适配器切换到 OSS/COS。"
        ),
        request=MediaUploadRequestSerializer,
        responses={200: MediaAssetResponseSerializer, 201: MediaAssetResponseSerializer},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                location=OpenApiParameter.HEADER,
                type=str,
                required=False,
                description="重复上传同一文件时使用的幂等键。",
            )
        ],
    )
    def post(self, request: Request) -> Response:
        serializer = MediaUploadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        uploaded = serializer.validated_data["file"]
        if uploaded.size > settings.MEDIA_MAX_UPLOAD_BYTES:
            raise ApiError(
                ErrorCode.MEDIA_UPLOAD_TOO_LARGE,
                ERROR_MESSAGES[ErrorCode.MEDIA_UPLOAD_TOO_LARGE],
                status_code=413,
            )
        result = upload_image(
            user=request.user,
            purpose=serializer.validated_data["purpose"],
            data=uploaded.read(),
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        payload = {**media_payload(result.asset, request), "reused": result.reused}
        return Response(payload, status=200 if result.reused else 201)


class MediaContentView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="读取本人或管理端可访问的媒体文件",
        auth=[{"BearerTokenAuth": []}],
        responses={200: OpenApiTypes.BINARY},
    )
    def get(self, request: Request, media_id: str) -> FileResponse:
        asset = get_accessible_media(viewer=request.user, media_id=media_id)
        response = FileResponse(
            open_media(asset),
            content_type=asset.content_type,
            filename=f"{asset.public_id}.{asset.extension}",
            as_attachment=False,
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class MediaDisplayView(APIView):
    """无 Authorization 的短期签名图片展示接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = []
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        summary="加载短期签名媒体图片",
        description="签名有效期内可重复加载；签名错误返回 403，过期返回 410。",
        responses={200: OpenApiTypes.BINARY},
        parameters=[
            OpenApiParameter(
                "expires",
                location=OpenApiParameter.QUERY,
                type=int,
                required=True,
                description="签名过期时间，Unix 秒",
            ),
            OpenApiParameter(
                "key_version",
                location=OpenApiParameter.QUERY,
                type=str,
                required=True,
                description="签名密钥版本",
            ),
            OpenApiParameter(
                "signature",
                location=OpenApiParameter.QUERY,
                type=str,
                required=True,
                description="服务端生成的短期访问签名",
            ),
        ],
    )
    def get(self, request: Request, media_id: str) -> FileResponse:
        asset = validate_media_display_token(
            media_id=media_id,
            expires_at=request.query_params.get("expires", ""),
            key_version=request.query_params.get("key_version", ""),
            signature=request.query_params.get("signature", ""),
        )
        response = FileResponse(
            open_media(asset),
            content_type=asset.content_type,
            filename=f"{asset.public_id}.{asset.extension}",
            as_attachment=False,
        )
        response["Cache-Control"] = "private, max-age=300"
        response["X-Content-Type-Options"] = "nosniff"
        return response
