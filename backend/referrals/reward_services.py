"""订单推广奖励快照、完成生成、退款冲减和到期结算业务服务。"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from backend.common.context import current_trace_id
from backend.common.crypto import sensitive_fingerprint
from backend.payouts.services import (
    adjust_earning_account,
    create_referral_reward_earning,
)
from backend.referrals.models import (
    OrderReferralSnapshot,
    ReferralAttribution,
    ReferralPolicy,
    ReferralReward,
    ReferralRewardAdjustment,
    ReferralRewardStatusLog,
)


def _fingerprint(payload: dict[str, Any]) -> str:
    """计算奖励写请求一致性摘要。"""
    return sensitive_fingerprint(payload)


def _record_status(
    *,
    reward: ReferralReward,
    from_status: str,
    to_status: str,
    reason: str,
    operator_user_id: int | None = None,
) -> None:
    """记录奖励状态变化审计。"""
    ReferralRewardStatusLog.objects.create(
        reward=reward,
        from_status=from_status,
        to_status=to_status,
        reason=reason,
        operator_user_id=operator_user_id,
        trace_id=current_trace_id(),
    )


def active_referral_policy_at(value: timezone.datetime) -> ReferralPolicy | None:
    """查询指定时间生效的奖励政策版本。"""
    policy = (
        ReferralPolicy.objects.filter(
            status=ReferralPolicy.Status.ACTIVE,
            effective_from__lte=value,
        )
        .filter(models_q_effective_to(value))
        .order_by("-version")
        .first()
    )
    if policy is not None:
        return policy
    return _ensure_default_referral_policy(value)


def _ensure_default_referral_policy(value: timezone.datetime) -> ReferralPolicy | None:
    """在尚未配置政策时创建零比例启动版本，避免支付流程无快照可追溯。"""
    from django.conf import settings

    effective_from = min(value, timezone.now())
    max_reward = settings.REFERRAL_REWARD_MAX_AMOUNT_MINOR
    try:
        with transaction.atomic():
            policy, _ = ReferralPolicy.objects.get_or_create(
                version=1,
                defaults={
                    "name": "启动默认推广奖励政策 V1",
                    "status": ReferralPolicy.Status.ACTIVE,
                    "reward_rate_bps": settings.REFERRAL_REWARD_RATE_BPS,
                    "max_reward_amount_minor": None if max_reward == 0 else max_reward,
                    "min_order_amount_minor": 0,
                    "funding_cap_to_platform_fee": (
                        settings.REFERRAL_REWARD_FUNDING_CAP_TO_PLATFORM_FEE
                    ),
                    "settlement_delay_days": settings.REFERRAL_REWARD_DELAY_DAYS,
                    "effective_from": effective_from,
                },
            )
            return policy
    except IntegrityError:
        return ReferralPolicy.objects.filter(version=1).first()


def models_q_effective_to(value: timezone.datetime):
    """构造政策结束时间为空或晚于查询时点的条件。"""
    from django.db.models import Q

    return Q(effective_to__isnull=True) | Q(effective_to__gt=value)


def calculate_reward_amount(
    *,
    paid_amount_minor: int,
    refunded_amount_minor: int,
    reward_rate_bps: int,
    max_reward_amount_minor: int | None,
    min_order_amount_minor: int,
    platform_fee_amount_minor: int,
    funding_cap_to_platform_fee: bool,
) -> tuple[int, int]:
    """按整数分向下取整计算奖励基数和奖励金额。"""
    base = max(0, int(paid_amount_minor) - int(refunded_amount_minor))
    if base < max(0, int(min_order_amount_minor)):
        return base, 0
    amount = base * int(reward_rate_bps) // 10000
    if max_reward_amount_minor is not None:
        amount = min(amount, max(0, int(max_reward_amount_minor)))
    if funding_cap_to_platform_fee:
        amount = min(amount, max(0, int(platform_fee_amount_minor)))
    return base, max(0, amount)


def _calculate_from_snapshot(snapshot: OrderReferralSnapshot) -> tuple[int, int]:
    """依据订单当前退款金额重新计算奖励。"""
    return calculate_reward_amount(
        paid_amount_minor=snapshot.paid_amount_minor,
        refunded_amount_minor=snapshot.refunded_amount_minor,
        reward_rate_bps=snapshot.reward_rate_bps,
        max_reward_amount_minor=snapshot.max_reward_amount_minor,
        min_order_amount_minor=snapshot.policy.min_order_amount_minor,
        platform_fee_amount_minor=getattr(
            snapshot.order,
            "platform_commission_amount_minor",
            snapshot.order.platform_fee_amount_minor,
        ),
        funding_cap_to_platform_fee=snapshot.policy.funding_cap_to_platform_fee,
    )


def create_order_referral_snapshot(*, order: Any) -> OrderReferralSnapshot | None:
    """订单支付成功时幂等锁定邀请关系和奖励政策。"""
    existing = OrderReferralSnapshot.objects.filter(order=order).first()
    if existing:
        return existing
    attribution = (
        ReferralAttribution.objects.filter(invitee_user=order.user)
        .select_related("inviter_user")
        .first()
    )
    if attribution is None:
        return None
    policy = active_referral_policy_at(order.paid_at or timezone.now())
    if policy is None:
        return None
    base, amount = calculate_reward_amount(
        paid_amount_minor=order.paid_amount_minor,
        refunded_amount_minor=order.refunded_amount_minor,
        reward_rate_bps=policy.reward_rate_bps,
        max_reward_amount_minor=policy.max_reward_amount_minor,
        min_order_amount_minor=policy.min_order_amount_minor,
        platform_fee_amount_minor=getattr(
            order,
            "platform_commission_amount_minor",
            order.platform_fee_amount_minor,
        ),
        funding_cap_to_platform_fee=policy.funding_cap_to_platform_fee,
    )
    try:
        snapshot, _ = OrderReferralSnapshot.objects.get_or_create(
            order=order,
            defaults={
                "attribution": attribution,
                "policy": policy,
                "inviter_user": attribution.inviter_user,
                "invitee_user": order.user,
                "currency": order.currency,
                "paid_amount_minor": order.paid_amount_minor,
                "refunded_amount_minor": order.refunded_amount_minor,
                "reward_base_minor": base,
                "reward_rate_bps": policy.reward_rate_bps,
                "max_reward_amount_minor": policy.max_reward_amount_minor,
                "expected_reward_amount_minor": amount,
            },
        )
        return snapshot
    except IntegrityError:
        return OrderReferralSnapshot.objects.filter(order=order).first()


def create_referral_reward_for_completed_order(*, order: Any) -> ReferralReward | None:
    """订单确认完成后幂等创建待结算或冻结奖励。"""
    snapshot = create_order_referral_snapshot(order=order)
    if snapshot is None:
        return None
    existing = ReferralReward.objects.filter(snapshot=snapshot).first()
    if existing:
        return existing
    base, amount = _calculate_from_snapshot(snapshot)
    if amount <= 0:
        return None
    risk_frozen = snapshot.attribution.risk_status != ReferralAttribution.RiskStatus.CLEAR
    status = (
        ReferralReward.Status.FROZEN if risk_frozen else ReferralReward.Status.PENDING_SETTLEMENT
    )
    settle_after = (order.completed_at or timezone.now()) + timedelta(
        days=snapshot.policy.settlement_delay_days
    )
    try:
        with transaction.atomic():
            reward = ReferralReward.objects.create(
                snapshot=snapshot,
                order_no=str(order.order_no),
                inviter_user=snapshot.inviter_user,
                currency=snapshot.currency,
                reward_base_minor=base,
                reward_rate_bps=snapshot.reward_rate_bps,
                amount_minor=amount,
                status=status,
                settle_after=settle_after,
                cancel_reason=snapshot.attribution.risk_reason if risk_frozen else "",
            )
            _record_status(
                reward=reward,
                from_status="",
                to_status=status,
                reason="订单完成生成推广奖励",
            )
            return reward
    except IntegrityError:
        return ReferralReward.objects.filter(snapshot=snapshot).first()


def apply_refund_to_referral_reward(
    *,
    order: Any,
    refund_no: str,
    operator_user_id: int | None = None,
    reason: str = "订单退款重算",
) -> ReferralReward | None:
    """退款成功后重算奖励；已结算奖励生成追回或补发调整。"""
    snapshot = (
        OrderReferralSnapshot.objects.select_related("policy", "attribution")
        .filter(order=order)
        .first()
    )
    if snapshot is None:
        return None
    with transaction.atomic():
        snapshot = OrderReferralSnapshot.objects.select_for_update().get(pk=snapshot.pk)
        reward = ReferralReward.objects.select_for_update().filter(snapshot=snapshot).first()
        if reward is None:
            return None
        snapshot.refunded_amount_minor = order.refunded_amount_minor
        new_base, new_amount = _calculate_from_snapshot(snapshot)
        previous_amount = reward.amount_minor
        delta = new_amount - previous_amount
        snapshot.reward_base_minor = new_base
        snapshot.expected_reward_amount_minor = new_amount
        snapshot.save(
            update_fields=[
                "refunded_amount_minor",
                "reward_base_minor",
                "expected_reward_amount_minor",
                "updated_at",
            ]
        )
        fingerprint = _fingerprint(
            {
                "reward_no": str(reward.reward_no),
                "refund_no": refund_no,
                "new_amount_minor": new_amount,
            }
        )
        try:
            adjustment = ReferralRewardAdjustment.objects.create(
                reward=reward,
                adjustment_type=(
                    ReferralRewardAdjustment.Type.SETTLED_RECOVERY
                    if reward.status == ReferralReward.Status.SETTLED
                    else ReferralRewardAdjustment.Type.REFUND_RECALC
                ),
                amount_delta_minor=delta,
                reason=reason,
                operator_user_id=operator_user_id,
                idempotency_key=f"refund:{refund_no}",
                request_fingerprint=fingerprint,
            )
        except IntegrityError:
            return reward
        previous_status = reward.status
        reward.reward_base_minor = new_base
        reward.amount_minor = new_amount
        was_settled = reward.status == ReferralReward.Status.SETTLED
        if was_settled and delta != 0:
            adjust_earning_account(
                user=reward.inviter_user,
                account_type="REFERRAL_REWARD",
                currency=reward.currency,
                business_type="REFERRAL_REWARD_ADJUSTMENT",
                business_no=str(adjustment.adjustment_no),
                amount_minor=abs(delta),
                direction="CREDIT" if delta > 0 else "DEBIT",
                idempotency_key=f"referral-adjustment:{adjustment.adjustment_no}",
                request_fingerprint=fingerprint,
                reason=reason,
            )
        if new_amount == 0:
            reward.status = ReferralReward.Status.CANCELED
            reward.cancel_reason = reason
        reward.version = F("version") + 1
        reward.save(
            update_fields=[
                "reward_base_minor",
                "amount_minor",
                "status",
                "cancel_reason",
                "version",
                "updated_at",
            ]
        )
        reward.refresh_from_db()
        if previous_status != reward.status:
            _record_status(
                reward=reward,
                from_status=previous_status,
                to_status=reward.status,
                reason=reason,
                operator_user_id=operator_user_id,
            )
        return reward


def settle_due_referral_rewards(*, limit: int = 100) -> dict[str, int]:
    """结算到期奖励并写入推广收益账户。"""
    settled = frozen = canceled = 0
    now = timezone.now()
    with transaction.atomic():
        rewards = list(
            ReferralReward.objects.select_for_update()
            .select_related("snapshot__policy", "snapshot__attribution", "inviter_user")
            .filter(status=ReferralReward.Status.PENDING_SETTLEMENT, settle_after__lte=now)
            .order_by("settle_after", "id")[:limit]
        )
        for reward in rewards:
            snapshot = reward.snapshot
            snapshot.refunded_amount_minor = snapshot.order.refunded_amount_minor
            base, amount = _calculate_from_snapshot(snapshot)
            snapshot.reward_base_minor = base
            snapshot.expected_reward_amount_minor = amount
            snapshot.save(
                update_fields=[
                    "refunded_amount_minor",
                    "reward_base_minor",
                    "expected_reward_amount_minor",
                    "updated_at",
                ]
            )
            previous_status = reward.status
            if snapshot.attribution.risk_status != ReferralAttribution.RiskStatus.CLEAR:
                reward.status = ReferralReward.Status.FROZEN
                reward.cancel_reason = snapshot.attribution.risk_reason or "归因待风险复核"
                frozen += 1
            elif amount <= 0:
                reward.status = ReferralReward.Status.CANCELED
                reward.amount_minor = 0
                reward.reward_base_minor = base
                reward.cancel_reason = "退款后奖励金额为零"
                canceled += 1
            else:
                entry = create_referral_reward_earning(
                    user=reward.inviter_user,
                    reward_no=str(reward.reward_no),
                    currency=reward.currency,
                    gross_amount_minor=base,
                    net_amount_minor=amount,
                    available_at=now,
                    rule_snapshot={
                        "policy_no": str(snapshot.policy.policy_no),
                        "policy_version": snapshot.policy.version,
                        "reward_rate_bps": snapshot.reward_rate_bps,
                        "reward_base_minor": base,
                        "order_no": reward.order_no,
                    },
                    idempotency_key=f"referral-reward:{reward.reward_no}",
                    request_fingerprint=_fingerprint(
                        {
                            "reward_no": str(reward.reward_no),
                            "amount_minor": amount,
                            "reward_base_minor": base,
                        }
                    ),
                )
                reward.status = ReferralReward.Status.SETTLED
                reward.amount_minor = amount
                reward.reward_base_minor = base
                reward.earning_business_no = str(entry.earning_no)
                reward.settled_at = entry.settled_at or now
                settled += 1
            reward.version = F("version") + 1
            reward.save(
                update_fields=[
                    "status",
                    "amount_minor",
                    "reward_base_minor",
                    "earning_business_no",
                    "settled_at",
                    "cancel_reason",
                    "version",
                    "updated_at",
                ]
            )
            reward.refresh_from_db()
            _record_status(
                reward=reward,
                from_status=previous_status,
                to_status=reward.status,
                reason="奖励结算任务",
            )
    return {"settled": settled, "frozen": frozen, "canceled": canceled}
