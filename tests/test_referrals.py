"""分享邀请绑定、链接转化、奖励快照和结算冲减测试。"""

from __future__ import annotations

import uuid

import pytest
from django.db import IntegrityError
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from backend.payouts.models import EarningAccount, EarningEntry
from backend.referrals.admin_services import create_referral_policy
from backend.referrals.models import (
    ReferralAttribution,
    ReferralReward,
    ReferralRewardAdjustment,
    ReferralShareLink,
    ReferralVisit,
)
from backend.referrals.reward_services import (
    active_referral_policy_at,
    apply_refund_to_referral_reward,
    calculate_reward_amount,
    settle_due_referral_rewards,
)
from backend.referrals.services import (
    bind_new_user_referral,
    get_or_create_invite_code,
)
from tests.test_booking_flow import (
    auth_headers,
    create_customer,
    create_provider_fixture,
    create_user,
)

pytestmark = pytest.mark.django_db


def _login_with_referral(
    client: APIClient,
    phone: str,
    invite_code: str,
    *,
    visitor_id: str | None = None,
    share_no: str | None = None,
):
    send = client.post(
        reverse("v1:auth-sms-code"),
        {"phone": phone},
        format="json",
    )
    code = send.json()["data"]["debug_code"]
    return client.post(
        reverse("v1:auth-login"),
        {
            "phone": phone,
            "code": code,
            "referral_context": {
                "invite_code": invite_code,
                "share_no": share_no or "",
                "channel": "POSTER",
                "campaign_code": "LAUNCH",
                "visitor_id": visitor_id or f"visitor-{phone}",
            },
        },
        format="json",
    )


@override_settings(SMS_CODE_RESEND_SECONDS=0)
def test_new_user_binds_unique_referrer_and_existing_user_is_ignored() -> None:
    inviter = create_user("referral-inviter")
    invite_code = get_or_create_invite_code(user=inviter).code
    client = APIClient()

    first = _login_with_referral(client, "13800130001", invite_code)
    second = _login_with_referral(client, "13800130002", invite_code)
    existing_again = client.post(
        reverse("v1:auth-login"),
        {
            "phone": "13800130001",
            "code": client.post(
                reverse("v1:auth-sms-code"),
                {"phone": "13800130001"},
                format="json",
            ).json()["data"]["debug_code"],
            "referral_context": {"invite_code": invite_code},
        },
        format="json",
    )

    assert first.status_code == second.status_code == existing_again.status_code == 200
    assert ReferralAttribution.objects.filter(inviter_user=inviter).count() == 2
    assert existing_again.json()["data"]["is_new_user"] is False


def test_self_invitation_is_rejected_without_creating_relation() -> None:
    user = create_user("referral-self")
    invite_code = get_or_create_invite_code(user=user).code

    result = bind_new_user_referral(
        user=user,
        context={"invite_code": invite_code},
        registration_source="PHONE",
        is_new_user=True,
    )

    assert result["status"] == "SELF_INVITE"
    assert not ReferralAttribution.objects.filter(invitee_user=user).exists()


@override_settings(
    PUBLIC_SHARE_BASE_URL="https://share.example.test",
    SMS_CODE_RESEND_SECONDS=0,
)
def test_share_link_visit_and_overview_count_conversion() -> None:
    inviter = create_user("referral-share-user")
    client = APIClient()
    link_response = client.post(
        reverse("v1:referral-share-links"),
        {"channel": "POSTER", "campaign_code": "POSTER_1"},
        format="json",
        **auth_headers(inviter),
    )
    link = link_response.json()["data"]

    visit = client.post(
        reverse("v1:referral-visits"),
        {"share_no": link["share_no"], "visitor_id": "device-1"},
        format="json",
    )
    login = _login_with_referral(
        client,
        "13800130003",
        link["invite_code"],
        visitor_id="device-1",
        share_no=link["share_no"],
    )
    overview = client.get(reverse("v1:referral-overview"), **auth_headers(inviter))

    assert link_response.status_code == 201
    assert visit.status_code == 201
    assert login.status_code == 200
    assert overview.json()["data"]["registered_count"] == 1
    assert overview.json()["data"]["share_link"]["share_url"].startswith(
        "https://share.example.test/invite/"
    )
    assert ReferralShareLink.objects.filter(user=inviter).count() == 2
    assert ReferralVisit.objects.filter(converted_at__isnull=False).count() == 1


@override_settings(
    REFERRAL_REWARD_DELAY_DAYS=0,
)
def test_order_reward_snapshots_settles_and_refund_recovers() -> None:
    provider, service, slot = create_provider_fixture("referral-reward-provider")
    admin = create_user("referral-reward-admin", is_staff=True)
    inviter = create_user("referral-reward-inviter")
    customer = create_customer("referral-reward-customer", admin)
    invite_code = get_or_create_invite_code(user=inviter).code
    bind_new_user_referral(
        user=customer,
        context={"invite_code": invite_code},
        registration_source="PHONE",
        is_new_user=True,
    )
    create_referral_policy(
        payload={
            "version": 1,
            "name": "测试奖励政策",
            "reward_rate_bps": 1000,
            "funding_cap_to_platform_fee": False,
            "settlement_delay_days": 0,
            "effective_from": timezone.now(),
        },
        operator_user_id=admin.id,
    )
    from tests.test_booking_flow import create_order, pay_order, transition_order

    created = create_order(
        user=customer,
        service_id=str(service.public_id),
        slot_id=str(slot.public_id),
        note="推广奖励测试",
        expected_service_version=service.version,
        expected_slot_version=slot.version,
        idempotency_key="referral-order",
    )
    paid = pay_order(
        user=customer,
        order_no=str(created.order.order_no),
        expected_version=created.order.version,
        idempotency_key="referral-payment",
    )
    accepted = transition_order(
        user=provider,
        order_no=str(created.order.order_no),
        expected_version=paid["order"]["version"],
        action="accept",
    )
    started = transition_order(
        user=provider,
        order_no=str(created.order.order_no),
        expected_version=accepted.version,
        action="start",
    )
    completed_by_provider = transition_order(
        user=provider,
        order_no=str(created.order.order_no),
        expected_version=started.version,
        action="complete",
    )
    transition_order(
        user=customer,
        order_no=str(created.order.order_no),
        expected_version=completed_by_provider.version,
        action="confirm",
    )
    created.order.refresh_from_db()

    reward = ReferralReward.objects.get(order_no=str(created.order.order_no))
    assert reward.amount_minor == 680
    assert reward.reward_base_minor == 6800
    result = settle_due_referral_rewards()

    reward.refresh_from_db()
    account = EarningAccount.objects.get(
        user=inviter,
        account_type=EarningAccount.AccountType.REFERRAL_REWARD,
    )
    assert result["settled"] == 1
    assert reward.status == ReferralReward.Status.SETTLED
    assert account.available_amount_minor == 680
    assert EarningEntry.objects.filter(business_type="REFERRAL_REWARD").count() == 1

    created.order.refunded_amount_minor = created.order.paid_amount_minor
    created.order.save(update_fields=["refunded_amount_minor", "updated_at"])
    apply_refund_to_referral_reward(
        order=created.order,
        refund_no=str(uuid.uuid4()),
        reason="全额退款冲减奖励",
    )

    reward.refresh_from_db()
    account.refresh_from_db()
    assert reward.amount_minor == 0
    assert reward.status == ReferralReward.Status.CANCELED
    assert account.available_amount_minor == 0
    assert ReferralRewardAdjustment.objects.filter(reward=reward).count() == 1


def test_database_rejects_second_attribution_for_same_invitee() -> None:
    first_inviter = create_user("referral-unique-first")
    second_inviter = create_user("referral-unique-second")
    invitee = create_user("referral-unique-invitee")
    first_code = get_or_create_invite_code(user=first_inviter)
    second_code = get_or_create_invite_code(user=second_inviter)
    ReferralAttribution.objects.create(
        invitee_user=invitee,
        inviter_user=first_inviter,
        invite_code=first_code,
        registration_source="PHONE",
    )

    with pytest.raises(IntegrityError):
        ReferralAttribution.objects.create(
            invitee_user=invitee,
            inviter_user=second_inviter,
            invite_code=second_code,
            registration_source="PHONE",
        )


@override_settings(
    REFERRAL_REWARD_RATE_BPS=250,
    REFERRAL_REWARD_MAX_AMOUNT_MINOR=0,
    REFERRAL_REWARD_DELAY_DAYS=3,
)
def test_default_policy_and_reward_rounding_rules() -> None:
    policy = active_referral_policy_at(timezone.now())
    base, amount = calculate_reward_amount(
        paid_amount_minor=999,
        refunded_amount_minor=0,
        reward_rate_bps=250,
        max_reward_amount_minor=1,
        min_order_amount_minor=1000,
        platform_fee_amount_minor=100,
        funding_cap_to_platform_fee=True,
    )

    assert policy is not None
    assert policy.version == 1
    assert policy.reward_rate_bps == 250
    assert policy.max_reward_amount_minor is None
    assert policy.settlement_delay_days == 3
    assert (base, amount) == (999, 0)
