"""推广奖励政策版本和奖励人工状态调整业务服务。"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.payouts.services import adjust_earning_account
from backend.referrals.models import (
    ReferralPolicy,
    ReferralReward,
    ReferralRewardAdjustment,
)
from backend.referrals.reward_services import _fingerprint, _record_status


def create_referral_policy(
    *,
    payload: dict[str, Any],
    operator_user_id: int | None = None,
) -> ReferralPolicy:
    """创建不可变奖励政策版本。"""
    version = int(payload.get("version") or 0)
    rate_bps = int(payload.get("reward_rate_bps") or 0)
    if version <= 0:
        raise ApiError(
            ErrorCode.REFERRAL_INVALID,
            "政策版本必须大于 0",
            status_code=400,
            details={"field": "version"},
        )
    if not 0 <= rate_bps <= 10000:
        raise ApiError(
            ErrorCode.REFERRAL_INVALID,
            "奖励比例必须在 0 到 10000 万分比之间",
            status_code=400,
            details={"field": "reward_rate_bps"},
        )
    effective_from = payload.get("effective_from")
    if effective_from is None:
        raise ApiError(
            ErrorCode.REFERRAL_INVALID,
            "政策生效时间不能为空",
            status_code=400,
            details={"field": "effective_from"},
        )
    try:
        max_reward = payload.get("max_reward_amount_minor")
        if "max_reward_amount_minor" not in payload:
            configured_max = settings.REFERRAL_REWARD_MAX_AMOUNT_MINOR
            max_reward = None if configured_max == 0 else configured_max
        return ReferralPolicy.objects.create(
            version=version,
            name=str(payload.get("name") or f"推广奖励政策 V{version}"),
            status=ReferralPolicy.Status.ACTIVE,
            reward_rate_bps=rate_bps,
            max_reward_amount_minor=max_reward,
            min_order_amount_minor=int(payload.get("min_order_amount_minor") or 0),
            funding_cap_to_platform_fee=bool(
                payload.get(
                    "funding_cap_to_platform_fee",
                    settings.REFERRAL_REWARD_FUNDING_CAP_TO_PLATFORM_FEE,
                )
            ),
            settlement_delay_days=int(
                payload.get("settlement_delay_days", settings.REFERRAL_REWARD_DELAY_DAYS)
            ),
            effective_from=effective_from,
            effective_to=payload.get("effective_to"),
            created_by_user_id=operator_user_id,
        )
    except IntegrityError as exc:
        raise ApiError(
            ErrorCode.REFERRAL_POLICY_CONFLICT,
            ERROR_MESSAGES[ErrorCode.REFERRAL_POLICY_CONFLICT],
            status_code=409,
        ) from exc


def retire_referral_policy(*, policy_no: str) -> ReferralPolicy:
    """停止政策用于新订单，历史订单保留原快照。"""
    policy = ReferralPolicy.objects.filter(policy_no=policy_no).first()
    if policy is None:
        raise ApiError(
            ErrorCode.REFERRAL_POLICY_NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.REFERRAL_POLICY_NOT_FOUND],
            status_code=404,
        )
    if policy.status != ReferralPolicy.Status.RETIRED:
        policy.status = ReferralPolicy.Status.RETIRED
        if policy.effective_to is None:
            policy.effective_to = timezone.now()
        policy.save(update_fields=["status", "effective_to"])
    return policy


def change_referral_reward_state(
    *,
    reward_no: str,
    action: str,
    expected_version: int,
    reason: str,
    operator_user_id: int | None = None,
) -> ReferralReward:
    """冻结、解冻或取消奖励，使用乐观锁防止并发覆盖。"""
    if len(reason.strip()) < 2:
        raise ApiError(
            ErrorCode.REFERRAL_INVALID,
            "操作原因至少 2 个字符",
            status_code=400,
            details={"field": "reason"},
        )
    with transaction.atomic():
        reward = (
            ReferralReward.objects.select_for_update()
            .select_related("snapshot__policy")
            .filter(reward_no=reward_no)
            .first()
        )
        if reward is None:
            raise ApiError(
                ErrorCode.REFERRAL_NOT_FOUND,
                "推广奖励不存在",
                status_code=404,
            )
        if reward.version != expected_version:
            raise ApiError(
                ErrorCode.REFERRAL_REWARD_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.REFERRAL_REWARD_VERSION_CONFLICT],
                status_code=409,
            )
        if reward.status == ReferralReward.Status.CANCELED:
            raise ApiError(
                ErrorCode.REFERRAL_REWARD_STATE_INVALID,
                ERROR_MESSAGES[ErrorCode.REFERRAL_REWARD_STATE_INVALID],
                status_code=409,
            )
        previous_status = reward.status
        if action == "freeze":
            allowed = {ReferralReward.Status.PENDING_SETTLEMENT, ReferralReward.Status.FROZEN}
            if reward.status not in allowed:
                raise ApiError(
                    ErrorCode.REFERRAL_REWARD_STATE_INVALID,
                    ERROR_MESSAGES[ErrorCode.REFERRAL_REWARD_STATE_INVALID],
                    status_code=409,
                )
            reward.status = ReferralReward.Status.FROZEN
        elif action == "unfreeze":
            if reward.status != ReferralReward.Status.FROZEN:
                raise ApiError(
                    ErrorCode.REFERRAL_REWARD_STATE_INVALID,
                    ERROR_MESSAGES[ErrorCode.REFERRAL_REWARD_STATE_INVALID],
                    status_code=409,
                )
            reward.status = ReferralReward.Status.PENDING_SETTLEMENT
        elif action == "cancel":
            if reward.status in {
                ReferralReward.Status.SETTLED,
                ReferralReward.Status.CANCELED,
            }:
                raise ApiError(
                    ErrorCode.REFERRAL_REWARD_STATE_INVALID,
                    ERROR_MESSAGES[ErrorCode.REFERRAL_REWARD_STATE_INVALID],
                    status_code=409,
                )
            reward.status = ReferralReward.Status.CANCELED
        else:
            raise ApiError(
                ErrorCode.REFERRAL_INVALID,
                "奖励操作不存在",
                status_code=400,
                details={"field": "action"},
            )
        reward.cancel_reason = reason
        reward.version = F("version") + 1
        reward.save(update_fields=["status", "cancel_reason", "version", "updated_at"])
        reward.refresh_from_db()
        _record_status(
            reward=reward,
            from_status=previous_status,
            to_status=reward.status,
            reason=reason,
            operator_user_id=operator_user_id,
        )
        return reward


def adjust_referral_reward(
    *,
    reward_no: str,
    expected_version: int,
    amount_delta_minor: int,
    reason: str,
    idempotency_key: str,
    operator_user_id: int | None = None,
) -> ReferralReward:
    """人工调整未结算奖励；已结算奖励同步调整推广收益账户。"""
    if amount_delta_minor == 0:
        raise ApiError(
            ErrorCode.REFERRAL_INVALID,
            "奖励调整金额不能为零",
            status_code=400,
            details={"field": "amount_delta_minor"},
        )
    if len(reason.strip()) < 2 or len(idempotency_key) > 128:
        raise ApiError(
            ErrorCode.REFERRAL_INVALID,
            "调整原因或幂等键不正确",
            status_code=400,
        )
    with transaction.atomic():
        reward = ReferralReward.objects.select_for_update().filter(reward_no=reward_no).first()
        if reward is None:
            raise ApiError(ErrorCode.REFERRAL_NOT_FOUND, "推广奖励不存在", status_code=404)
        if reward.version != expected_version:
            raise ApiError(
                ErrorCode.REFERRAL_REWARD_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.REFERRAL_REWARD_VERSION_CONFLICT],
                status_code=409,
            )
        fingerprint = _fingerprint(
            {
                "reward_no": str(reward.reward_no),
                "amount_delta_minor": amount_delta_minor,
                "reason": reason,
            }
        )
        try:
            adjustment = ReferralRewardAdjustment.objects.create(
                reward=reward,
                adjustment_type=ReferralRewardAdjustment.Type.MANUAL_CORRECTION,
                amount_delta_minor=amount_delta_minor,
                reason=reason,
                operator_user_id=operator_user_id,
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
            )
        except IntegrityError as exc:
            existing = ReferralRewardAdjustment.objects.filter(
                reward=reward, idempotency_key=idempotency_key
            ).first()
            if existing and existing.request_fingerprint == fingerprint:
                return reward
            raise ApiError(
                ErrorCode.REFERRAL_INVALID,
                "奖励调整幂等请求与原请求不一致",
                status_code=409,
            ) from exc
        new_amount = reward.amount_minor + amount_delta_minor
        if new_amount < 0:
            raise ApiError(
                ErrorCode.REFERRAL_INVALID,
                "调整后奖励金额不能为负数",
                status_code=400,
                details={"field": "amount_delta_minor"},
            )
        previous_status = reward.status
        if reward.status == ReferralReward.Status.SETTLED:
            adjust_earning_account(
                user=reward.inviter_user,
                account_type="REFERRAL_REWARD",
                currency=reward.currency,
                business_type="REFERRAL_REWARD_ADJUSTMENT",
                business_no=str(adjustment.adjustment_no),
                amount_minor=abs(amount_delta_minor),
                direction="CREDIT" if amount_delta_minor > 0 else "DEBIT",
                idempotency_key=f"referral-adjustment:{adjustment.adjustment_no}",
                request_fingerprint=fingerprint,
                reason=reason,
            )
        reward.amount_minor = new_amount
        if new_amount == 0 and reward.status != ReferralReward.Status.SETTLED:
            reward.status = ReferralReward.Status.CANCELED
            reward.cancel_reason = reason
        reward.version = F("version") + 1
        reward.save(
            update_fields=[
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
