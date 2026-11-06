"""媒体上传、图片安全规范化、引用校验和私有读取业务服务。"""

from __future__ import annotations

import hashlib
import hmac
import io
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError

from backend.accounts.models import User
from backend.common.crypto import sensitive_fingerprint
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.media.models import MediaAsset
from backend.media.storage import build_storage_key, delete, open_bytes, save_bytes

ALLOWED_IMAGE_FORMATS = {
    "JPEG": {"content_type": "image/jpeg", "extension": "jpg"},
    "PNG": {"content_type": "image/png", "extension": "png"},
    "WEBP": {"content_type": "image/webp", "extension": "webp"},
}
PROVIDER_APPLICATION_AVATAR = MediaAsset.Purpose.PROVIDER_APPLICATION_AVATAR
PROVIDER_APPLICATION_LIFE_PHOTO = MediaAsset.Purpose.PROVIDER_APPLICATION_LIFE_PHOTO
USER_PROFILE_AVATAR = MediaAsset.Purpose.USER_PROFILE_AVATAR
PROVIDER_PROFILE_AVATAR = MediaAsset.Purpose.PROVIDER_PROFILE_AVATAR
PROVIDER_PROFILE_PHOTO = MediaAsset.Purpose.PROVIDER_PROFILE_PHOTO
PROVIDER_SERVICE_COVER = MediaAsset.Purpose.PROVIDER_SERVICE_COVER
PROVIDER_SERVICE_GALLERY = MediaAsset.Purpose.PROVIDER_SERVICE_GALLERY
MOMENT_IMAGE = MediaAsset.Purpose.MOMENT_IMAGE


@dataclass(frozen=True)
class NormalizedImage:
    """经过格式、尺寸和元数据安全处理后的图片数据。"""

    data: bytes
    content_type: str
    extension: str
    width: int
    height: int
    sha256: str


@dataclass(frozen=True)
class UploadResult:
    """媒体上传结果，区分首次创建和幂等/内容去重重用。"""

    asset: MediaAsset
    reused: bool


def normalize_image(data: bytes) -> NormalizedImage:
    """解码并重新编码图片，移除 EXIF 等元数据并执行上传限制。"""
    if not data:
        raise _upload_error("文件不能为空")
    if len(data) > settings.MEDIA_MAX_UPLOAD_BYTES:
        raise ApiError(
            ErrorCode.MEDIA_UPLOAD_TOO_LARGE,
            ERROR_MESSAGES[ErrorCode.MEDIA_UPLOAD_TOO_LARGE],
            status_code=413,
        )

    Image.MAX_IMAGE_PIXELS = settings.MEDIA_MAX_IMAGE_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as source:
            image_format = source.format
            if image_format not in ALLOWED_IMAGE_FORMATS:
                raise _upload_error("仅支持 JPEG、PNG 和 WebP 图片")
            if getattr(source, "n_frames", 1) != 1:
                raise _upload_error("暂不支持动态图片")
            source.load()
            image = ImageOps.exif_transpose(source)
            width, height = image.size
            _validate_dimensions(width, height)
            normalized_data = _encode_image(image, image_format)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise _upload_error("图片文件无效或无法安全解析") from exc

    if len(normalized_data) > settings.MEDIA_MAX_UPLOAD_BYTES:
        raise ApiError(
            ErrorCode.MEDIA_UPLOAD_TOO_LARGE,
            ERROR_MESSAGES[ErrorCode.MEDIA_UPLOAD_TOO_LARGE],
            status_code=413,
        )
    format_info = ALLOWED_IMAGE_FORMATS[image_format]
    return NormalizedImage(
        data=normalized_data,
        content_type=format_info["content_type"],
        extension=format_info["extension"],
        width=width,
        height=height,
        sha256=hashlib.sha256(normalized_data).hexdigest(),
    )


def _validate_dimensions(width: int, height: int) -> None:
    if width < settings.MEDIA_MIN_IMAGE_DIMENSION or height < settings.MEDIA_MIN_IMAGE_DIMENSION:
        raise _upload_error(f"图片宽高不能小于 {settings.MEDIA_MIN_IMAGE_DIMENSION} 像素")
    if width > settings.MEDIA_MAX_IMAGE_DIMENSION or height > settings.MEDIA_MAX_IMAGE_DIMENSION:
        raise _upload_error(f"图片宽高不能大于 {settings.MEDIA_MAX_IMAGE_DIMENSION} 像素")
    if width * height > settings.MEDIA_MAX_IMAGE_PIXELS:
        raise _upload_error("图片像素总量超过限制")


def _encode_image(image: Image.Image, image_format: str) -> bytes:
    output = io.BytesIO()
    if image_format == "JPEG":
        image.convert("RGB").save(output, format="JPEG", quality=90, optimize=True)
    elif image_format == "PNG":
        image.save(output, format="PNG", optimize=True)
    else:
        webp_image = image if image.mode in {"RGB", "RGBA"} else image.convert("RGBA")
        webp_image.save(output, format="WEBP", quality=90, method=4)
    return output.getvalue()


def _upload_error(message: str) -> ApiError:
    return ApiError(
        ErrorCode.MEDIA_UPLOAD_INVALID,
        ERROR_MESSAGES[ErrorCode.MEDIA_UPLOAD_INVALID],
        status_code=400,
        details={"file": message},
    )


def _normalize_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    key = value.strip()
    if not key or len(key) > 128:
        raise ApiError(
            ErrorCode.MEDIA_IDEMPOTENCY_CONFLICT,
            "Idempotency-Key 长度必须在 1 到 128 之间",
            status_code=400,
        )
    return key


def _display_signature(media_id: str, expires_at: int, key_version: str) -> str:
    message = f"display:{media_id}:{expires_at}:{key_version}".encode()
    return hmac.new(
        settings.MEDIA_URL_SIGNING_KEY.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()


def sign_media_display_path(media_id: str, *, expires_at: int | None = None) -> str:
    """生成短期展示地址的路径和查询参数，不校验资源归属。"""

    now = int(time.time())
    expires_at = (
        expires_at if expires_at is not None else now + settings.MEDIA_DISPLAY_URL_TTL_SECONDS
    )
    key_version = settings.MEDIA_URL_SIGNING_KEY_VERSION
    signature = _display_signature(media_id, expires_at, key_version)
    query = urlencode(
        {
            "expires": expires_at,
            "key_version": key_version,
            "signature": signature,
        }
    )
    return f"{reverse('v1:media-display', args=[media_id])}?{query}"


def _display_path_with_reuse(media_id: str) -> tuple[str, datetime]:
    now = int(time.time())
    key_version = settings.MEDIA_URL_SIGNING_KEY_VERSION
    cache_key = f"media:display-url:{key_version}:{media_id}"
    cached = cache.get(cache_key)
    refresh_after = settings.MEDIA_DISPLAY_URL_REFRESH_BUFFER_SECONDS
    if (
        isinstance(cached, dict)
        and cached.get("key_version") == key_version
        and cached.get("expires_at", 0) > now + refresh_after
    ):
        return cached["path"], datetime.fromtimestamp(cached["expires_at"], tz=UTC)

    expires_at = now + settings.MEDIA_DISPLAY_URL_TTL_SECONDS
    path = sign_media_display_path(media_id, expires_at=expires_at)
    cache.set(
        cache_key,
        {"path": path, "expires_at": expires_at, "key_version": key_version},
        timeout=max(1, settings.MEDIA_DISPLAY_URL_TTL_SECONDS - refresh_after),
    )
    return path, datetime.fromtimestamp(expires_at, tz=UTC)


def validate_media_display_token(
    *,
    media_id: str,
    expires_at: str,
    key_version: str,
    signature: str,
) -> MediaAsset:
    """校验短期展示地址签名和有效期，并返回可读取的媒体。"""

    if key_version != settings.MEDIA_URL_SIGNING_KEY_VERSION:
        raise ApiError(
            ErrorCode.MEDIA_URL_INVALID,
            ERROR_MESSAGES[ErrorCode.MEDIA_URL_INVALID],
            status_code=403,
        )
    try:
        expires = int(expires_at)
    except (TypeError, ValueError):
        raise ApiError(
            ErrorCode.MEDIA_URL_INVALID,
            ERROR_MESSAGES[ErrorCode.MEDIA_URL_INVALID],
            status_code=403,
        ) from None
    expected_signature = _display_signature(media_id, expires, key_version)
    if not hmac.compare_digest(signature, expected_signature):
        raise ApiError(
            ErrorCode.MEDIA_URL_INVALID,
            ERROR_MESSAGES[ErrorCode.MEDIA_URL_INVALID],
            status_code=403,
        )
    if expires <= int(time.time()):
        raise ApiError(
            ErrorCode.MEDIA_URL_EXPIRED,
            ERROR_MESSAGES[ErrorCode.MEDIA_URL_EXPIRED],
            status_code=410,
        )
    try:
        return MediaAsset.objects.get(
            public_id=media_id,
            status=MediaAsset.Status.AVAILABLE,
        )
    except (MediaAsset.DoesNotExist, ValueError):
        raise ApiError(
            ErrorCode.MEDIA_NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.MEDIA_NOT_FOUND],
            status_code=404,
        ) from None


def upload_image(
    *,
    user: User,
    purpose: str,
    data: bytes,
    idempotency_key: str | None = None,
) -> UploadResult:
    """上传图片并按用户、用途、幂等键和内容摘要去重。"""
    if purpose not in MediaAsset.Purpose.values:
        raise _upload_error("媒体用途不正确")
    normalized_key = _normalize_idempotency_key(idempotency_key)
    image = normalize_image(data)
    fingerprint = sensitive_fingerprint({"purpose": purpose, "sha256": image.sha256})

    if normalized_key:
        existing = MediaAsset.objects.filter(
            owner=user,
            idempotency_key=normalized_key,
        ).first()
        if existing:
            if existing.request_fingerprint != fingerprint:
                raise ApiError(
                    ErrorCode.MEDIA_IDEMPOTENCY_CONFLICT,
                    ERROR_MESSAGES[ErrorCode.MEDIA_IDEMPOTENCY_CONFLICT],
                    status_code=409,
                )
            return UploadResult(existing, reused=True)

    existing_content = MediaAsset.objects.filter(
        owner=user,
        purpose=purpose,
        sha256=image.sha256,
        status=MediaAsset.Status.AVAILABLE,
    ).first()
    if existing_content:
        return UploadResult(existing_content, reused=True)

    storage_key = build_storage_key(purpose=purpose, extension=image.extension)
    saved_key: str | None = None
    try:
        with transaction.atomic():
            asset = MediaAsset.objects.create(
                owner=user,
                purpose=purpose,
                storage_key=storage_key,
                content_type=image.content_type,
                extension=image.extension,
                byte_size=len(image.data),
                width=image.width,
                height=image.height,
                sha256=image.sha256,
                idempotency_key=normalized_key,
                request_fingerprint=fingerprint,
            )
            saved_key = save_bytes(storage_key, image.data)
            if saved_key != storage_key:
                asset.storage_key = saved_key
                asset.save(update_fields=["storage_key"])
            return UploadResult(asset, reused=False)
    except IntegrityError as exc:
        if saved_key:
            delete(saved_key)
        if normalized_key:
            existing = MediaAsset.objects.filter(
                owner=user,
                idempotency_key=normalized_key,
            ).first()
            if existing and existing.request_fingerprint == fingerprint:
                return UploadResult(existing, reused=True)
        existing_content = MediaAsset.objects.filter(
            owner=user,
            purpose=purpose,
            sha256=image.sha256,
            status=MediaAsset.Status.AVAILABLE,
        ).first()
        if existing_content:
            return UploadResult(existing_content, reused=True)
        raise ApiError(
            ErrorCode.MEDIA_UPLOAD_INVALID,
            ERROR_MESSAGES[ErrorCode.MEDIA_UPLOAD_INVALID],
            status_code=409,
        ) from exc


def get_available_media(
    *,
    user: User,
    purpose: str,
    media_ids: list[str],
) -> list[MediaAsset]:
    """校验媒体属于当前用户、用途正确且状态可用，并保持输入顺序。"""
    if not media_ids:
        return []
    assets = {
        str(asset.public_id): asset
        for asset in MediaAsset.objects.filter(
            owner=user,
            purpose=purpose,
            status=MediaAsset.Status.AVAILABLE,
            public_id__in=media_ids,
        )
    }
    if len(assets) != len(set(media_ids)):
        raise ApiError(
            ErrorCode.MEDIA_NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.MEDIA_NOT_FOUND],
            status_code=400,
            details={"media_ids": "媒体不存在、不属于当前用户或用途不正确"},
        )
    return [assets[media_id] for media_id in media_ids]


def get_available_media_for_purposes(
    *,
    user: User,
    purposes: set[str],
    media_ids: list[str],
) -> list[MediaAsset]:
    """校验媒体属于当前用户，并允许兼容多个已确认媒体用途。"""

    if not media_ids:
        return []
    assets = {
        str(asset.public_id): asset
        for asset in MediaAsset.objects.filter(
            owner=user,
            purpose__in=purposes,
            status=MediaAsset.Status.AVAILABLE,
            public_id__in=media_ids,
        )
    }
    if len(assets) != len(set(media_ids)):
        raise ApiError(
            ErrorCode.MEDIA_NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.MEDIA_NOT_FOUND],
            status_code=400,
            details={"media_ids": "媒体不存在、不属于当前用户或用途不正确"},
        )
    return [assets[media_id] for media_id in media_ids]


def mark_media_referenced(media_ids: list[str]) -> None:
    """记录业务引用时间，为后续孤儿媒体清理提供依据。"""
    if media_ids:
        MediaAsset.objects.filter(public_id__in=media_ids).update(last_referenced_at=timezone.now())


def get_accessible_media(*, viewer: User, media_id: str) -> MediaAsset:
    """按媒体所有者或管理员权限读取私有媒体元数据。"""
    try:
        asset = MediaAsset.objects.get(
            public_id=media_id,
            status=MediaAsset.Status.AVAILABLE,
        )
    except (MediaAsset.DoesNotExist, ValueError):
        raise ApiError(
            ErrorCode.MEDIA_NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.MEDIA_NOT_FOUND],
            status_code=404,
        ) from None
    if asset.owner_id != viewer.id and not viewer.is_staff:
        raise ApiError(
            ErrorCode.MEDIA_ACCESS_DENIED,
            ERROR_MESSAGES[ErrorCode.MEDIA_ACCESS_DENIED],
            status_code=403,
        )
    return asset


def open_media(asset: MediaAsset):
    """打开媒体文件内容，供受控内容接口返回。"""
    return open_bytes(asset.storage_key)


def media_payload(asset: MediaAsset, request: HttpRequest | None = None) -> dict[str, Any]:
    """生成不含存储路径和敏感信息的媒体响应。"""
    display_path, display_expires_at = _display_path_with_reuse(str(asset.public_id))
    display_url = request.build_absolute_uri(display_path) if request is not None else display_path
    return {
        "media_id": str(asset.public_id),
        "purpose": asset.purpose,
        "content_type": asset.content_type,
        "byte_size": asset.byte_size,
        "width": asset.width,
        "height": asset.height,
        "content_url": reverse("v1:media-content", args=[asset.public_id]),
        "display_url": display_url,
        "display_url_expires_at": display_expires_at,
        "created_at": asset.created_at,
    }


def get_media_payloads(
    media_ids: list[str],
    request: HttpRequest | None = None,
) -> list[dict[str, Any]]:
    """按输入媒体 ID 顺序返回安全媒体摘要。"""
    assets = MediaAsset.objects.filter(
        public_id__in=media_ids,
        status=MediaAsset.Status.AVAILABLE,
    )
    payloads = {str(asset.public_id): media_payload(asset, request) for asset in assets}
    return [payloads[media_id] for media_id in media_ids if media_id in payloads]


def get_recent_media_payloads(
    media_ids: list[str],
    request: HttpRequest | None = None,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """按创建时间倒序返回最近媒体摘要，自动去重并限制数量。"""

    unique_ids = list(dict.fromkeys(media_ids))
    if not unique_ids or limit <= 0:
        return []
    assets = list(
        MediaAsset.objects.filter(
            public_id__in=unique_ids,
            status=MediaAsset.Status.AVAILABLE,
        ).order_by("-created_at", "-id")[:limit]
    )
    return [media_payload(asset, request) for asset in assets]
