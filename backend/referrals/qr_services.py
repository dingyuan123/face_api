"""分享主页二维码生成、短期签名地址和图片读取服务。"""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

import qrcode
from django.conf import settings
from django.http import HttpRequest
from django.urls import reverse

from backend.common.errors import ErrorCode
from backend.common.exceptions import ApiError
from backend.referrals.models import ReferralShareLink
from backend.referrals.services import build_share_url


def _qr_signature(share_no: str, expires_at: int, key_version: str) -> str:
    """计算二维码图片短期地址签名。"""
    message = f"referral-qr:{share_no}:{expires_at}:{key_version}".encode()
    return hmac.new(
        settings.MEDIA_URL_SIGNING_KEY.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()


def ensure_referral_qr_image(*, share_no: str, profile_url: str) -> Path:
    """生成或复用分享主页二维码 PNG 文件。"""
    directory = Path(settings.MEDIA_ROOT) / "referral_qr"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{share_no}.png"
    fingerprint_path = directory / f"{share_no}.url.sha256"
    fingerprint = hashlib.sha256(profile_url.encode("utf-8")).hexdigest()
    if path.exists() and fingerprint_path.exists():
        try:
            if fingerprint_path.read_text(encoding="ascii").strip() == fingerprint:
                return path
        except OSError:
            pass
    image = qrcode.make(
        profile_url,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    image.save(path, format="PNG")
    fingerprint_path.write_text(fingerprint, encoding="ascii")
    return path


def build_referral_qr_image_url(
    *,
    user,
    share_link: ReferralShareLink,
    request: HttpRequest | None = None,
) -> tuple[str, str]:
    """返回二维码图片短期地址和过期时间。"""
    share_no = str(share_link.share_no)
    profile_url = build_share_url(user=user, share_link=share_link)
    ensure_referral_qr_image(share_no=share_no, profile_url=profile_url)
    expires_at = int(time.time()) + settings.MEDIA_DISPLAY_URL_TTL_SECONDS
    key_version = settings.MEDIA_URL_SIGNING_KEY_VERSION
    query = urlencode(
        {
            "expires": expires_at,
            "key_version": key_version,
            "signature": _qr_signature(share_no, expires_at, key_version),
        }
    )
    path = f"{reverse('v1:referral-qr', args=[share_no])}?{query}"
    expires_display = datetime.fromtimestamp(expires_at, tz=UTC)
    return (
        request.build_absolute_uri(path) if request is not None else path,
        expires_display.strftime("%Y-%m-%d %H:%M:%S"),
    )


def validate_referral_qr_token(
    *,
    share_no: str,
    expires_at: str,
    key_version: str,
    signature: str,
) -> Path:
    """校验二维码图片签名并返回本地 PNG 文件。"""
    if key_version != settings.MEDIA_URL_SIGNING_KEY_VERSION:
        raise ApiError(ErrorCode.MEDIA_URL_INVALID, "二维码地址无效", status_code=403)
    try:
        expires = int(expires_at)
    except (TypeError, ValueError) as exc:
        raise ApiError(ErrorCode.MEDIA_URL_INVALID, "二维码地址无效", status_code=403) from exc
    expected = _qr_signature(share_no, expires, key_version)
    if not hmac.compare_digest(signature, expected):
        raise ApiError(ErrorCode.MEDIA_URL_INVALID, "二维码地址无效", status_code=403)
    if expires <= int(time.time()):
        raise ApiError(ErrorCode.MEDIA_URL_EXPIRED, "二维码地址已过期", status_code=410)
    try:
        share_uuid = uuid.UUID(share_no)
    except ValueError as exc:
        raise ApiError(ErrorCode.NOT_FOUND, "二维码图片不存在", status_code=404) from exc
    if not ReferralShareLink.objects.filter(
        share_no=share_uuid,
        status=ReferralShareLink.Status.ACTIVE,
    ).exists():
        raise ApiError(ErrorCode.NOT_FOUND, "二维码图片不存在", status_code=404)
    link = (
        ReferralShareLink.objects.select_related("user", "invite_code")
        .filter(share_no=share_uuid)
        .first()
    )
    if link is None:
        raise ApiError(ErrorCode.NOT_FOUND, "二维码图片不存在", status_code=404)
    return ensure_referral_qr_image(
        share_no=share_no,
        profile_url=build_share_url(user=link.user, share_link=link),
    )
