"""会员套餐、购买支付、续费顺延、权益发放和管理员维护服务。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from backend.common.context import current_trace_id
from backend.common.crypto import sensitive_fingerprint
from backend.common.display import enum_label
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.memberships.models import (
    MembershipAccount,
    MembershipBenefitGrant,
    MembershipPeriod,
    MembershipPlan,
    MembershipPlanVersion,
    MembershipPurchase,
    MembershipStatusLog,
)

MEMBERSHIP_BENEFIT_CODES = {
    "PRIORITY_RECOMMENDATION",
    "DEDICATED_SUPPORT",
    "MEMBER_COUPON",
}


def _invalid(field: str, message: str) -> ApiError:
    """返回会员参数或业务规则校验错误。"""
    return ApiError(
        ErrorCode.MEMBERSHIP_INVALID,
        message,
        status_code=400,
        details={field: message},
    )


def _not_found() -> ApiError:
    """返回会员套餐或购买记录不存在错误。"""
    return ApiError(
        ErrorCode.MEMBERSHIP_NOT_FOUND,
        ERROR_MESSAGES[ErrorCode.MEMBERSHIP_NOT_FOUND],
        status_code=404,
    )


def _conflict(message: str, *, code: ErrorCode = ErrorCode.MEMBERSHIP_STATE_INVALID) -> ApiError:
    """返回会员状态、版本或幂等冲突错误。"""
    return ApiError(code, message, status_code=409)


def _normalize_idempotency_key(value: str | None, prefix: str) -> str:
    """规范化会员购买和权益幂等键。"""
    if value is None:
        return f"auto:{prefix}:{uuid.uuid4()}"
    key = value.strip()
    if not key or len(key) > 128:
        raise _invalid("idempotency_key", "幂等键长度必须在 1 到 128 之间")
    return key


def _plan_version_snapshot(version: MembershipPlanVersion) -> dict[str, Any]:
    """生成写入购买单和有效期的套餐版本快照。"""
    return {
        "plan_no": str(version.plan.plan_no),
        "plan_code": version.plan.code,
        "version_no": version.version_no,
        "name": version.name,
        "description": version.description,
        "duration_days": version.duration_days,
        "currency": version.currency,
        "price_amount_minor": version.price_amount_minor,
        "benefits": version.benefits,
    }


def _validate_benefits(benefits: Any) -> list[dict[str, Any]]:
    """校验会员权益配置，拒绝未知权益和缺少发放参数的会员券。"""
    if not isinstance(benefits, list):
        raise _invalid("benefits", "会员权益必须是列表")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in benefits:
        if not isinstance(item, dict):
            raise _invalid("benefits", "每项会员权益必须是对象")
        code = str(item.get("code", "")).strip().upper()
        if code not in MEMBERSHIP_BENEFIT_CODES:
            raise _invalid("benefits", f"会员权益代码不存在：{code or '空'}")
        if code in seen:
            raise _invalid("benefits", f"会员权益不能重复配置：{code}")
        seen.add(code)
        normalized_item: dict[str, Any] = {"code": code}
        if code == "MEMBER_COUPON":
            coupon_template_no = str(item.get("coupon_template_no", "")).strip()
            coupon_template_code = str(item.get("coupon_template_code", "")).strip()
            if not coupon_template_no and not coupon_template_code:
                raise _invalid(
                    "benefits",
                    "会员优惠券权益必须配置 coupon_template_no 或 coupon_template_code",
                )
            try:
                count = int(item.get("count", 1))
            except (TypeError, ValueError) as exc:
                raise _invalid("benefits", "会员优惠券发放数量必须是整数") from exc
            if count < 1 or count > 10:
                raise _invalid("benefits", "会员优惠券发放数量必须在 1 到 10 之间")
            normalized_item.update(
                {
                    "coupon_template_no": coupon_template_no,
                    "coupon_template_code": coupon_template_code,
                    "count": count,
                }
            )
        normalized.append(normalized_item)
    return normalized


def plan_version_payload(version: MembershipPlanVersion) -> dict[str, Any]:
    """返回会员套餐当前版本安全展示信息。"""
    return {
        "plan_no": str(version.plan.plan_no),
        "code": version.plan.code,
        "name": version.name,
        "description": version.description,
        "duration_days": version.duration_days,
        "currency": version.currency,
        "price_amount_minor": version.price_amount_minor,
        "benefits": version.benefits,
        "status": version.plan.status,
        "status_text": enum_label(MembershipPlan.Status, version.plan.status),
        "sort_order": version.plan.sort_order,
        "version": version.version_no,
    }


def purchase_payload(
    purchase: MembershipPurchase,
    *,
    payment: Any | None = None,
) -> dict[str, Any]:
    """返回会员购买单、套餐快照和支付安全摘要。"""
    from backend.payments.services import payment_payload

    return {
        "purchase_no": str(purchase.purchase_no),
        "status": purchase.status,
        "status_text": enum_label(MembershipPurchase.Status, purchase.status),
        "plan": purchase.plan_snapshot,
        "currency": purchase.currency,
        "amount_minor": purchase.amount_minor,
        "payment_no": purchase.payment_no or None,
        "payment": payment_payload(payment) if payment is not None else None,
        "version": purchase.version,
        "paid_at": purchase.paid_at,
        "created_at": purchase.created_at,
        "updated_at": purchase.updated_at,
    }


def period_payload(period: MembershipPeriod) -> dict[str, Any]:
    """返回会员有效期周期和套餐快照。"""
    return {
        "period_no": str(period.period_no),
        "purchase_no": str(period.purchase.purchase_no),
        "plan": period.plan_snapshot,
        "status": period.status,
        "status_text": enum_label(MembershipPeriod.Status, period.status),
        "starts_at": period.starts_at,
        "ends_at": period.ends_at,
        "activated_at": period.activated_at,
        "expired_at": period.expired_at,
    }


def _log_membership(
    *,
    purchase: MembershipPurchase,
    event_type: str,
    from_status: str,
    to_status: str,
    idempotency_key: str,
    reason: str = "",
    period: MembershipPeriod | None = None,
    actor_user_id: int | None = None,
) -> None:
    """在当前事务内追加会员购买和有效期状态审计。"""
    MembershipStatusLog.objects.create(
        purchase=purchase,
        period=period,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        reason=reason[:500],
        actor_user_id=actor_user_id,
        idempotency_key=idempotency_key[:128],
        trace_id=current_trace_id(),
    )


def _current_plan_version(*, plan: MembershipPlan) -> MembershipPlanVersion:
    """读取套餐当前版本；缺失时视为配置数据不完整。"""
    version = plan.versions.filter(version_no=plan.version).first()
    if version is None:
        raise _invalid("plan_code", "会员套餐版本配置不完整")
    return version


def list_membership_plans(*, include_unavailable: bool = False) -> list[dict[str, Any]]:
    """查询可购买会员套餐，价格和权益只读取当前版本。"""
    queryset = MembershipPlan.objects.order_by("sort_order", "id")
    if not include_unavailable:
        queryset = queryset.filter(status=MembershipPlan.Status.ACTIVE)
    result = []
    for plan in queryset:
        version = _current_plan_version(plan=plan)
        result.append(plan_version_payload(version))
    return result


@dataclass(slots=True)
class MembershipPurchaseResult:
    """会员购买创建或幂等重放结果。"""

    purchase: MembershipPurchase
    payment: Any | None
    payment_action: str
    created: bool
    reused: bool


def _get_payment_for_purchase(purchase: MembershipPurchase) -> Any | None:
    """按支付单号读取会员购买关联支付，不存在时返回空。"""
    if not purchase.payment_no:
        return None
    from backend.payments.models import Payment

    return Payment.objects.filter(
        payment_no=purchase.payment_no,
        user=purchase.user,
    ).first()


def create_membership_purchase(
    *,
    user,
    plan_code: str,
    payment_method: str,
    idempotency_key: str | None = None,
) -> MembershipPurchaseResult:
    """创建会员购买单并发起余额、微信或支付宝支付；重复请求幂等。"""
    normalized_key = _normalize_idempotency_key(idempotency_key, "membership-purchase")
    if payment_method not in {"BALANCE", "WECHAT_APP", "ALIPAY_APP"}:
        raise _invalid("payment_method", "不支持的支付方式")
    try:
        with transaction.atomic():
            plan = (
                MembershipPlan.objects.select_for_update()
                .filter(code=plan_code.strip(), status=MembershipPlan.Status.ACTIVE)
                .first()
            )
            if plan is None:
                raise _invalid("plan_code", "会员套餐不存在、未上架或已暂停")
            version = _current_plan_version(plan=plan)
            fingerprint = sensitive_fingerprint(
                {
                    "user_id": user.id,
                    "plan_no": str(plan.plan_no),
                    "plan_version": version.version_no,
                    "amount_minor": version.price_amount_minor,
                    "currency": version.currency,
                    "payment_method": payment_method,
                }
            )
            existing = MembershipPurchase.objects.filter(
                user=user,
                idempotency_key=normalized_key,
            ).first()
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise _conflict(
                        "会员购买请求与原请求不一致",
                        code=ErrorCode.MEMBERSHIP_IDEMPOTENCY_CONFLICT,
                    )
                payment = _get_payment_for_purchase(existing)
                return MembershipPurchaseResult(
                    purchase=existing,
                    payment=payment,
                    payment_action="NONE"
                    if payment and payment.status == "SUCCESS"
                    else "NATIVE_PAY",
                    created=False,
                    reused=True,
                )
            purchase = MembershipPurchase.objects.create(
                user=user,
                plan=plan,
                plan_version=version,
                plan_snapshot=_plan_version_snapshot(version),
                status=MembershipPurchase.Status.PENDING_PAYMENT,
                currency=version.currency,
                amount_minor=version.price_amount_minor,
                idempotency_key=normalized_key,
                request_fingerprint=fingerprint,
            )
            _log_membership(
                purchase=purchase,
                event_type=MembershipStatusLog.EventType.PURCHASE_CREATED,
                from_status="",
                to_status=purchase.status,
                idempotency_key=f"create:{purchase.purchase_no}",
                reason="创建会员购买单",
                actor_user_id=user.id,
            )
    except IntegrityError as exc:
        existing = MembershipPurchase.objects.filter(
            user=user,
            idempotency_key=normalized_key,
        ).first()
        if existing is not None:
            payment = _get_payment_for_purchase(existing)
            return MembershipPurchaseResult(
                purchase=existing,
                payment=payment,
                payment_action="NONE" if payment and payment.status == "SUCCESS" else "NATIVE_PAY",
                created=False,
                reused=True,
            )
        raise _conflict(
            "会员购买请求冲突，请稍后重试",
            code=ErrorCode.MEMBERSHIP_IDEMPOTENCY_CONFLICT,
        ) from exc

    from backend.payments.models import Payment
    from backend.payments.services import (
        charge_wallet_for_order,
        create_external_payment,
    )

    payment_kwargs = {
        "user": user,
        "order_no": str(purchase.purchase_no),
        "business_type": Payment.BusinessType.MEMBERSHIP_PURCHASE,
        "business_no": str(purchase.purchase_no),
        "amount_minor": purchase.amount_minor,
        "idempotency_key": f"membership-payment:{normalized_key}",
    }
    if payment_method == Payment.Method.BALANCE:
        charge_result = charge_wallet_for_order(**payment_kwargs)
        payment_action = "NONE"
    elif payment_method in {Payment.Method.WECHAT_APP, Payment.Method.ALIPAY_APP}:
        charge_result = create_external_payment(
            **payment_kwargs,
            payment_method=payment_method,
            description=f"FaceTo 会员购买：{purchase.plan_snapshot.get('name', '')}",
        )
        payment_action = "NATIVE_PAY"
    else:
        raise _invalid("payment_method", "不支持的支付方式")

    payment = charge_result.payment
    purchase.payment_no = str(payment.payment_no)
    purchase.version += 1
    purchase.save(update_fields=["payment_no", "version", "updated_at"])
    if payment.status == Payment.Status.SUCCESS:
        confirm_membership_payment(payment=payment)
        purchase.refresh_from_db()
    return MembershipPurchaseResult(
        purchase=purchase,
        payment=payment,
        payment_action=payment_action,
        created=True,
        reused=charge_result.reused,
    )


def confirm_membership_payment(*, payment) -> MembershipPurchase:
    """支付成功后幂等确认会员购买并生成顺延后的有效期周期。"""
    from backend.payments.models import Payment

    if payment.business_type != Payment.BusinessType.MEMBERSHIP_PURCHASE:
        raise _invalid("business_type", "支付单不是会员购买")
    with transaction.atomic():
        purchase = (
            MembershipPurchase.objects.select_for_update()
            .select_related("plan", "plan_version")
            .filter(
                purchase_no=payment.business_no or payment.order_no,
                user=payment.user,
            )
            .first()
        )
        if purchase is None:
            raise _not_found()
        if purchase.currency != payment.currency:
            raise _conflict("支付币种与会员购买单不一致")
        if purchase.amount_minor != payment.amount_minor:
            raise _conflict("支付金额与会员购买单不一致")
        if purchase.status == MembershipPurchase.Status.PAID:
            if hasattr(purchase, "period"):
                return purchase
        elif purchase.status != MembershipPurchase.Status.PENDING_PAYMENT:
            raise _conflict("当前会员购买状态不允许确认支付")

        previous_status = purchase.status
        if purchase.status == MembershipPurchase.Status.PAID:
            _activate_membership_period(purchase=purchase)
            purchase.refresh_from_db()
            return purchase
        purchase.status = MembershipPurchase.Status.PAID
        purchase.paid_at = payment.paid_at or timezone.now()
        purchase.version += 1
        purchase.save(update_fields=["status", "paid_at", "version", "updated_at"])
        _log_membership(
            purchase=purchase,
            event_type=MembershipStatusLog.EventType.PAYMENT_SUCCESS,
            from_status=previous_status,
            to_status=purchase.status,
            idempotency_key=f"paid:{payment.payment_no}",
            reason="会员购买支付成功",
            actor_user_id=payment.user_id,
        )
        _activate_membership_period(purchase=purchase)
        purchase.refresh_from_db()
        return purchase


def _activate_membership_period(*, purchase: MembershipPurchase) -> MembershipPeriod:
    """在会员账户锁内创建有效期并按当前到期时间顺延，权益同步幂等发放。"""
    if hasattr(purchase, "period"):
        return purchase.period
    now = timezone.now()
    account, _ = MembershipAccount.objects.get_or_create(user=purchase.user)
    account = MembershipAccount.objects.select_for_update().get(pk=account.pk)
    current_until = account.active_until_at
    starts_at = current_until if current_until and current_until > now else now
    duration_days = int(
        purchase.plan_snapshot.get("duration_days", purchase.plan_version.duration_days)
    )
    ends_at = starts_at + timedelta(days=duration_days)
    fingerprint = sensitive_fingerprint(
        {
            "purchase_no": str(purchase.purchase_no),
            "plan_version": purchase.plan_version.version_no,
            "starts_at": starts_at.isoformat(),
            "ends_at": ends_at.isoformat(),
        }
    )
    period = MembershipPeriod.objects.create(
        purchase=purchase,
        user=purchase.user,
        plan=purchase.plan,
        plan_version=purchase.plan_version,
        plan_snapshot=purchase.plan_snapshot,
        status=MembershipPeriod.Status.ACTIVE,
        starts_at=starts_at,
        ends_at=ends_at,
        idempotency_key=f"membership-period:{purchase.purchase_no}",
        request_fingerprint=fingerprint,
    )
    account.active_until_at = ends_at
    account.current_period_no = period.period_no
    account.version = F("version") + 1
    account.save(update_fields=["active_until_at", "current_period_no", "version", "updated_at"])
    account.refresh_from_db()
    _log_membership(
        purchase=purchase,
        period=period,
        event_type=(
            MembershipStatusLog.EventType.PERIOD_EXTENDED
            if current_until and current_until > now
            else MembershipStatusLog.EventType.PERIOD_ACTIVATED
        ),
        from_status="",
        to_status=period.status,
        idempotency_key=f"period:{period.period_no}",
        reason=(
            "会员续费有效期顺延" if current_until and current_until > now else "会员购买成功后生效"
        ),
        actor_user_id=purchase.user_id,
    )
    _issue_membership_benefits(period=period)
    return period


def _issue_membership_benefits(*, period: MembershipPeriod) -> None:
    """按购买时权益快照幂等发放专属标记和会员优惠券。"""
    from backend.coupons.models import CouponTemplate
    from backend.coupons.services import issue_coupon

    benefits = period.plan_snapshot.get("benefits", [])
    if not isinstance(benefits, list):
        return
    for item in benefits:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code", "")).strip().upper()
        if code not in MEMBERSHIP_BENEFIT_CODES:
            continue
        count = int(item.get("count", 1) or 1) if code == "MEMBER_COUPON" else 1
        for index in range(count):
            idempotency_key = f"membership-benefit:{period.period_no}:{code}:{index}"
            existing = MembershipBenefitGrant.objects.filter(
                period=period,
                benefit_code=code,
                idempotency_key=idempotency_key,
            ).first()
            if existing is not None:
                continue
            payload: dict[str, Any] = {"plan_version": period.plan_version.version_no}
            status = MembershipBenefitGrant.Status.ACTIVE
            if code == "MEMBER_COUPON":
                template = None
                template_no = str(item.get("coupon_template_no", "")).strip()
                template_code = str(item.get("coupon_template_code", "")).strip()
                if template_no:
                    try:
                        template = CouponTemplate.objects.filter(
                            template_no=uuid.UUID(template_no),
                            status=CouponTemplate.Status.ACTIVE,
                        ).first()
                    except ValueError:
                        template = None
                if template is None and template_code:
                    template = CouponTemplate.objects.filter(
                        code=template_code,
                        status=CouponTemplate.Status.ACTIVE,
                    ).first()
                if template is None:
                    status = MembershipBenefitGrant.Status.SKIPPED
                    payload["reason"] = "会员优惠券模板未启用或配置已变化"
                else:
                    try:
                        coupon, _ = issue_coupon(
                            user=period.user,
                            template_no=str(template.template_no),
                            source_type="MEMBERSHIP",
                            source_no=f"{period.period_no}:{code}:{index}",
                            operator_user_id=None,
                        )
                        payload["coupon_no"] = str(coupon.coupon_no)
                    except ApiError as exc:
                        status = MembershipBenefitGrant.Status.SKIPPED
                        payload["reason"] = str(exc)
            MembershipBenefitGrant.objects.create(
                period=period,
                user=period.user,
                benefit_code=code,
                status=status,
                payload=payload,
                idempotency_key=idempotency_key,
            )


def get_membership_summary(*, user) -> dict[str, Any]:
    """查询当前用户会员状态、有效期、套餐和已生效权益。"""
    now = timezone.now()
    with transaction.atomic():
        account, _ = MembershipAccount.objects.get_or_create(user=user)
        account = MembershipAccount.objects.select_for_update().get(pk=account.pk)
        expired_periods = list(
            MembershipPeriod.objects.select_for_update().filter(
                user=user,
                status=MembershipPeriod.Status.ACTIVE,
                ends_at__lte=now,
            )
        )
        for period in expired_periods:
            period.status = MembershipPeriod.Status.EXPIRED
            period.expired_at = now
            period.version += 1
            period.save(update_fields=["status", "expired_at", "version", "updated_at"])
            _log_membership(
                purchase=period.purchase,
                period=period,
                event_type=MembershipStatusLog.EventType.PERIOD_EXPIRED,
                from_status=MembershipPeriod.Status.ACTIVE,
                to_status=period.status,
                idempotency_key=f"expired:{period.period_no}",
                reason="会员有效期届满",
            )
        current_period = None
        if account.current_period_no:
            current_period = MembershipPeriod.objects.filter(
                user=user,
                period_no=account.current_period_no,
                status=MembershipPeriod.Status.ACTIVE,
                ends_at__gt=now,
            ).first()
        if current_period is None:
            current_period = (
                MembershipPeriod.objects.select_related("plan_version", "purchase")
                .filter(user=user, status=MembershipPeriod.Status.ACTIVE, ends_at__gt=now)
                .order_by("-ends_at", "-id")
                .first()
            )
        if current_period is not None:
            account.active_until_at = current_period.ends_at
            account.current_period_no = current_period.period_no
        else:
            account.active_until_at = None
            account.current_period_no = None
        account.version = F("version") + 1
        account.save(
            update_fields=["active_until_at", "current_period_no", "version", "updated_at"]
        )
        account.refresh_from_db()

        benefits = []
        if current_period is not None:
            benefits = list(
                MembershipBenefitGrant.objects.filter(
                    period=current_period,
                ).order_by("benefit_code", "id")
            )
    return {
        "is_member": current_period is not None,
        "plan": current_period.plan_snapshot if current_period else None,
        "period": period_payload(current_period) if current_period else None,
        "benefits": [
            {
                "grant_no": str(item.grant_no),
                "code": item.benefit_code,
                "status": item.status,
                "status_text": enum_label(MembershipBenefitGrant.Status, item.status),
                "payload": item.payload,
            }
            for item in benefits
        ],
    }


def list_membership_purchases(
    *,
    user,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """分页查询当前用户会员购买历史。"""
    queryset = (
        MembershipPurchase.objects.select_related(
            "plan",
            "plan_version",
        )
        .filter(user=user)
        .order_by("-created_at", "-id")
    )
    total = queryset.count()
    items = list(queryset[(page - 1) * page_size : page * page_size])
    return {
        "items": [purchase_payload(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_membership_purchase(*, user, purchase_no: str) -> dict[str, Any]:
    """查询当前用户指定会员购买单并返回支付摘要。"""
    try:
        purchase_uuid = uuid.UUID(str(purchase_no))
    except ValueError as exc:
        raise _invalid("purchase_no", "会员购买单编号格式不正确") from exc
    purchase = (
        MembershipPurchase.objects.select_related("plan", "plan_version")
        .filter(user=user, purchase_no=purchase_uuid)
        .first()
    )
    if purchase is None:
        raise _not_found()
    return purchase_payload(purchase, payment=_get_payment_for_purchase(purchase))


def create_membership_plan(
    *,
    operator,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """管理员创建会员套餐并生成初始不可变版本。"""
    benefits = _validate_benefits(payload.get("benefits", []))
    code = str(payload.get("code", "")).strip()
    name = str(payload.get("name", "")).strip()
    if not code or not name:
        raise _invalid("code", "会员套餐代码和名称不能为空")
    duration_days = int(payload.get("duration_days", 0))
    price_amount_minor = int(payload.get("price_amount_minor", 0))
    if duration_days <= 0:
        raise _invalid("duration_days", "会员套餐有效天数必须大于 0")
    if price_amount_minor <= 0:
        raise _invalid("price_amount_minor", "会员套餐价格必须大于 0")
    with transaction.atomic():
        if MembershipPlan.objects.filter(code=code).exists():
            raise _conflict("会员套餐代码已存在", code=ErrorCode.MEMBERSHIP_IDEMPOTENCY_CONFLICT)
        plan = MembershipPlan.objects.create(
            code=code,
            name=name,
            description=str(payload.get("description", "")).strip(),
            duration_days=duration_days,
            currency=str(payload.get("currency", "CNY")).strip().upper() or "CNY",
            price_amount_minor=price_amount_minor,
            benefits=benefits,
            status=MembershipPlan.Status.DRAFT,
            sort_order=int(payload.get("sort_order", 0)),
            version=1,
            created_by=operator.id,
            updated_by=operator.id,
        )
        version = MembershipPlanVersion.objects.create(
            plan=plan,
            version_no=1,
            name=plan.name,
            description=plan.description,
            duration_days=plan.duration_days,
            currency=plan.currency,
            price_amount_minor=plan.price_amount_minor,
            benefits=plan.benefits,
            effective_at=timezone.now(),
        )
        return plan_version_payload(version)


def update_membership_plan(
    *,
    operator,
    plan_no: str,
    payload: dict[str, Any],
    expected_version: int,
) -> dict[str, Any]:
    """管理员修改会员套餐；价格、时长或权益变化生成新版本。"""
    try:
        plan_uuid = uuid.UUID(str(plan_no))
    except ValueError as exc:
        raise _invalid("plan_no", "会员套餐编号格式不正确") from exc
    with transaction.atomic():
        plan = MembershipPlan.objects.select_for_update().filter(plan_no=plan_uuid).first()
        if plan is None:
            raise _not_found()
        if plan.version != expected_version:
            raise _conflict(
                "会员套餐已被更新，请刷新后重试",
                code=ErrorCode.MEMBERSHIP_VERSION_CONFLICT,
            )
        current_version = _current_plan_version(plan=plan)
        commercial_changed = False
        if "name" in payload:
            plan.name = str(payload["name"]).strip()
        if "description" in payload:
            plan.description = str(payload["description"]).strip()
        if "sort_order" in payload:
            plan.sort_order = int(payload["sort_order"])
        if "status" in payload:
            status = str(payload["status"]).upper()
            if status not in MembershipPlan.Status.values:
                raise _invalid("status", "会员套餐状态不存在")
            plan.status = status
        new_duration_days = int(payload.get("duration_days", plan.duration_days))
        new_price = int(payload.get("price_amount_minor", plan.price_amount_minor))
        new_currency = str(payload.get("currency", plan.currency)).strip().upper() or plan.currency
        new_benefits = (
            _validate_benefits(payload["benefits"])
            if "benefits" in payload
            else current_version.benefits
        )
        if new_duration_days <= 0:
            raise _invalid("duration_days", "会员套餐有效天数必须大于 0")
        if new_price <= 0:
            raise _invalid("price_amount_minor", "会员套餐价格必须大于 0")
        if (
            new_duration_days != current_version.duration_days
            or new_price != current_version.price_amount_minor
            or new_currency != current_version.currency
            or new_benefits != current_version.benefits
            or plan.name != current_version.name
            or plan.description != current_version.description
        ):
            commercial_changed = True
        plan.duration_days = new_duration_days
        plan.price_amount_minor = new_price
        plan.currency = new_currency
        plan.benefits = new_benefits
        plan.updated_by = operator.id
        if commercial_changed:
            plan.version += 1
        plan.save()
        version = current_version
        if commercial_changed:
            version = MembershipPlanVersion.objects.create(
                plan=plan,
                version_no=plan.version,
                name=plan.name,
                description=plan.description,
                duration_days=plan.duration_days,
                currency=plan.currency,
                price_amount_minor=plan.price_amount_minor,
                benefits=plan.benefits,
                effective_at=timezone.now(),
            )
        return plan_version_payload(version)


def list_admin_membership_purchases(
    *,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """分页查询管理员会员购买记录，不提供退款或资金调整操作。"""
    queryset = MembershipPurchase.objects.select_related(
        "plan",
        "plan_version",
    ).order_by("-created_at", "-id")
    if status:
        normalized_status = status.upper()
        if normalized_status not in MembershipPurchase.Status.values:
            raise _invalid("status", "会员购买状态不存在")
        queryset = queryset.filter(status=normalized_status)
    total = queryset.count()
    items = list(queryset[(page - 1) * page_size : page * page_size])
    return {
        "items": [purchase_payload(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
