from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from backend.accounts.models import AuthToken, User
from backend.accounts.services import _token_raw, hash_token
from backend.common.exceptions import ApiError
from backend.orders.models import Order
from backend.payouts.models import EarningAccount, Withdrawal
from backend.payouts.services import (
    approve_withdrawal,
    create_payout_method,
    create_provider_order_earning,
    create_withdrawal,
    earning_account_payload,
    reject_withdrawal,
)
from backend.providers.models import ProviderProfile
from backend.reviews.services import (
    create_review,
    list_my_reviews,
    list_provider_review_management,
    reply_review,
)
from backend.scheduling.models import ScheduleSlot

pytestmark = pytest.mark.django_db


def create_user(phone_hash: str, *, staff: bool = False, provider: bool = False) -> User:
    user = User.objects.create(
        phone_hash=phone_hash,
        phone_masked="138****8000",
        is_staff=staff,
        initial_role_selected=True,
        primary_role=User.InitialRole.PROVIDER if provider else User.InitialRole.USER,
        provider_status=User.ProviderStatus.APPROVED
        if provider
        else User.ProviderStatus.NOT_SUBMITTED,
        provider_enabled=provider,
    )
    if provider:
        ProviderProfile.objects.create(
            user=user,
            nickname=f"u-{phone_hash}"[:20],
            introduction="用于自动化测试的服务者资料说明",
        )
    return user


def auth_headers(user: User) -> dict[str, str]:
    token_public_id = uuid.uuid4()
    token_id = _token_raw(AuthToken.TokenType.ACCESS, token_public_id)
    AuthToken.objects.create(
        public_id=token_public_id,
        user=user,
        token_type=AuthToken.TokenType.ACCESS,
        token_hash=hash_token(token_id),
        expires_at=timezone.now() + timedelta(hours=1),
    )
    return {"HTTP_AUTHORIZATION": f"Bearer {token_id}"}


def create_completed_order(customer: User, provider: User) -> Order:
    start = timezone.now() - timedelta(days=1)
    slot = ScheduleSlot.objects.create(
        provider_user=provider,
        start_at=start,
        end_at=start + timedelta(hours=1),
    )
    return Order.objects.create(
        user=customer,
        provider_user=provider,
        schedule_slot=slot,
        service_snapshot={
            "id": "service-1",
            "title": "测试服务",
            "category_code": "SPORT",
            "currency": "CNY",
            "hourly_amount_minor": 6800,
            "duration_minutes": 60,
            "introduction": "用于评价页展示的测试服务介绍",
            "cover_media_id": None,
        },
        provider_snapshot={},
        slot_snapshot={},
        original_price_amount_minor=10000,
        payable_amount_minor=10000,
        paid_amount_minor=10000,
        status=Order.Status.COMPLETED,
        completed_at=timezone.now() - timedelta(hours=2),
        review_expires_at=timezone.now() + timedelta(days=5),
        request_fingerprint="order-fingerprint",
    )


def test_review_pages_include_pending_reviewed_and_anonymous_privacy() -> None:
    customer = create_user("review-customer")
    provider = create_user("review-provider", provider=True)
    order = create_completed_order(customer, provider)

    pending = list_my_reviews(user=customer, status="ALL")
    assert pending["summary"]["pending_count"] == 1
    assert pending["items"][0]["item_type"] == "PENDING_REVIEW"
    assert pending["items"][0]["service"]["price"]["amount_minor"] == 6800
    assert pending["items"][0]["service"]["duration_minutes"] == 60
    assert pending["items"][0]["provider"]["public_id"] == str(provider.public_id)
    assert pending["items"][0]["provider"]["verification"]["real_name_status"] == "NOT_SUBMITTED"
    assert pending["items"][0]["provider"]["completed_order_count"] == 1

    review = create_review(
        user=customer,
        order_no=str(order.order_no),
        rating=5,
        content="体验很好",
        tag_codes=[],
        is_anonymous=True,
    )
    assert review["user"] is None
    assert review["user_public_id"] is None

    reviewed = list_my_reviews(user=customer, status="REVIEWED")
    assert reviewed["summary"]["reviewed_count"] == 1
    assert reviewed["items"][0]["review"]["rating"] == 5

    duplicate = create_review(
        user=customer,
        order_no=str(order.order_no),
        rating=5,
        content="体验很好",
        tag_codes=[],
        is_anonymous=True,
    )
    assert duplicate["id"] == review["id"]


def test_provider_review_management_and_single_reply_are_safe() -> None:
    customer = create_user("reply-customer")
    provider = create_user("reply-provider", provider=True)
    order = create_completed_order(customer, provider)
    review = create_review(
        user=customer,
        order_no=str(order.order_no),
        rating=4,
        content="不错",
        tag_codes=[],
        is_anonymous=False,
    )

    first = reply_review(
        provider_user=provider,
        review_id=review["id"],
        content="感谢支持",
    )
    assert first["reply"]["content"] == "感谢支持"
    replay = reply_review(
        provider_user=provider,
        review_id=review["id"],
        content="感谢支持",
    )
    assert replay["reply"]["content"] == "感谢支持"

    summary = list_provider_review_management(provider_user=provider, page=1, page_size=20)
    assert summary["total"] == 1
    assert summary["summary"]["reply_count"] == 1
    assert summary["summary"]["rating_distribution"]["4"] == 1
    with pytest.raises(ApiError):
        reply_review(
            provider_user=provider,
            review_id=review["id"],
            content="换一条回复",
        )


def test_provider_income_and_withdrawal_flow_is_idempotent() -> None:
    provider = create_user("income-provider", provider=True)
    admin = create_user("payout-admin", staff=True)
    customer = create_user("income-customer")
    order = create_completed_order(customer, provider)
    order.paid_amount_minor = 10000
    order.refunded_amount_minor = 0
    order.platform_fee_amount_minor = 0
    order.currency = "CNY"
    order.completed_at = timezone.now()

    entry = create_provider_order_earning(order)
    assert entry is not None
    assert entry.net_amount_minor == 10000
    account_payload = earning_account_payload(user=provider, account_type="PROVIDER_INCOME")
    assert account_payload["available_amount_minor"] == 10000

    payout_method = create_payout_method(
        user=provider,
        payload={
            "method_type": "BANK_CARD",
            "account_name": "张三",
            "account_number": "6222021234567890",
            "institution_name": "测试银行",
            "is_default": True,
        },
        idempotency_key="payout-method-1",
    )
    assert "****" in payout_method["account_number_masked"]
    assert "account_number" not in payout_method

    withdrawal = create_withdrawal(
        user=provider,
        account_type="PROVIDER_INCOME",
        amount_minor=5000,
        payout_method_id=payout_method["id"],
        expected_version=account_payload["version"],
        idempotency_key="withdrawal-1",
    )
    assert withdrawal["status"] == "PENDING_REVIEW"
    replay = create_withdrawal(
        user=provider,
        account_type="PROVIDER_INCOME",
        amount_minor=5000,
        payout_method_id=payout_method["id"],
        expected_version=account_payload["version"],
        idempotency_key="withdrawal-1",
    )
    assert replay["reused"] is True
    assert Withdrawal.objects.count() == 1

    result = approve_withdrawal(
        admin_user=admin,
        request_no=withdrawal["withdrawal_no"],
        expected_version=withdrawal["version"],
        idempotency_key="approve-1",
    )
    assert result["status"] == "SUCCESS"
    account = EarningAccount.objects.get(user=provider, account_type="PROVIDER_INCOME")
    assert account.available_amount_minor == 5000
    assert account.frozen_amount_minor == 0
    assert account.total_withdrawn_amount_minor == 5000


def test_referral_account_and_rejected_withdrawal_release_balance() -> None:
    user = create_user("referral-user")
    admin = create_user("reject-admin", staff=True)
    account = EarningAccount.objects.create(
        user=user,
        account_type=EarningAccount.AccountType.REFERRAL_REWARD,
        available_amount_minor=2000,
    )
    payout_method = create_payout_method(
        user=user,
        payload={
            "method_type": "ALIPAY",
            "account_name": "李四",
            "account_number": "alipay-user",
            "institution_name": "",
            "is_default": True,
        },
    )
    withdrawal = create_withdrawal(
        user=user,
        account_type="REFERRAL_REWARD",
        amount_minor=1000,
        payout_method_id=payout_method["id"],
        expected_version=account.version,
    )
    rejected = reject_withdrawal(
        admin_user=admin,
        request_no=withdrawal["withdrawal_no"],
        expected_version=withdrawal["version"],
        review_note="测试拒绝",
        idempotency_key="reject-1",
    )
    assert rejected["status"] == "REJECTED"
    account.refresh_from_db()
    assert account.available_amount_minor == 2000
    assert account.frozen_amount_minor == 0


def test_review_management_api_requires_provider_access() -> None:
    customer = create_user("api-review-customer")
    client = APIClient()
    response = client.get(reverse("v1:provider-review-management"), **auth_headers(customer))
    assert response.status_code == 403
