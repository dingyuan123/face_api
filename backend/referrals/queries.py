"""分享赚钱页和管理员推广数据的只读查询服务。"""

from __future__ import annotations

from typing import Any

from django.db.models import Count, Sum

from backend.accounts.models import User
from backend.referrals.models import (
    OrderReferralSnapshot,
    ReferralAttribution,
    ReferralPolicy,
    ReferralReward,
)
from backend.referrals.services import (
    build_share_url,
    get_or_create_invite_code,
    get_or_create_profile_share_link,
    share_link_payload,
)


def _reward_payload(reward: ReferralReward) -> dict[str, Any]:
    """返回奖励安全摘要和比例快照。"""
    snapshot = reward.snapshot
    return {
        "reward_no": str(reward.reward_no),
        "order_no": reward.order_no,
        "currency": reward.currency,
        "reward_base_minor": reward.reward_base_minor,
        "reward_rate_bps": reward.reward_rate_bps,
        "amount_minor": reward.amount_minor,
        "status": reward.status,
        "settle_after": reward.settle_after,
        "settled_at": reward.settled_at,
        "cancel_reason": reward.cancel_reason,
        "version": reward.version,
        "policy_version": snapshot.policy.version,
        "created_at": reward.created_at,
        "updated_at": reward.updated_at,
    }


def referral_overview(*, user: User) -> dict[str, Any]:
    """返回分享赚钱页的邀请码、链接、转化和奖励汇总。"""
    invite_code = get_or_create_invite_code(user=user)
    share_link = get_or_create_profile_share_link(user=user)
    attributed = ReferralAttribution.objects.filter(inviter_user=user)
    snapshots = OrderReferralSnapshot.objects.filter(
        inviter_user=user,
        order__status="COMPLETED",
    )
    reward_rows = (
        ReferralReward.objects.filter(inviter_user=user)
        .values("status")
        .annotate(count=Count("id"), amount_minor=Sum("amount_minor"))
        .order_by("status")
    )
    return {
        "invite_code": invite_code.code,
        "share_link": share_link_payload(
            share_link,
            build_share_url(user=user, share_link=share_link),
        ),
        "registered_count": attributed.count(),
        "ordered_user_count": snapshots.values("invitee_user").distinct().count(),
        "valid_order_amount_minor": snapshots.aggregate(total=Sum("reward_base_minor"))["total"]
        or 0,
        "reward_summary": {row["status"]: row for row in reward_rows},
    }


def referral_reward_summary(*, user: User) -> dict[str, Any]:
    """返回当前邀请人奖励状态汇总。"""
    rows = (
        ReferralReward.objects.filter(inviter_user=user)
        .values("status")
        .annotate(count=Count("id"), amount_minor=Sum("amount_minor"))
        .order_by("status")
    )
    return {"items": list(rows)}


def list_referral_rewards(
    *,
    user: User,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """分页返回当前邀请人的推广奖励明细。"""
    from backend.referrals.services import _invalid

    queryset = ReferralReward.objects.select_related(
        "snapshot__policy",
        "snapshot__attribution",
    ).filter(inviter_user=user)
    if status:
        if status not in ReferralReward.Status.values:
            raise _invalid("status", "奖励状态不存在")
        queryset = queryset.filter(status=status)
    total = queryset.count()
    start = (page - 1) * page_size
    items = queryset.order_by("-created_at", "-id")[start : start + page_size]
    return {
        "items": [_reward_payload(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def admin_list_attributions(
    *,
    inviter_public_id: str | None = None,
    risk_status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """管理员分页查询邀请归因和风险状态。"""
    from backend.referrals.services import _invalid

    queryset = ReferralAttribution.objects.select_related(
        "invitee_user",
        "inviter_user",
        "invite_code",
        "share_link",
    )
    if inviter_public_id:
        queryset = queryset.filter(inviter_user__public_id=inviter_public_id)
    if risk_status:
        if risk_status not in ReferralAttribution.RiskStatus.values:
            raise _invalid("risk_status", "风险状态不存在")
        queryset = queryset.filter(risk_status=risk_status)
    total = queryset.count()
    start = (page - 1) * page_size
    items = queryset.order_by("-bound_at", "-id")[start : start + page_size]
    return {
        "items": [
            {
                "invitee_user_public_id": str(item.invitee_user.public_id),
                "inviter_user_public_id": str(item.inviter_user.public_id),
                "invite_code": item.invite_code.code,
                "share_no": str(item.share_link.share_no) if item.share_link else None,
                "registration_source": item.registration_source,
                "source_channel": item.source_channel,
                "campaign_code": item.campaign_code,
                "risk_status": item.risk_status,
                "risk_reason": item.risk_reason,
                "bound_at": item.bound_at,
            }
            for item in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def admin_list_rewards(
    *,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """管理员分页查询推广奖励。"""
    from backend.referrals.services import _invalid

    queryset = ReferralReward.objects.select_related(
        "snapshot__policy",
        "snapshot__attribution",
        "inviter_user",
    )
    if status:
        if status not in ReferralReward.Status.values:
            raise _invalid("status", "奖励状态不存在")
        queryset = queryset.filter(status=status)
    total = queryset.count()
    start = (page - 1) * page_size
    items = queryset.order_by("-created_at", "-id")[start : start + page_size]
    return {
        "items": [_reward_payload(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def list_referral_policies() -> list[dict[str, Any]]:
    """返回全部奖励政策版本，按版本倒序。"""
    return [
        {
            "policy_no": str(item.policy_no),
            "version": item.version,
            "name": item.name,
            "status": item.status,
            "reward_rate_bps": item.reward_rate_bps,
            "max_reward_amount_minor": item.max_reward_amount_minor,
            "min_order_amount_minor": item.min_order_amount_minor,
            "funding_cap_to_platform_fee": item.funding_cap_to_platform_fee,
            "settlement_delay_days": item.settlement_delay_days,
            "effective_from": item.effective_from,
            "effective_to": item.effective_to,
            "created_at": item.created_at,
        }
        for item in ReferralPolicy.objects.order_by("-version")
    ]
