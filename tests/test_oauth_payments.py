"""第三方登录、手机号安全合并和外部支付回调的核心测试。"""

from __future__ import annotations

import time
from dataclasses import replace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from backend.accounts.models import User, UserAuth
from backend.accounts.services import (
    bind_phone_to_account,
    hash_phone,
    login_with_oauth,
    send_sms_code,
)
from backend.common.errors import ErrorCode
from backend.common.exceptions import ApiError
from backend.integrations.oauth.apple import AppleLoginProvider
from backend.integrations.oauth.contracts import OAuthIdentity, OAuthProviderError
from backend.integrations.oauth.wechat import WeChatLoginProvider
from backend.integrations.payments.contracts import PaymentNotification
from backend.orders.models import Order
from backend.orders.services import (
    approve_order_refund_request,
    create_order,
    create_order_refund_request,
    pay_order,
)
from backend.payments.models import Payment
from backend.payments.services import handle_payment_notification, register_refund
from tests.test_booking_flow import create_provider_fixture

pytestmark = pytest.mark.django_db


def test_oauth_login_requires_phone_binding_then_binds_new_phone() -> None:
    login = login_with_oauth(
        identity=OAuthIdentity(
            provider="WECHAT",
            subject="oauth-subject-1",
            open_id="open-id-1",
        ),
        idempotency_key="oauth-login-1",
    )
    user = User.objects.get(public_id=login.user_public_id)

    assert login.requires_phone_binding is True
    assert user.phone_hash is None

    sms = send_sms_code(
        phone_value="13800138001",
        idempotency_key="oauth-sms-1",
    )
    binding = bind_phone_to_account(
        user=user,
        phone_value="13800138001",
        code_value=sms.debug_code or "",
        idempotency_key="oauth-bind-1",
    )

    user.refresh_from_db()
    assert binding.merged is False
    assert binding.login.requires_phone_binding is False
    assert user.phone_hash == hash_phone("13800138001")


def test_empty_oauth_account_can_merge_into_registered_phone_account() -> None:
    target = User.objects.create(
        phone_hash=hash_phone("13800138002"),
        phone_masked="138****8002",
        status=User.Status.ACTIVE,
    )
    UserAuth.objects.create(
        user=target,
        auth_type=UserAuth.Type.PHONE,
        auth_identifier=hash_phone("13800138002"),
    )
    oauth_login = login_with_oauth(
        identity=OAuthIdentity(provider="APPLE", subject="apple-empty-account"),
        idempotency_key="oauth-login-2",
    )
    oauth_user = User.objects.get(public_id=oauth_login.user_public_id)
    sms = send_sms_code(
        phone_value="13800138002",
        idempotency_key="oauth-sms-2",
    )

    result = bind_phone_to_account(
        user=oauth_user,
        phone_value="13800138002",
        code_value=sms.debug_code or "",
        idempotency_key="oauth-bind-2",
    )

    oauth_user.refresh_from_db()
    assert result.merged is True
    assert result.login.user_public_id == str(target.public_id)
    assert oauth_user.status == User.Status.LOGOFF
    assert target.auths.filter(auth_type=UserAuth.Type.APPLE).exists()


def test_oauth_account_with_business_data_is_not_implicitly_merged() -> None:
    target = User.objects.create(
        phone_hash=hash_phone("13800138003"),
        phone_masked="138****8003",
        status=User.Status.ACTIVE,
    )
    UserAuth.objects.create(
        user=target,
        auth_type=UserAuth.Type.PHONE,
        auth_identifier=hash_phone("13800138003"),
    )
    oauth_user = User.objects.create(phone_hash=None, phone_masked="")
    UserAuth.objects.create(
        user=oauth_user,
        auth_type=UserAuth.Type.WECHAT,
        auth_identifier="wechat-with-data",
    )
    User.objects.filter(pk=oauth_user.pk).update(last_login_at=None)
    from backend.social.models import UserFollow

    UserFollow.objects.create(follower=oauth_user, followed=target)
    sms = send_sms_code(
        phone_value="13800138003",
        idempotency_key="oauth-sms-3",
    )

    with pytest.raises(ApiError) as error:
        bind_phone_to_account(
            user=oauth_user,
            phone_value="13800138003",
            code_value=sms.debug_code or "",
            idempotency_key="oauth-bind-3",
        )

    assert error.value.machine_code == ErrorCode.AUTH_ACCOUNT_MERGE_CONFLICT
    assert target.auths.filter(auth_type=UserAuth.Type.APPLE).exists() is False


def test_apple_identity_token_checks_nonce_and_audience(monkeypatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(
        {
            "iss": "https://appleid.apple.com",
            "aud": "com.example.jianmianliao",
            "sub": "apple-user-1",
            "nonce": "expected-nonce",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
        },
        private_key,
        algorithm="RS256",
    )

    class FakeJwkClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def get_signing_key_from_jwt(self, _token: str):
            return type(
                "SigningKey",
                (),
                {"key": private_key.public_key()},
            )()

    monkeypatch.setattr("backend.integrations.oauth.apple.PyJWKClient", FakeJwkClient)
    with override_settings(APPLE_CLIENT_ID="com.example.jianmianliao"):
        identity = AppleLoginProvider().verify(
            identity_token=token,
            nonce="expected-nonce",
        )
        with pytest.raises(OAuthProviderError):
            AppleLoginProvider().verify(
                identity_token=token,
                nonce="wrong-nonce",
            )

    assert identity.subject == "apple-user-1"


def test_wechat_provider_uses_server_side_code_exchange(monkeypatch) -> None:
    captured = {}

    def fake_get_json(_self, url, params):
        captured["url"] = url
        captured["params"] = params
        return {"openid": "wx-open-id", "unionid": "wx-union-id"}

    monkeypatch.setattr(WeChatLoginProvider, "_get_json", fake_get_json)
    with override_settings(
        WECHAT_LOGIN_APP_ID="wx-app-id",
        WECHAT_LOGIN_APP_SECRET="wx-secret",
    ):
        identity = WeChatLoginProvider().verify(code="temporary-code", state="state")

    assert identity.open_id == "wx-open-id"
    assert identity.union_id == "wx-union-id"
    assert captured["params"]["code"] == "temporary-code"
    assert captured["url"].endswith("/sns/oauth2/access_token")


@override_settings(PAYMENT_GATEWAY_MODE="MOCK")
def test_wechat_app_payment_callback_confirms_order_idempotently() -> None:
    _provider, service, slot = create_provider_fixture("external-payment-provider")
    customer = User.objects.create(
        phone_hash=hash_phone("13800138004"),
        phone_masked="138****8004",
        initial_role_selected=True,
    )
    created = create_order(
        user=customer,
        service_id=str(service.public_id),
        slot_id=str(slot.public_id),
        note="外部支付测试",
        expected_service_version=service.version,
        expected_slot_version=slot.version,
        idempotency_key="external-order-1",
    )
    paid = pay_order(
        user=customer,
        order_no=str(created.order.order_no),
        expected_version=created.order.version,
        payment_method=Payment.Method.WECHAT_APP,
        idempotency_key="external-payment-1",
    )
    payment = Payment.objects.get(payment_no=paid["payment"]["payment_no"])
    client = APIClient()
    callback_payload = {
        "event_type": "TRANSACTION.SUCCESS",
        "out_trade_no": payment.payment_no.hex,
        "transaction_no": "wechat-transaction-1",
        "amount_minor": payment.amount_minor,
        "channel_status": "SUCCESS",
        "success": True,
    }

    first = client.post(
        reverse("v1:payment-wechat-notify"),
        callback_payload,
        format="json",
    )
    repeated = client.post(
        reverse("v1:payment-wechat-notify"),
        callback_payload,
        format="json",
    )

    payment.refresh_from_db()
    created.order.refresh_from_db()
    assert first.status_code == 200
    assert repeated.status_code == 200
    assert paid["payment_action"] == "NATIVE_PAY"
    assert paid["order"]["status"] == "PENDING_PAYMENT"
    assert payment.status == Payment.Status.SUCCESS
    assert created.order.status == Order.Status.PENDING_ACCEPT


@override_settings(PAYMENT_GATEWAY_MODE="MOCK")
def test_external_refund_uses_original_payment_channel() -> None:
    _provider, service, slot = create_provider_fixture("external-refund-provider")
    customer = User.objects.create(
        phone_hash=hash_phone("13800138005"),
        phone_masked="138****8005",
        initial_role_selected=True,
    )
    created = create_order(
        user=customer,
        service_id=str(service.public_id),
        slot_id=str(slot.public_id),
        note="外部退款测试",
        expected_service_version=service.version,
        expected_slot_version=slot.version,
        idempotency_key="external-refund-order",
    )
    paid = pay_order(
        user=customer,
        order_no=str(created.order.order_no),
        expected_version=created.order.version,
        payment_method=Payment.Method.ALIPAY_APP,
        idempotency_key="external-refund-payment",
    )
    payment = Payment.objects.get(payment_no=paid["payment"]["payment_no"])
    handle_payment_notification(
        notification=PaymentNotification(
            event_type="TRADE.NOTIFY",
            out_trade_no=payment.payment_no.hex,
            transaction_no="alipay-transaction-1",
            amount_minor=payment.amount_minor,
            success=True,
            channel_status="TRADE_SUCCESS",
        )
    )
    payment.refresh_from_db()
    created.order.refresh_from_db()

    admin_user = User.objects.create(
        phone_hash=hash_phone("13800138099"),
        phone_masked="138****8099",
        status=User.Status.ACTIVE,
    )
    refund_request, created_refund_request = create_order_refund_request(
        user=customer,
        order_no=str(created.order.order_no),
        reason="测试原渠道退款",
        expected_order_version=created.order.version,
        idempotency_key="external-refund-request-1",
    )
    result = approve_order_refund_request(
        admin_user=admin_user,
        request_no=str(refund_request.request_no),
        expected_version=refund_request.version,
        review_note="同意测试退款",
    )

    payment.refresh_from_db()
    created.order.refresh_from_db()
    refund_request.refresh_from_db()
    assert created_refund_request is True
    assert result["status"] == "REFUNDED"
    assert result["status_text"] == "已退款"
    assert refund_request.payment_refund.refund_method == Payment.Method.ALIPAY_APP
    assert payment.status == Payment.Status.REFUNDED
    assert created.order.status == Order.Status.REFUNDED


@override_settings(PAYMENT_GATEWAY_MODE="MOCK")
def test_external_refund_notification_is_idempotent_and_checks_amount() -> None:
    _provider, service, slot = create_provider_fixture("refund-callback-provider")
    customer = User.objects.create(
        phone_hash=hash_phone("13800138006"),
        phone_masked="138****8006",
        initial_role_selected=True,
    )
    created = create_order(
        user=customer,
        service_id=str(service.public_id),
        slot_id=str(slot.public_id),
        note="退款回调测试",
        expected_service_version=service.version,
        expected_slot_version=slot.version,
        idempotency_key="refund-callback-order",
    )
    paid = pay_order(
        user=customer,
        order_no=str(created.order.order_no),
        expected_version=created.order.version,
        payment_method=Payment.Method.WECHAT_APP,
        idempotency_key="refund-callback-payment",
    )
    payment = Payment.objects.get(payment_no=paid["payment"]["payment_no"])
    handle_payment_notification(
        notification=PaymentNotification(
            event_type="TRANSACTION.SUCCESS",
            out_trade_no=payment.payment_no.hex,
            transaction_no="wechat-refund-callback-transaction",
            amount_minor=payment.amount_minor,
            success=True,
            channel_status="SUCCESS",
        )
    )
    payment.refresh_from_db()
    refund = register_refund(
        payment=payment,
        refund_amount_minor=payment.amount_minor,
        idempotency_key="refund-callback-1",
    )
    callback = PaymentNotification(
        event_type="REFUND.SUCCESS",
        out_trade_no=payment.payment_no.hex,
        transaction_no="wechat-refund-1",
        amount_minor=payment.amount_minor,
        success=True,
        channel_status="REFUND_SUCCESS",
        refund_no=refund.refund_no.hex,
    )

    first = handle_payment_notification(notification=callback)
    repeated = handle_payment_notification(notification=callback)

    payment.refresh_from_db()
    assert first.status == "SUCCESS"
    assert repeated.status == "SUCCESS"
    assert first.completed_at == repeated.completed_at
    assert payment.status == Payment.Status.REFUNDED

    with pytest.raises(ApiError) as error:
        handle_payment_notification(
            notification=replace(callback, amount_minor=payment.amount_minor + 1)
        )
    assert error.value.machine_code == ErrorCode.PAYMENT_AMOUNT_MISMATCH
