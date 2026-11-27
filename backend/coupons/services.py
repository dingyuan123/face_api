"""优惠券发放、领取、订单试算、锁定、核销、释放和管理员维护服务。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from backend.common.context import current_trace_id
from backend.common.crypto import sensitive_fingerprint
from backend.common.display import enum_label
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.coupons.models import (
    CouponInstance,
    CouponRedemption,
    CouponStatusLog,
    CouponTemplate,
)


def _invalid(field: str, message: str) -> ApiError:
    """返回优惠券参数或状态校验错误。"""
    return ApiError(
        ErrorCode.COUPON_INVALID,
        message,
        status_code=400,
        details={field: message},
    )


def _conflict(message: str, *, code: ErrorCode = ErrorCode.COUPON_STATE_INVALID) -> ApiError:
    """返回优惠券并发、幂等或状态冲突错误。"""
    return ApiError(code, message, status_code=409)


def _not_found() -> ApiError:
    """返回优惠券不存在错误。"""
    return ApiError(
        ErrorCode.COUPON_NOT_FOUND,
        ERROR_MESSAGES[ErrorCode.COUPON_NOT_FOUND],
        status_code=404,
    )


def _normalize_idempotency_key(value: str | None, prefix: str) -> str:
    """规范化业务幂等键，未提供时生成不与用户请求冲突的自动键。"""
    if value is None:
        return f"auto:{prefix}:{uuid.uuid4()}"
    key = value.strip()
    if not key or len(key) > 128:
        raise _invalid("idempotency_key", "幂等键长度必须在 1 到 128 之间")
    return key


@dataclass(slots=True)
class CouponScopeContext:
    """订单优惠券适用范围的服务端事实摘要。"""

    city_code: str = ""
    category_code: str = ""
    service_public_id: str = ""
    provider_public_id: str = ""


def _template_snapshot(template: CouponTemplate) -> dict[str, Any]:
    """生成写入用户券和订单核销记录的模板规则快照。"""
    return {
        "template_no": str(template.template_no),
        "code": template.code,
        "name": template.name,
        "discount_type": template.discount_type,
        "currency": template.currency,
        "discount_amount_minor": template.discount_amount_minor,
        "min_spend_amount_minor": template.min_spend_amount_minor,
        "scope_type": template.scope_type,
        "scope_value": template.scope_value,
        "validity_type": template.validity_type,
        "validity_days": template.validity_days,
    }


def coupon_payload(coupon: CouponInstance) -> dict[str, Any]:
    """返回用户优惠券安全展示信息和使用条件。"""
    now = timezone.now()
    effective_status = coupon.status
    if coupon.status == CouponInstance.Status.AVAILABLE and coupon.valid_to <= now:
        effective_status = CouponInstance.Status.EXPIRED
    snapshot = coupon.template_snapshot or _template_snapshot(coupon.template)
    return {
        "coupon_no": str(coupon.coupon_no),
        "template_no": snapshot.get("template_no", str(coupon.template.template_no)),
        "code": snapshot.get("code", coupon.template.code),
        "name": snapshot.get("name", coupon.template.name),
        "status": effective_status,
        "status_text": enum_label(CouponInstance.Status, effective_status),
        "currency": snapshot.get("currency", coupon.template.currency),
        "discount_amount_minor": snapshot.get(
            "discount_amount_minor",
            coupon.template.discount_amount_minor,
        ),
        "min_spend_amount_minor": snapshot.get(
            "min_spend_amount_minor",
            coupon.template.min_spend_amount_minor,
        ),
        "scope_type": snapshot.get("scope_type", coupon.template.scope_type),
        "scope_type_text": enum_label(
            CouponTemplate.ScopeType,
            snapshot.get("scope_type", coupon.template.scope_type),
        ),
        "scope_value": snapshot.get("scope_value", coupon.template.scope_value),
        "valid_from": coupon.valid_from,
        "valid_to": coupon.valid_to,
        "source_type": coupon.source_type,
        "source_type_text": enum_label(CouponInstance.SourceType, coupon.source_type),
        "issued_at": coupon.issued_at,
        "used_at": coupon.used_at,
        "revoked_at": coupon.revoked_at,
        "version": coupon.version,
    }


def redemption_payload(redemption: CouponRedemption) -> dict[str, Any]:
    """返回优惠券订单核销记录和金额快照。"""
    return {
        "redemption_no": str(redemption.redemption_no),
        "coupon_no": str(redemption.coupon.coupon_no),
        "coupon_name": redemption.template_snapshot.get("name", redemption.coupon.template.name),
        "order_no": redemption.order_no,
        "status": redemption.status,
        "status_text": enum_label(CouponRedemption.Status, redemption.status),
        "currency": redemption.currency,
        "original_amount_minor": redemption.original_amount_minor,
        "discount_amount_minor": redemption.discount_amount_minor,
        "payable_amount_minor": redemption.payable_amount_minor,
        "reserved_at": redemption.reserved_at,
        "used_at": redemption.used_at,
        "released_at": redemption.released_at,
    }


def _log_status(
    *,
    coupon: CouponInstance,
    event_type: str,
    from_status: str,
    to_status: str,
    reason: str = "",
    redemption: CouponRedemption | None = None,
    operator_user_id: int | None = None,
    idempotency_key: str = "",
) -> None:
    """在当前事务内追加优惠券状态审计记录。"""
    CouponStatusLog.objects.create(
        coupon=coupon,
        redemption=redemption,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        reason=reason[:500],
        operator_user_id=operator_user_id,
        idempotency_key=idempotency_key[:128],
        trace_id=current_trace_id(),
    )


def _expire_coupon(coupon: CouponInstance) -> None:
    """将已到期且未锁定的用户券逻辑标记为过期。"""
    if coupon.status != CouponInstance.Status.AVAILABLE:
        return
    if coupon.valid_to > timezone.now():
        return
    previous_status = coupon.status
    coupon.status = CouponInstance.Status.EXPIRED
    coupon.version += 1
    coupon.save(update_fields=["status", "version", "updated_at"])
    _log_status(
        coupon=coupon,
        event_type=CouponStatusLog.EventType.EXPIRED,
        from_status=previous_status,
        to_status=coupon.status,
        reason="优惠券有效期届满",
    )


def list_user_coupons(
    *,
    user,
    status: str = "AVAILABLE",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """分页查询当前用户可用、已使用、已过期或全部优惠券。"""
    normalized_status = (status or "AVAILABLE").upper()
    allowed = {"AVAILABLE", "USED", "EXPIRED", "ALL"}
    if normalized_status not in allowed:
        raise _invalid("status", "优惠券状态筛选不存在")
    now = timezone.now()
    CouponInstance.objects.filter(
        user=user,
        status=CouponInstance.Status.AVAILABLE,
        valid_to__lte=now,
    ).update(
        status=CouponInstance.Status.EXPIRED,
        updated_at=now,
    )
    queryset = CouponInstance.objects.select_related("template").filter(user=user)
    if normalized_status == "AVAILABLE":
        queryset = queryset.filter(
            status=CouponInstance.Status.AVAILABLE,
            valid_from__lte=now,
            valid_to__gt=now,
        )
    elif normalized_status == "USED":
        queryset = queryset.filter(status=CouponInstance.Status.USED)
    elif normalized_status == "EXPIRED":
        queryset = queryset.filter(
            Q(status=CouponInstance.Status.EXPIRED)
            | Q(status=CouponInstance.Status.AVAILABLE, valid_to__lte=now)
        )
    queryset = queryset.order_by("-valid_to", "-id")
    total = queryset.count()
    items = list(queryset[(page - 1) * page_size : page * page_size])
    return {
        "items": [coupon_payload(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "status": normalized_status,
    }


def get_user_coupon(*, user, coupon_no: str) -> dict[str, Any]:
    """查询当前用户指定优惠券，禁止读取他人券实例。"""
    try:
        coupon_uuid = uuid.UUID(str(coupon_no))
    except ValueError as exc:
        raise _invalid("coupon_no", "优惠券编号格式不正确") from exc
    coupon = (
        CouponInstance.objects.select_related("template")
        .filter(user=user, coupon_no=coupon_uuid)
        .first()
    )
    if coupon is None:
        raise _not_found()
    _expire_coupon(coupon)
    coupon.refresh_from_db()
    return coupon_payload(coupon)


def _issue_coupon(
    *,
    user,
    template: CouponTemplate,
    source_type: str,
    source_no: str,
    operator_user_id: int | None = None,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> tuple[CouponInstance, bool]:
    """在调用方事务内幂等发放一张用户优惠券并校验发放限额。"""
    now = timezone.now()
    if template.status != CouponTemplate.Status.ACTIVE:
        raise _invalid("template_no", "优惠券模板未启用或已结束")
    if template.validity_type == CouponTemplate.ValidityType.FIXED_PERIOD:
        effective_from = template.valid_from or now
        effective_to = template.valid_to
        if effective_to is None or effective_to <= now:
            raise _invalid("template_no", "优惠券模板有效期已结束")
    else:
        effective_from = valid_from or now
        effective_to = valid_to or (effective_from + timedelta(days=template.validity_days or 0))
    if effective_to <= effective_from:
        raise _invalid("valid_to", "优惠券有效期结束时间必须晚于开始时间")

    if (
        template.total_issue_limit is not None
        and template.issued_count >= template.total_issue_limit
    ):
        raise _invalid("template_no", "优惠券发放总量已达上限")

    normalized_source_no = source_no.strip()[:64]
    if normalized_source_no:
        existing = CouponInstance.objects.filter(
            user=user,
            template=template,
            source_type=source_type,
            source_no=normalized_source_no,
        ).first()
        if existing is not None:
            return existing, False

    if template.per_user_issue_limit > 0:
        user_issued_count = (
            CouponInstance.objects.filter(
                user=user,
                template=template,
            )
            .exclude(status=CouponInstance.Status.REVOKED)
            .count()
        )
        if user_issued_count >= template.per_user_issue_limit:
            raise _invalid("template_no", "当前用户已达到该优惠券领取上限")

    template = CouponTemplate.objects.select_for_update().get(pk=template.pk)
    if (
        template.total_issue_limit is not None
        and template.issued_count >= template.total_issue_limit
    ):
        raise _invalid("template_no", "优惠券发放总量已达上限")

    coupon = CouponInstance.objects.create(
        template=template,
        user=user,
        status=CouponInstance.Status.AVAILABLE,
        valid_from=effective_from,
        valid_to=effective_to,
        source_type=source_type,
        source_no=normalized_source_no,
        template_snapshot=_template_snapshot(template),
    )
    CouponTemplate.objects.filter(pk=template.pk).update(
        issued_count=template.issued_count + 1,
    )
    template.refresh_from_db()
    _log_status(
        coupon=coupon,
        event_type=(
            CouponStatusLog.EventType.CLAIMED
            if source_type == CouponInstance.SourceType.USER_CLAIM
            else CouponStatusLog.EventType.ISSUED
        ),
        from_status="",
        to_status=coupon.status,
        reason="优惠券发放成功",
        operator_user_id=operator_user_id,
        idempotency_key=f"issue:{source_type}:{normalized_source_no or coupon.coupon_no}",
    )
    return coupon, True


def issue_coupon(
    *,
    user,
    template_no: str,
    source_type: str,
    source_no: str,
    operator_user_id: int | None = None,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> tuple[CouponInstance, bool]:
    """公开发放优惠券入口，供会员权益和管理员发放调用。"""
    if source_type not in CouponInstance.SourceType.values:
        raise _invalid("source_type", "优惠券发放来源不存在")
    try:
        template_uuid = uuid.UUID(str(template_no))
    except ValueError as exc:
        raise _invalid("template_no", "优惠券模板编号格式不正确") from exc
    template = CouponTemplate.objects.filter(template_no=template_uuid).first()
    if template is None:
        raise _not_found()
    try:
        with transaction.atomic():
            return _issue_coupon(
                user=user,
                template=template,
                source_type=source_type,
                source_no=source_no,
                operator_user_id=operator_user_id,
                valid_from=valid_from,
                valid_to=valid_to,
            )
    except IntegrityError as exc:
        existing = CouponInstance.objects.filter(
            user=user,
            template=template,
            source_type=source_type,
            source_no=source_no.strip()[:64],
        ).first()
        if existing is not None:
            return existing, False
        raise _conflict(
            "优惠券发放请求冲突，请稍后重试",
            code=ErrorCode.COUPON_IDEMPOTENCY_CONFLICT,
        ) from exc


def claim_coupon(
    *,
    user,
    template_no: str,
    idempotency_key: str | None = None,
) -> tuple[CouponInstance, bool]:
    """用户领取可领取优惠券，同一幂等键重复领取返回原券。"""
    normalized_key = _normalize_idempotency_key(idempotency_key, "coupon-claim")
    try:
        template_uuid = uuid.UUID(str(template_no))
    except ValueError as exc:
        raise _invalid("template_no", "优惠券模板编号格式不正确") from exc
    template = CouponTemplate.objects.filter(template_no=template_uuid).first()
    if template is None:
        raise _not_found()
    fingerprint = sensitive_fingerprint(
        {
            "user_id": user.id,
            "template_no": str(template.template_no),
            "idempotency_key": normalized_key,
        }
    )
    try:
        with transaction.atomic():
            return _issue_coupon(
                user=user,
                template=template,
                source_type=CouponInstance.SourceType.USER_CLAIM,
                source_no=normalized_key,
                operator_user_id=user.id,
            )
    except IntegrityError as exc:
        existing = CouponInstance.objects.filter(
            user=user,
            template=template,
            source_type=CouponInstance.SourceType.USER_CLAIM,
            source_no=normalized_key,
        ).first()
        if (
            existing is not None
            and sensitive_fingerprint(
                {
                    "user_id": user.id,
                    "template_no": str(template.template_no),
                    "idempotency_key": normalized_key,
                }
            )
            == fingerprint
        ):
            return existing, False
        raise _conflict(
            "优惠券领取请求与原请求不一致",
            code=ErrorCode.COUPON_IDEMPOTENCY_CONFLICT,
        ) from exc


def _scope_matches(
    *,
    template: CouponTemplate,
    snapshot: dict[str, Any],
    context: CouponScopeContext,
) -> bool:
    """按核销时模板快照校验订单城市、类目、服务和服务者范围。"""
    scope_type = snapshot.get("scope_type", template.scope_type)
    scope_value = str(snapshot.get("scope_value", template.scope_value) or "")
    if scope_type == CouponTemplate.ScopeType.ALL:
        return True
    if scope_type == CouponTemplate.ScopeType.CITY:
        return scope_value == context.city_code
    if scope_type == CouponTemplate.ScopeType.SERVICE_CATEGORY:
        return scope_value == context.category_code
    if scope_type == CouponTemplate.ScopeType.SERVICE:
        return scope_value == context.service_public_id
    if scope_type == CouponTemplate.ScopeType.PROVIDER:
        return scope_value == context.provider_public_id
    return False


def preview_coupon_discount(
    *,
    user,
    coupon_no: str,
    original_amount_minor: int,
    currency: str,
    context: CouponScopeContext,
    for_update: bool = True,
) -> dict[str, Any]:
    """服务端校验用户券并计算订单优惠，不接受客户端优惠金额。"""
    if original_amount_minor < 0:
        raise _invalid("original_amount_minor", "订单原价不能为负数")
    try:
        coupon_uuid = uuid.UUID(str(coupon_no))
    except ValueError as exc:
        raise _invalid("coupon_no", "优惠券编号格式不正确") from exc
    queryset = CouponInstance.objects.select_related("template").filter(
        user=user,
        coupon_no=coupon_uuid,
    )
    if for_update:
        queryset = queryset.select_for_update()
    coupon = queryset.first()
    if coupon is None:
        raise _not_found()
    if for_update:
        _expire_coupon(coupon)
        coupon.refresh_from_db()
    snapshot = coupon.template_snapshot or _template_snapshot(coupon.template)
    if coupon.status != CouponInstance.Status.AVAILABLE:
        raise _conflict("优惠券不可使用")
    now = timezone.now()
    if coupon.valid_from > now or coupon.valid_to <= now:
        raise _conflict("优惠券不在有效期内")
    if snapshot.get("currency", coupon.template.currency) != currency:
        raise _invalid("coupon_no", "优惠券币种与订单币种不一致")
    min_spend = int(snapshot.get("min_spend_amount_minor", 0) or 0)
    if original_amount_minor < min_spend:
        raise _invalid(
            "coupon_no",
            f"订单原价未达到优惠券满 {min_spend // 100} 元使用门槛",
        )
    if not _scope_matches(template=coupon.template, snapshot=snapshot, context=context):
        raise _invalid("coupon_no", "当前订单不在优惠券适用范围内")
    configured_discount = int(snapshot.get("discount_amount_minor", 0) or 0)
    discount_amount_minor = min(configured_discount, original_amount_minor)
    payable_amount_minor = original_amount_minor - discount_amount_minor
    return {
        "coupon_no": str(coupon.coupon_no),
        "code": snapshot.get("code", coupon.template.code),
        "name": snapshot.get("name", coupon.template.name),
        "currency": currency,
        "original_amount_minor": original_amount_minor,
        "discount_amount_minor": discount_amount_minor,
        "payable_amount_minor": payable_amount_minor,
        "template_snapshot": snapshot,
        "coupon_instance": coupon,
    }


def reserve_coupon_for_order(
    *,
    user,
    coupon_no: str,
    order_no: str,
    original_amount_minor: int,
    currency: str,
    context: CouponScopeContext,
    idempotency_key: str,
) -> CouponRedemption | None:
    """创建订单时锁定一张用户券，重复订单幂等返回原核销记录。"""
    if not coupon_no:
        return None
    normalized_key = _normalize_idempotency_key(idempotency_key, "coupon-reserve")
    fingerprint = sensitive_fingerprint(
        {
            "user_id": user.id,
            "coupon_no": str(coupon_no),
            "order_no": str(order_no),
            "original_amount_minor": original_amount_minor,
            "currency": currency,
            "scope": {
                "city_code": context.city_code,
                "category_code": context.category_code,
                "service_public_id": context.service_public_id,
                "provider_public_id": context.provider_public_id,
            },
        }
    )
    existing = CouponRedemption.objects.select_for_update().filter(order_no=str(order_no)).first()
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise _conflict(
                "优惠券订单请求与原请求不一致",
                code=ErrorCode.COUPON_IDEMPOTENCY_CONFLICT,
            )
        return existing
    preview = preview_coupon_discount(
        user=user,
        coupon_no=coupon_no,
        original_amount_minor=original_amount_minor,
        currency=currency,
        context=context,
    )
    coupon = preview.pop("coupon_instance")
    previous_status = coupon.status
    coupon.status = CouponInstance.Status.RESERVED
    coupon.version += 1
    coupon.save(update_fields=["status", "version", "updated_at"])
    redemption = CouponRedemption.objects.create(
        coupon=coupon,
        user=user,
        order_no=str(order_no),
        status=CouponRedemption.Status.RESERVED,
        currency=currency,
        original_amount_minor=original_amount_minor,
        discount_amount_minor=preview["discount_amount_minor"],
        payable_amount_minor=preview["payable_amount_minor"],
        template_snapshot=preview["template_snapshot"],
        idempotency_key=normalized_key,
        request_fingerprint=fingerprint,
    )
    _log_status(
        coupon=coupon,
        redemption=redemption,
        event_type=CouponStatusLog.EventType.RESERVED,
        from_status=previous_status,
        to_status=coupon.status,
        reason="订单创建锁定优惠券",
        operator_user_id=user.id,
        idempotency_key=f"reserve:{order_no}",
    )
    return redemption


def consume_coupon_for_order(
    *,
    order_no: str,
    idempotency_key: str | None = None,
) -> CouponRedemption | None:
    """订单支付成功后幂等核销已锁定优惠券。"""
    normalized_key = _normalize_idempotency_key(idempotency_key, "coupon-use")
    redemption = (
        CouponRedemption.objects.select_for_update()
        .select_related("coupon")
        .filter(order_no=str(order_no))
        .first()
    )
    if redemption is None:
        return None
    if redemption.status == CouponRedemption.Status.USED:
        return redemption
    if redemption.status != CouponRedemption.Status.RESERVED:
        raise _conflict("优惠券核销状态不允许支付确认")
    coupon = redemption.coupon
    previous_status = coupon.status
    coupon.status = CouponInstance.Status.USED
    coupon.used_at = timezone.now()
    coupon.version += 1
    coupon.save(update_fields=["status", "used_at", "version", "updated_at"])
    redemption.status = CouponRedemption.Status.USED
    redemption.used_at = coupon.used_at
    redemption.save(update_fields=["status", "used_at", "updated_at"])
    _log_status(
        coupon=coupon,
        redemption=redemption,
        event_type=CouponStatusLog.EventType.USED,
        from_status=previous_status,
        to_status=coupon.status,
        reason="订单支付成功核销优惠券",
        idempotency_key=normalized_key,
    )
    return redemption


def release_coupon_for_order(
    *,
    order_no: str,
    reason: str,
    idempotency_key: str | None = None,
) -> CouponRedemption | None:
    """订单取消或支付失败时释放已锁定优惠券，已过期券不恢复可用。"""
    normalized_key = _normalize_idempotency_key(idempotency_key, "coupon-release")
    redemption = (
        CouponRedemption.objects.select_for_update()
        .select_related("coupon")
        .filter(order_no=str(order_no))
        .first()
    )
    if redemption is None:
        return None
    if redemption.status == CouponRedemption.Status.RELEASED:
        return redemption
    if redemption.status != CouponRedemption.Status.RESERVED:
        return redemption
    coupon = redemption.coupon
    previous_status = coupon.status
    now = timezone.now()
    coupon.status = (
        CouponInstance.Status.AVAILABLE if coupon.valid_to > now else CouponInstance.Status.EXPIRED
    )
    coupon.version += 1
    coupon.save(update_fields=["status", "version", "updated_at"])
    redemption.status = CouponRedemption.Status.RELEASED
    redemption.released_at = now
    redemption.save(update_fields=["status", "released_at", "updated_at"])
    _log_status(
        coupon=coupon,
        redemption=redemption,
        event_type=CouponStatusLog.EventType.RELEASED,
        from_status=previous_status,
        to_status=coupon.status,
        reason=reason or "订单取消或支付失败",
        idempotency_key=normalized_key,
    )
    return redemption


def record_coupon_order_refund(
    *,
    order_no: str,
    reason: str,
    idempotency_key: str | None = None,
) -> CouponRedemption | None:
    """记录订单退款对优惠券的影响；按确认规则不自动返还已使用优惠券。"""
    normalized_key = _normalize_idempotency_key(idempotency_key, "coupon-refund")
    redemption = (
        CouponRedemption.objects.select_for_update()
        .select_related("coupon")
        .filter(order_no=str(order_no))
        .first()
    )
    if redemption is None:
        return None
    _log_status(
        coupon=redemption.coupon,
        redemption=redemption,
        event_type=CouponStatusLog.EventType.ORDER_REFUNDED,
        from_status=redemption.coupon.status,
        to_status=redemption.coupon.status,
        reason=reason or "关联订单退款，不自动返还优惠券",
        idempotency_key=normalized_key,
    )
    return redemption


def revoke_coupon(
    *,
    coupon_no: str,
    reason: str,
    operator_user_id: int,
    expected_version: int,
) -> dict[str, Any]:
    """管理员撤销未使用优惠券，保留券实例和审计记录。"""
    if len(reason.strip()) < 2:
        raise _invalid("reason", "撤销原因至少需要 2 个字符")
    try:
        coupon_uuid = uuid.UUID(str(coupon_no))
    except ValueError as exc:
        raise _invalid("coupon_no", "优惠券编号格式不正确") from exc
    with transaction.atomic():
        coupon = (
            CouponInstance.objects.select_for_update()
            .select_related("template")
            .filter(coupon_no=coupon_uuid)
            .first()
        )
        if coupon is None:
            raise _not_found()
        if coupon.version != expected_version:
            raise _conflict(
                "优惠券已被更新，请刷新后重试",
                code=ErrorCode.COUPON_VERSION_CONFLICT,
            )
        if coupon.status not in {
            CouponInstance.Status.AVAILABLE,
            CouponInstance.Status.EXPIRED,
        }:
            raise _conflict("已锁定或已使用的优惠券不能撤销")
        previous_status = coupon.status
        coupon.status = CouponInstance.Status.REVOKED
        coupon.revoked_at = timezone.now()
        coupon.version += 1
        coupon.save(update_fields=["status", "revoked_at", "version", "updated_at"])
        _log_status(
            coupon=coupon,
            event_type=CouponStatusLog.EventType.REVOKED,
            from_status=previous_status,
            to_status=coupon.status,
            reason=reason.strip(),
            operator_user_id=operator_user_id,
            idempotency_key=f"revoke:{coupon.coupon_no}:{expected_version}",
        )
        return coupon_payload(coupon)


def get_coupon_redemption_for_order(*, order_no: str) -> dict[str, Any] | None:
    """返回订单优惠券核销摘要，供订单详情只读展示。"""
    redemption = (
        CouponRedemption.objects.select_related("coupon", "coupon__template")
        .filter(order_no=str(order_no))
        .order_by("-created_at", "-id")
        .first()
    )
    return redemption_payload(redemption) if redemption is not None else None


def list_admin_redemptions(
    *,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """分页查询优惠券订单核销记录，供财务和运营审计。"""
    queryset = CouponRedemption.objects.select_related("coupon", "coupon__template").order_by(
        "-created_at",
        "-id",
    )
    if status:
        normalized_status = status.upper()
        if normalized_status not in CouponRedemption.Status.values:
            raise _invalid("status", "优惠券核销状态不存在")
        queryset = queryset.filter(status=normalized_status)
    total = queryset.count()
    items = list(queryset[(page - 1) * page_size : page * page_size])
    return {
        "items": [redemption_payload(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def admin_coupon_template_payload(template: CouponTemplate) -> dict[str, Any]:
    """返回管理员优惠券模板配置和发放计数。"""
    return {
        "template_no": str(template.template_no),
        "code": template.code,
        "name": template.name,
        "description": template.description,
        "discount_type": template.discount_type,
        "discount_type_text": enum_label(
            CouponTemplate.DiscountType,
            template.discount_type,
        ),
        "currency": template.currency,
        "discount_amount_minor": template.discount_amount_minor,
        "min_spend_amount_minor": template.min_spend_amount_minor,
        "scope_type": template.scope_type,
        "scope_type_text": enum_label(CouponTemplate.ScopeType, template.scope_type),
        "scope_value": template.scope_value,
        "validity_type": template.validity_type,
        "validity_type_text": enum_label(
            CouponTemplate.ValidityType,
            template.validity_type,
        ),
        "valid_from": template.valid_from,
        "valid_to": template.valid_to,
        "validity_days": template.validity_days,
        "total_issue_limit": template.total_issue_limit,
        "per_user_issue_limit": template.per_user_issue_limit,
        "issued_count": template.issued_count,
        "status": template.status,
        "status_text": enum_label(CouponTemplate.Status, template.status),
        "version": template.version,
        "created_at": template.created_at,
        "updated_at": template.updated_at,
    }


def list_admin_coupon_templates(
    *,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """分页查询优惠券模板和发放进度。"""
    queryset = CouponTemplate.objects.order_by("-created_at", "-id")
    if status:
        normalized_status = status.upper()
        if normalized_status not in CouponTemplate.Status.values:
            raise _invalid("status", "优惠券模板状态不存在")
        queryset = queryset.filter(status=normalized_status)
    total = queryset.count()
    items = list(queryset[(page - 1) * page_size : page * page_size])
    return {
        "items": [admin_coupon_template_payload(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _validate_template_payload(payload: dict[str, Any], *, creating: bool) -> dict[str, Any]:
    """校验优惠券模板金额、范围和有效期组合。"""
    if creating:
        code = str(payload.get("code", "")).strip()
        name = str(payload.get("name", "")).strip()
        if not code or not name:
            raise _invalid("code", "优惠券模板代码和名称不能为空")
    else:
        code = str(payload.get("code", "")).strip()
        name = str(payload.get("name", "")).strip()
    discount_type = str(payload.get("discount_type", "FIXED_AMOUNT")).upper()
    if discount_type != CouponTemplate.DiscountType.FIXED_AMOUNT:
        raise _invalid("discount_type", "当前仅支持固定金额优惠券")
    discount_amount_minor = int(payload.get("discount_amount_minor", 0))
    if discount_amount_minor <= 0:
        raise _invalid("discount_amount_minor", "优惠金额必须大于 0")
    min_spend_amount_minor = int(payload.get("min_spend_amount_minor", 0))
    if min_spend_amount_minor < 0:
        raise _invalid("min_spend_amount_minor", "最低消费门槛不能为负数")
    scope_type = str(payload.get("scope_type", "ALL")).upper()
    if scope_type not in CouponTemplate.ScopeType.values:
        raise _invalid("scope_type", "优惠适用范围不存在")
    scope_value = str(payload.get("scope_value", "")).strip()
    if scope_type == CouponTemplate.ScopeType.ALL:
        scope_value = ""
    elif not scope_value:
        raise _invalid("scope_value", "指定适用范围时范围代码不能为空")
    validity_type = str(payload.get("validity_type", "FIXED_PERIOD")).upper()
    if validity_type not in CouponTemplate.ValidityType.values:
        raise _invalid("validity_type", "优惠券有效期类型不存在")
    valid_from = payload.get("valid_from")
    valid_to = payload.get("valid_to")
    validity_days = payload.get("validity_days")
    if validity_type == CouponTemplate.ValidityType.FIXED_PERIOD:
        if not valid_from or not valid_to or validity_days is not None:
            raise _invalid("valid_from", "固定有效期必须提供开始和结束时间且不填写有效天数")
        if valid_to <= valid_from:
            raise _invalid("valid_to", "有效期结束时间必须晚于开始时间")
    else:
        if valid_from or valid_to or not validity_days or int(validity_days) <= 0:
            raise _invalid("validity_days", "领取后生效必须提供正整数有效天数")
        valid_from = None
        valid_to = None
        validity_days = int(validity_days)
    total_issue_limit = payload.get("total_issue_limit")
    per_user_issue_limit = int(payload.get("per_user_issue_limit", 1))
    if total_issue_limit is not None and int(total_issue_limit) <= 0:
        raise _invalid("total_issue_limit", "发放总量上限必须大于 0")
    if per_user_issue_limit < 0:
        raise _invalid("per_user_issue_limit", "单用户领取上限不能为负数")
    return {
        "code": code,
        "name": name,
        "description": str(payload.get("description", "")).strip(),
        "discount_type": discount_type,
        "currency": str(payload.get("currency", "CNY")).strip().upper() or "CNY",
        "discount_amount_minor": discount_amount_minor,
        "min_spend_amount_minor": min_spend_amount_minor,
        "scope_type": scope_type,
        "scope_value": scope_value,
        "validity_type": validity_type,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "validity_days": validity_days,
        "total_issue_limit": int(total_issue_limit) if total_issue_limit is not None else None,
        "per_user_issue_limit": per_user_issue_limit,
        "status": str(payload.get("status", CouponTemplate.Status.DRAFT)).upper(),
    }


def create_coupon_template(
    *,
    operator,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """管理员创建优惠券模板，默认草稿状态且不直接发放。"""
    values = _validate_template_payload(payload, creating=True)
    if values["status"] not in CouponTemplate.Status.values:
        raise _invalid("status", "优惠券模板状态不存在")
    try:
        with transaction.atomic():
            template = CouponTemplate.objects.create(
                **values,
                created_by=operator.id,
                updated_by=operator.id,
            )
    except IntegrityError as exc:
        raise _conflict(
            "优惠券模板代码已存在",
            code=ErrorCode.COUPON_IDEMPOTENCY_CONFLICT,
        ) from exc
    return admin_coupon_template_payload(template)


def update_coupon_template(
    *,
    operator,
    template_no: str,
    payload: dict[str, Any],
    expected_version: int,
) -> dict[str, Any]:
    """管理员修改优惠券模板；已发放实例继续使用领取时快照。"""
    try:
        template_uuid = uuid.UUID(str(template_no))
    except ValueError as exc:
        raise _invalid("template_no", "优惠券模板编号格式不正确") from exc
    with transaction.atomic():
        template = (
            CouponTemplate.objects.select_for_update().filter(template_no=template_uuid).first()
        )
        if template is None:
            raise _not_found()
        if template.version != expected_version:
            raise _conflict(
                "优惠券模板已被更新，请刷新后重试",
                code=ErrorCode.COUPON_VERSION_CONFLICT,
            )
        if "code" in payload and str(payload["code"]).strip() != template.code:
            raise _invalid("code", "优惠券模板代码创建后不可修改")
        merged = admin_coupon_template_payload(template)
        merged.update({key: value for key, value in payload.items() if value is not None})
        values = _validate_template_payload(merged, creating=False)
        if (
            values["total_issue_limit"] is not None
            and values["total_issue_limit"] < template.issued_count
        ):
            raise _invalid("total_issue_limit", "发放总量上限不能低于已发放数量")
        if values["status"] not in CouponTemplate.Status.values:
            raise _invalid("status", "优惠券模板状态不存在")
        for field, value in values.items():
            setattr(template, field, value)
        template.updated_by = operator.id
        template.version += 1
        template.save()
        return admin_coupon_template_payload(template)


def admin_issue_coupon(
    *,
    operator,
    user,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """管理员向指定用户发放优惠券并保存来源和幂等记录。"""
    coupon, created = issue_coupon(
        user=user,
        template_no=str(payload.get("template_no", "")),
        source_type=CouponInstance.SourceType.ADMIN_ISSUE,
        source_no=str(payload.get("source_no", "")).strip()
        or f"admin:{operator.id}:{uuid.uuid4()}",
        operator_user_id=operator.id,
        valid_from=payload.get("valid_from"),
        valid_to=payload.get("valid_to"),
    )
    result = coupon_payload(coupon)
    result["created"] = created
    return result
