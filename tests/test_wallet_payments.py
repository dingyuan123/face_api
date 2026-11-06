from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from backend.accounts.models import AuthToken, User
from backend.accounts.services import _token_raw, hash_token
from backend.common.errors import ErrorCode
from backend.common.exceptions import ApiError
from backend.payments.models import Payment, Refund
from backend.payments.services import charge_wallet_for_order, refund_wallet_for_payment
from backend.wallets.models import WalletTransaction
from backend.wallets.services import admin_top_up_wallet

pytestmark = pytest.mark.django_db


def create_user(phone_hash: str, *, is_staff: bool = False) -> User:
    return User.objects.create(
        phone_hash=phone_hash,
        phone_masked="138****8000",
        is_staff=is_staff,
    )


def auth_headers(user: User) -> dict[str, str]:
    token_id = uuid.uuid4()
    raw_token = _token_raw(AuthToken.TokenType.ACCESS, token_id)
    AuthToken.objects.create(
        public_id=token_id,
        user=user,
        token_type=AuthToken.TokenType.ACCESS,
        token_hash=hash_token(raw_token),
        expires_at=timezone.now() + timedelta(hours=1),
    )
    return {"HTTP_AUTHORIZATION": f"Bearer {raw_token}"}


def test_admin_can_create_test_topup_but_user_cannot() -> None:
    client = APIClient()
    user = create_user("wallet-user")
    admin = create_user("wallet-admin", is_staff=True)

    denied = client.post(
        reverse("v1:admin-wallet-topups"),
        {
            "target_user_public_id": str(user.public_id),
            "currency": "CNY",
            "amount_minor": 10000,
            "reason": "测试余额",
        },
        format="json",
        **auth_headers(user),
    )
    created = client.post(
        reverse("v1:admin-wallet-topups"),
        {
            "target_user_public_id": str(user.public_id),
            "currency": "CNY",
            "amount_minor": 10000,
            "reason": "测试余额",
        },
        format="json",
        **auth_headers(admin),
    )
    wallet = client.get(reverse("v1:wallet"), **auth_headers(user))

    assert denied.status_code == 403
    assert created.status_code == 201
    assert created.json()["data"]["amount_minor"] == 10000
    assert wallet.json()["data"]["available_amount_minor"] == 10000


def test_wallet_balance_payment_and_refund_are_idempotent() -> None:
    user = create_user("wallet-payment-user")
    admin = create_user("wallet-payment-admin", is_staff=True)
    topup = admin_top_up_wallet(
        target_user=user,
        created_by=admin,
        amount_minor=10000,
        reason="测试余额",
        idempotency_key="topup-1",
    )
    assert topup["amount_minor"] == 10000

    first = charge_wallet_for_order(
        user=user,
        order_no="ORDER-TEST-1",
        amount_minor=6800,
        idempotency_key="payment-1",
    )
    repeated = charge_wallet_for_order(
        user=user,
        order_no="ORDER-TEST-1",
        amount_minor=6800,
        idempotency_key="payment-1",
    )
    refund = refund_wallet_for_payment(
        payment=first.payment,
        refund_amount_minor=6800,
        idempotency_key="refund-1",
    )
    repeated_refund = refund_wallet_for_payment(
        payment=first.payment,
        refund_amount_minor=6800,
        idempotency_key="refund-1",
    )

    assert first.reused is False
    assert repeated.reused is True
    assert first.payment.status == Payment.Status.REFUNDED
    assert refund.id == repeated_refund.id
    assert Payment.objects.count() == 1
    assert Refund.objects.count() == 1
    assert WalletTransaction.objects.count() == 3


@override_settings(ENABLE_DEV_WALLET_TOPUP=False)
def test_development_topup_can_be_disabled() -> None:
    user = create_user("wallet-disabled-user")
    admin = create_user("wallet-disabled-admin", is_staff=True)

    with pytest.raises(ApiError) as error:
        admin_top_up_wallet(
            target_user=user,
            created_by=admin,
            amount_minor=100,
            reason="disabled",
        )
    assert error.value.machine_code == ErrorCode.WALLET_TOPUP_DISABLED
