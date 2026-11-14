"""分享链接、邀请码和新用户一级邀请归因业务服务。"""

from __future__ import annotations

import secrets
import uuid
from typing import Any
from urllib.parse import quote, urljoin, urlparse

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import HttpRequest
from django.utils import timezone

from backend.accounts.models import User
from backend.common.crypto import sensitive_fingerprint
from backend.common.errors import ErrorCode
from backend.common.exceptions import ApiError
from backend.referrals.models import (
    ReferralAttribution,
    ReferralInviteCode,
    ReferralShareLink,
    ReferralVisit,
)

INVITE_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _invalid(field: str, message: str) -> ApiError:
    """构造分享推广参数校验异常。"""
    return ApiError(ErrorCode.REFERRAL_INVALID, message, status_code=400, details={"field": field})


def _not_found(message: str = "分享推广记录不存在") -> ApiError:
    """构造分享推广记录不存在异常。"""
    return ApiError(ErrorCode.REFERRAL_NOT_FOUND, message, status_code=404)


def _fingerprint(payload: dict[str, Any]) -> str:
    """计算写请求一致性摘要。"""
    return sensitive_fingerprint(payload)


def _hash(value: str | None, kind: str) -> str:
    """将访问标识转换为不可逆摘要，不保存原始设备号或 IP。"""
    normalized = (value or "").strip()
    return _fingerprint({kind: normalized}) if normalized else ""


def _request_hashes(request: HttpRequest | None, visitor_id: str | None) -> tuple[str, str, str]:
    """返回访问者、IP 和 User-Agent 的安全摘要。"""
    if request is None:
        return _hash(visitor_id, "visitor_id"), "", ""
    return (
        _hash(visitor_id, "visitor_id"),
        _hash(request.META.get("REMOTE_ADDR", ""), "ip"),
        _hash(request.META.get("HTTP_USER_AGENT", ""), "user_agent"),
    )


def _normalize_context(payload: dict[str, Any] | None) -> dict[str, str]:
    """规范化注册归因上下文。"""
    payload = payload or {}
    invite_code = str(payload.get("invite_code") or "").strip().upper()
    share_no = str(payload.get("share_no") or payload.get("share_id") or "").strip()
    channel = str(payload.get("channel") or "").strip().upper()
    campaign_code = str(payload.get("campaign_code") or "").strip()
    visitor_id = str(payload.get("visitor_id") or "").strip()
    if len(invite_code) > 16:
        raise _invalid("referral_context.invite_code", "邀请码长度不能超过 16 个字符")
    if len(channel) > 32 or len(campaign_code) > 64 or len(visitor_id) > 128:
        raise _invalid("referral_context", "归因上下文字段长度不正确")
    try:
        share_uuid = uuid.UUID(share_no) if share_no else None
    except ValueError as exc:
        raise _invalid("referral_context.share_no", "分享链接标识格式不正确") from exc
    return {
        "invite_code": invite_code,
        "share_no": str(share_uuid) if share_uuid else "",
        "channel": channel,
        "campaign_code": campaign_code,
        "visitor_id": visitor_id,
    }


def get_or_create_invite_code(*, user: User) -> ReferralInviteCode:
    """为用户幂等生成唯一专属邀请码。"""
    existing = ReferralInviteCode.objects.filter(user=user).first()
    if existing:
        return existing
    for _ in range(10):
        code = "".join(secrets.choice(INVITE_CODE_ALPHABET) for _ in range(8))
        try:
            with transaction.atomic():
                return ReferralInviteCode.objects.create(user=user, code=code)
        except IntegrityError:
            continue
    raise ApiError(ErrorCode.REFERRAL_INVALID, "邀请码生成失败，请稍后重试", status_code=500)


def build_share_url(*, user: User, share_link: ReferralShareLink) -> str:
    """生成携带邀请码和分享链接标识的公开主页链接。"""
    base_url = str(settings.PUBLIC_SHARE_BASE_URL).strip()
    parsed = urlparse(base_url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise _invalid("PUBLIC_SHARE_BASE_URL", "分享域名必须是完整 HTTP 或 HTTPS 地址")
    base = base_url.rstrip("/") + "/"
    query = (
        f"?invite_code={quote(share_link.invite_code.code)}"
        f"&share_no={quote(str(share_link.share_no))}"
        f"&channel={quote(share_link.channel)}"
    )
    return urljoin(base, "invite/") + query


def share_link_payload(link: ReferralShareLink, share_url: str) -> dict[str, Any]:
    """返回分享链接安全摘要。"""
    return {
        "share_no": str(link.share_no),
        "invite_code": link.invite_code.code,
        "channel": link.channel,
        "campaign_code": link.campaign_code,
        "status": link.status,
        "share_url": share_url,
        "created_at": link.created_at,
        "expires_at": link.expires_at,
    }


def create_share_link(
    *,
    user: User,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """按渠道和活动生成分享链接并支持幂等。"""
    channel = str(payload.get("channel") or "").strip().upper()
    campaign_code = str(payload.get("campaign_code") or "").strip()
    if channel not in ReferralShareLink.Channel.values:
        raise _invalid("channel", "分享渠道不存在")
    if len(campaign_code) > 64:
        raise _invalid("campaign_code", "活动代码长度不能超过 64 个字符")
    normalized_key = (idempotency_key or "").strip()
    if len(normalized_key) > 128:
        raise _invalid("Idempotency-Key", "幂等键长度不能超过 128 个字符")
    invite_code = get_or_create_invite_code(user=user)
    fingerprint = _fingerprint(
        {"invite_code": invite_code.code, "channel": channel, "campaign_code": campaign_code}
    )
    try:
        with transaction.atomic():
            link = ReferralShareLink.objects.create(
                invite_code=invite_code,
                user=user,
                channel=channel,
                campaign_code=campaign_code,
                idempotency_key=normalized_key,
                request_fingerprint=fingerprint,
            )
    except IntegrityError as exc:
        link = ReferralShareLink.objects.filter(user=user, idempotency_key=normalized_key).first()
        if not normalized_key or not link or link.request_fingerprint != fingerprint:
            raise ApiError(
                ErrorCode.REFERRAL_INVALID,
                "分享链接幂等请求与原请求不一致",
                status_code=409,
            ) from exc
    return share_link_payload(link, build_share_url(user=user, share_link=link))


def get_or_create_profile_share_link(*, user: User) -> ReferralShareLink:
    """获取个人海报使用的稳定分享链接。"""
    invite_code = get_or_create_invite_code(user=user)
    fingerprint = _fingerprint(
        {
            "invite_code": invite_code.code,
            "channel": ReferralShareLink.Channel.POSTER,
            "campaign_code": "PROFILE_POSTER",
        }
    )
    link, _ = ReferralShareLink.objects.get_or_create(
        user=user,
        idempotency_key="profile-poster",
        defaults={
            "invite_code": invite_code,
            "channel": ReferralShareLink.Channel.POSTER,
            "campaign_code": "PROFILE_POSTER",
            "request_fingerprint": fingerprint,
        },
    )
    return link


def record_referral_visit(
    *,
    payload: dict[str, Any],
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """记录匿名分享访问，不执行邀请绑定。"""
    share_no = str(payload.get("share_no") or payload.get("share_id") or "").strip()
    invite_code_value = str(payload.get("invite_code") or "").strip().upper()
    visitor_id = str(payload.get("visitor_id") or "").strip()
    if not share_no and not invite_code_value:
        raise _invalid("share_no", "share_no 和 invite_code 至少填写一个")
    query = ReferralShareLink.objects.filter(status=ReferralShareLink.Status.ACTIVE)
    if share_no:
        try:
            query = query.filter(share_no=uuid.UUID(share_no))
        except ValueError as exc:
            raise _invalid("share_no", "分享链接标识格式不正确") from exc
    else:
        query = query.filter(invite_code__code=invite_code_value).order_by("-created_at")
    link = query.select_related("invite_code").first()
    if link is None:
        raise _not_found("分享链接不存在或已停用")
    visitor_hash, ip_hash, user_agent_hash = _request_hashes(request, visitor_id)
    visit = ReferralVisit.objects.create(
        share_link=link,
        visitor_hash=visitor_hash,
        ip_hash=ip_hash,
        user_agent_hash=user_agent_hash,
    )
    return {
        "visit_no": str(visit.visit_no),
        "share_no": str(link.share_no),
        "invite_code": link.invite_code.code,
        "occurred_at": visit.occurred_at,
    }


def bind_new_user_referral(
    *,
    user: User,
    context: dict[str, Any] | None,
    registration_source: str,
    is_new_user: bool,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """仅在新用户注册流程中绑定唯一直接邀请人。"""
    normalized = _normalize_context(context)
    if not normalized["invite_code"]:
        return {"status": "NOT_REQUESTED"}
    if not is_new_user:
        return {"status": "EXISTING_USER"}
    if registration_source not in ReferralAttribution.RegistrationSource.values:
        raise _invalid("registration_source", "注册来源不存在")
    existing = ReferralAttribution.objects.filter(invitee_user=user).first()
    if existing:
        return {
            "status": "ALREADY_BOUND"
            if existing.invite_code.code == normalized["invite_code"]
            else "CONFLICT",
            "inviter_user_id": existing.inviter_user_id,
        }
    invite_code = (
        ReferralInviteCode.objects.select_related("user")
        .filter(code=normalized["invite_code"], status=ReferralInviteCode.Status.ACTIVE)
        .first()
    )
    if invite_code is None:
        return {"status": "INVALID_CODE"}
    if invite_code.user_id == user.id:
        return {"status": "SELF_INVITE"}
    if invite_code.user.status != User.Status.ACTIVE:
        return {"status": "INVITER_UNAVAILABLE"}
    share_link = None
    if normalized["share_no"]:
        share_link = ReferralShareLink.objects.filter(
            share_no=normalized["share_no"],
            invite_code=invite_code,
            status=ReferralShareLink.Status.ACTIVE,
        ).first()
    visitor_hash, ip_hash, _ = _request_hashes(request, normalized["visitor_id"])
    risk_status = ReferralAttribution.RiskStatus.CLEAR
    risk_reason = ""
    if visitor_hash and ReferralAttribution.objects.filter(visitor_hash=visitor_hash).exists():
        risk_status = ReferralAttribution.RiskStatus.REVIEW
        risk_reason = "同一访问设备关联多个注册归因"
    try:
        with transaction.atomic():
            attribution = ReferralAttribution.objects.create(
                invitee_user=user,
                inviter_user=invite_code.user,
                invite_code=invite_code,
                share_link=share_link,
                registration_source=registration_source,
                source_channel=normalized["channel"] or (share_link.channel if share_link else ""),
                campaign_code=normalized["campaign_code"]
                or (share_link.campaign_code if share_link else ""),
                visitor_hash=visitor_hash,
                ip_hash=ip_hash,
                risk_status=risk_status,
                risk_reason=risk_reason,
            )
            if share_link and visitor_hash:
                ReferralVisit.objects.filter(
                    share_link=share_link,
                    visitor_hash=visitor_hash,
                    converted_at__isnull=True,
                ).update(converted_at=timezone.now(), converted_user=user)
    except IntegrityError as exc:
        raise ApiError(
            ErrorCode.REFERRAL_BINDING_CONFLICT,
            "邀请归因已绑定或存在冲突",
            status_code=409,
        ) from exc
    return {
        "status": "BOUND_WITH_RISK_REVIEW"
        if risk_status != ReferralAttribution.RiskStatus.CLEAR
        else "BOUND",
        "inviter_user_id": attribution.inviter_user_id,
        "risk_status": attribution.risk_status,
    }
