"""第一批枚举中文展示字段和标签对象响应测试。"""

from __future__ import annotations

import pytest
from django.utils import timezone

from backend.accounts.services import session_payload
from backend.adminops.auth import write_admin_operation
from backend.adminops.services import list_admin_audit_logs
from backend.catalog.models import ProviderServiceTag, ProviderTag, ServiceTag
from backend.catalog.services import service_payload
from backend.payments.models import Payment
from backend.payments.services import payment_payload
from backend.payouts.models import (
    EarningAccount,
    EarningEntry,
    EarningTransaction,
    PayoutMethod,
    Withdrawal,
)
from backend.payouts.services import (
    list_earning_entries,
    list_earning_transactions,
    payout_method_payload,
    withdrawal_payload,
)
from backend.providers.models import (
    ProviderProfileCategory,
    ProviderProfileTag,
)
from backend.providers.profile_services import provider_profile_payload
from backend.providers.services import application_payload
from backend.wallets.models import WalletAccount, WalletTransaction
from backend.wallets.services import wallet_transaction_payload
from tests.test_booking_flow import create_provider_fixture

pytestmark = pytest.mark.django_db


def test_first_batch_responses_include_labels_and_tag_objects() -> None:
    provider, service, _slot = create_provider_fixture("enum-display-provider")
    service_tag, _ = ServiceTag.objects.get_or_create(
        code="BEGINNER",
        defaults={
            "name": "新手友好",
            "category": "教学特点",
            "sort_order": 10,
        },
    )
    provider_tag, _ = ProviderTag.objects.get_or_create(
        code="PATIENT",
        defaults={
            "name": "耐心细致",
            "category": "服务特点",
            "sort_order": 10,
        },
    )
    ProviderServiceTag.objects.get_or_create(
        service=service,
        tag=service_tag,
        defaults={"position": 0},
    )
    ProviderProfileTag.objects.get_or_create(
        profile=provider.provider_profile,
        tag_code=provider_tag.code,
        defaults={"sort_order": 0},
    )
    ProviderProfileCategory.objects.get_or_create(
        profile=provider.provider_profile,
        category_code=service.category.code,
    )

    service_data = service_payload(service)
    profile_data = provider_profile_payload(provider)
    session_data = session_payload(provider)
    application_data = application_payload(None, provider)
    write_admin_operation(
        operator=provider,
        action="USER_BAN",
        target_type="USER",
        target_id=str(provider.public_id),
    )
    audit_data = list_admin_audit_logs(page=1, page_size=20)

    assert service_data["status"] == "ONLINE"
    assert service_data["status_text"] == "已上架"
    assert service_data["category"]["code"] == "SPORT"
    assert service_data["category"]["name"]
    assert service_data["tag_codes"] == ["BEGINNER"]
    assert service_data["tags"][0]["name"] == "新手友好"
    assert profile_data["categories"][0]["code"] == "SPORT"
    assert profile_data["categories"][0]["name"]
    assert profile_data["tag_codes"] == ["PATIENT"]
    assert profile_data["tags"][0]["name"] == "耐心细致"
    assert session_data["status_text"] == "正常"
    assert session_data["primary_role_text"] == "服务陪伴者"
    assert session_data["provider_status_text"] == "已通过"
    assert application_data["status_text"] == "未提交"
    assert application_data["real_name_status_text"] == "未提交"
    assert audit_data["items"][0]["action"] == "USER_BAN"
    assert audit_data["items"][0]["action_text"] == "封禁用户"
    assert audit_data["items"][0]["target_type_text"] == "用户"


def test_payment_finance_and_payout_responses_include_labels() -> None:
    provider, _service, _slot = create_provider_fixture("enum-finance-provider")
    payment = Payment.objects.create(
        user=provider,
        order_no="enum-order",
        payment_method=Payment.Method.ALIPAY_APP,
        payment_channel="ALIPAY",
        amount_minor=1000,
        status=Payment.Status.PENDING,
        idempotency_key="enum-payment",
        request_fingerprint="enum-payment-fingerprint",
    )
    wallet = WalletAccount.objects.create(user=provider)
    wallet_transaction = WalletTransaction.objects.create(
        account=wallet,
        user=provider,
        direction=WalletTransaction.Direction.CREDIT,
        transaction_type=WalletTransaction.TransactionType.TOPUP,
        business_type="TEST_TOPUP",
        business_no="enum-topup",
        amount_minor=1000,
        balance_after_amount_minor=1000,
        idempotency_key="enum-wallet",
        request_fingerprint="enum-wallet-fingerprint",
    )
    earning_account = EarningAccount.objects.create(
        user=provider,
        account_type=EarningAccount.AccountType.PROVIDER_INCOME,
    )
    EarningEntry.objects.create(
        account=earning_account,
        user=provider,
        business_type="PROVIDER_ORDER_INCOME",
        business_no="enum-order",
        gross_amount_minor=1000,
        platform_fee_amount_minor=100,
        net_amount_minor=900,
        status=EarningEntry.Status.PENDING_SETTLEMENT,
        available_at=timezone.now(),
        idempotency_key="enum-earning-entry",
        request_fingerprint="enum-earning-entry-fingerprint",
    )
    EarningTransaction.objects.create(
        account=earning_account,
        user=provider,
        direction=EarningTransaction.Direction.HOLD,
        transaction_type=EarningTransaction.TransactionType.WITHDRAWAL_HOLD,
        business_type="WITHDRAWAL",
        business_no="enum-withdrawal",
        amount_minor=900,
        available_after_amount_minor=0,
        frozen_after_amount_minor=900,
        total_income_after_amount_minor=0,
        total_withdrawn_after_amount_minor=0,
        idempotency_key="enum-earning-transaction",
        request_fingerprint="enum-earning-transaction-fingerprint",
    )
    payout_method = PayoutMethod.objects.create(
        user=provider,
        method_type=PayoutMethod.MethodType.BANK_CARD,
        account_name_encrypted="encrypted",
        account_name_masked="张*",
        account_number_encrypted="encrypted",
        account_number_masked="**** 1234",
        account_fingerprint="enum-payout-fingerprint",
        display_text="测试银行 **** 1234",
        request_fingerprint="enum-payout-request",
    )
    withdrawal = Withdrawal.objects.create(
        user=provider,
        account=earning_account,
        payout_method=payout_method,
        amount_minor=900,
        payout_amount_minor=900,
        status=Withdrawal.Status.PENDING_REVIEW,
        idempotency_key="enum-withdrawal",
        request_fingerprint="enum-withdrawal-fingerprint",
    )

    payment_data = payment_payload(payment)
    wallet_data = wallet_transaction_payload(wallet_transaction)
    entry_data = list_earning_entries(
        user=provider,
        account_type=EarningAccount.AccountType.PROVIDER_INCOME,
        page=1,
        page_size=20,
    )
    transaction_data = list_earning_transactions(
        user=provider,
        account_type=EarningAccount.AccountType.PROVIDER_INCOME,
        page=1,
        page_size=20,
    )
    method_data = payout_method_payload(payout_method)
    withdrawal_data = withdrawal_payload(withdrawal)

    assert payment_data["payment_method_text"] == "支付宝 App 支付"
    assert payment_data["status_text"] == "待支付"
    assert wallet_data["direction_text"] == "入账"
    assert wallet_data["transaction_type_text"] == "测试充值"
    assert entry_data["items"][0]["status_text"] == "待结算"
    assert transaction_data["items"][0]["direction_text"] == "冻结"
    assert transaction_data["items"][0]["transaction_type_text"] == "提现冻结"
    assert method_data["method_type_text"] == "银行卡"
    assert method_data["status_text"] == "启用"
    assert withdrawal_data["account_type_text"] == "服务者收入"
    assert withdrawal_data["status_text"] == "待人工审核"
