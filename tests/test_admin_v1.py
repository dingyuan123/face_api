"""Vue 管理后台认证、权限、用户和服务者管理 API 测试。"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.contrib.auth.hashers import make_password
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from backend.accounts.models import User
from backend.accounts.services import hash_phone
from backend.adminops.auth import write_admin_operation
from backend.adminops.models import AdminOperationLog
from backend.orders.models import Order
from backend.orders.services import create_order_refund_request
from backend.payouts.models import (
    EarningAccount,
    EarningEntry,
    PayoutMethod,
    Withdrawal,
)
from backend.profiles.models import UserProfile
from backend.reviews.models import Review
from backend.support.models import SupportTicket
from tests.test_booking_flow import (
    create_customer,
    create_order,
    create_provider_fixture,
    pay_order,
)
from tests.test_booking_flow import (
    create_user as create_booking_user,
)

pytestmark = pytest.mark.django_db


def create_admin(phone: str) -> User:
    return User.objects.create(
        phone_hash=hash_phone(phone),
        phone_masked="138****8000",
        password=make_password("AdminPassword!2026"),
        is_staff=True,
        status=User.Status.ACTIVE,
    )


def login_headers(client: APIClient, phone: str) -> dict[str, str]:
    captcha = client.post(reverse("admin-v1-captcha"), format="json").json()["data"]
    answer = sum(int(value) for value in captcha["question"].split(" = ")[0].split(" + "))
    response = client.post(
        reverse("admin-v1-login"),
        {
            "phone": phone,
            "password": "AdminPassword!2026",
            "captcha_token": captcha["captcha_token"],
            "captcha_answer": str(answer),
        },
        format="json",
    )
    assert response.status_code == 200
    return {"HTTP_AUTHORIZATION": f"Bearer {response.json()['data']['access_token']}"}


def test_admin_v1_login_me_and_dashboard_require_permission() -> None:
    client = APIClient()
    admin = create_admin("13800130001")

    captcha = client.post(reverse("admin-v1-captcha"), format="json").json()["data"]
    answer = sum(int(value) for value in captcha["question"].split(" = ")[0].split(" + "))
    login = client.post(
        reverse("admin-v1-login"),
        {
            "phone": "13800130001",
            "password": "AdminPassword!2026",
            "captcha_token": captcha["captcha_token"],
            "captcha_answer": str(answer),
        },
        format="json",
    )
    headers = {"HTTP_AUTHORIZATION": f"Bearer {login.json()['data']['access_token']}"}
    me = client.get(reverse("admin-v1-me"), **headers)
    dashboard = client.get(reverse("admin-v1-dashboard"), **headers)
    legacy_admin = client.get(reverse("v1:admin-provider-applications"), **headers)

    assert login.status_code == 200
    assert login.json()["data"]["permissions"]
    assert me.status_code == dashboard.status_code == 200
    assert legacy_admin.status_code == 200
    assert dashboard.json()["data"]["user_count"] == 1
    assert admin.is_staff is True


def test_admin_can_ban_unban_user_and_write_audit() -> None:
    client = APIClient()
    admin = create_admin("13800130002")
    target = User.objects.create(
        phone_hash="admin-v1-target",
        phone_masked="139****0000",
        status=User.Status.ACTIVE,
    )
    headers = login_headers(client, "13800130002")

    banned = client.post(
        reverse("admin-v1-user-action", args=[target.public_id, "ban"]),
        {"expected_version": target.version, "reason": "测试封禁"},
        format="json",
        **headers,
    )
    target.refresh_from_db()
    unbanned = client.post(
        reverse("admin-v1-user-action", args=[target.public_id, "unban"]),
        {"expected_version": target.version, "reason": "测试解封"},
        format="json",
        **headers,
    )

    assert banned.status_code == unbanned.status_code == 200
    assert banned.json()["data"]["status"] == "FROZEN"
    assert unbanned.json()["data"]["status"] == "ACTIVE"
    assert AdminOperationLog.objects.filter(operator=admin).count() == 2


def test_admin_user_detail_and_related_lists_are_safe_and_complete() -> None:
    client = APIClient()
    admin = create_admin("13800130020")
    provider, service, slot = create_provider_fixture("admin-user-detail-provider")
    customer = create_customer("admin-user-detail-customer", admin)
    UserProfile.objects.create(
        user=customer,
        nickname="管理详情用户",
        gender="MALE",
        age=28,
        city_code="LZ",
        signature="测试签名",
    )
    created = create_order(
        user=customer,
        service_id=str(service.public_id),
        slot_id=str(slot.public_id),
        note="管理详情订单",
        expected_service_version=service.version,
        expected_slot_version=slot.version,
        idempotency_key="admin-user-detail-order",
    )
    earning_account = EarningAccount.objects.create(
        user=provider,
        account_type=EarningAccount.AccountType.PROVIDER_INCOME,
        available_amount_minor=6800,
        total_income_amount_minor=6800,
    )
    EarningEntry.objects.create(
        account=earning_account,
        user=provider,
        business_type="PROVIDER_ORDER_INCOME",
        business_no=str(created.order.order_no),
        gross_amount_minor=6800,
        platform_fee_amount_minor=680,
        net_amount_minor=6120,
        status=EarningEntry.Status.AVAILABLE,
        available_at=timezone.now(),
        settled_at=timezone.now(),
        idempotency_key="admin-user-detail-earning",
        request_fingerprint="admin-user-detail-earning-fingerprint",
    )
    payout_method = PayoutMethod.objects.create(
        user=provider,
        method_type=PayoutMethod.MethodType.BANK_CARD,
        account_name_encrypted="encrypted-name",
        account_name_masked="张*",
        account_number_encrypted="encrypted-number",
        account_number_masked="**** 1234",
        institution_name="测试银行",
        account_fingerprint="admin-user-detail-payout-fingerprint",
        display_text="测试银行 **** 1234",
        request_fingerprint="admin-user-detail-payout-request",
    )
    Withdrawal.objects.create(
        user=provider,
        account=earning_account,
        payout_method=payout_method,
        amount_minor=1000,
        fee_amount_minor=0,
        payout_amount_minor=1000,
        status=Withdrawal.Status.PENDING_REVIEW,
        idempotency_key="admin-user-detail-withdrawal",
        request_fingerprint="admin-user-detail-withdrawal-fingerprint",
    )
    Review.objects.create(
        order_no=uuid.uuid4(),
        user=customer,
        provider_user=provider,
        rating=5,
        content="管理详情评价",
        review_expires_at=timezone.now() + timedelta(days=7),
    )
    SupportTicket.objects.create(
        user=provider,
        category=SupportTicket.Category.ORDER,
        subject="管理详情工单",
        description="测试管理员用户详情关联工单",
    )
    write_admin_operation(
        operator=admin,
        action="USER_TEST_AUDIT",
        target_type="USER",
        target_id=str(provider.public_id),
        reason="测试用户审计",
    )
    unauthorized = client.get(reverse("admin-v1-user-detail", args=[provider.public_id]))
    headers = login_headers(client, "13800130020")

    users = client.get(reverse("admin-v1-users"), {"keyword": "provider"}, **headers)
    detail = client.get(
        reverse("admin-v1-user-detail", args=[provider.public_id]),
        **headers,
    )
    orders = client.get(
        reverse("admin-v1-user-orders", args=[provider.public_id]),
        {"role": "PROVIDER"},
        **headers,
    )
    finance = client.get(
        reverse("admin-v1-user-finance", args=[provider.public_id]),
        **headers,
    )
    withdrawals = client.get(
        reverse("admin-v1-user-withdrawals", args=[provider.public_id]),
        **headers,
    )
    reviews = client.get(
        reverse("admin-v1-user-reviews", args=[provider.public_id]),
        **headers,
    )
    tickets = client.get(
        reverse("admin-v1-user-support-tickets", args=[provider.public_id]),
        **headers,
    )
    audits = client.get(
        reverse("admin-v1-user-audit-logs", args=[provider.public_id]),
        **headers,
    )
    invalid_role = client.get(
        reverse("admin-v1-user-orders", args=[provider.public_id]),
        {"role": "INVALID"},
        **headers,
    )

    assert unauthorized.status_code in {401, 403}
    assert users.status_code == 200
    assert users.json()["data"]["items"][0]["nickname"].startswith("provider-")
    assert users.json()["data"]["items"][0]["avatar_media"]["display_url"]
    assert detail.status_code == 200
    detail_data = detail.json()["data"]
    assert detail_data["provider"]["completed_order_count"] == 0
    assert detail_data["finance"]["provider_earning"]["available"]["amount_minor"] == 6800
    assert detail_data["finance"]["earning_summary"]["platform_commission"]["amount_minor"] == 680
    assert detail_data["finance"]["payout_methods"][0]["account_number_masked"].endswith("1234")
    assert orders.json()["data"]["items"][0]["role"] == "PROVIDER"
    assert orders.json()["data"]["items"][0]["cover_media"]["display_url"]
    assert finance.json()["data"]["total"] >= 1
    assert withdrawals.json()["data"]["total"] == 1
    assert reviews.json()["data"]["total"] == 1
    assert tickets.json()["data"]["total"] == 1
    assert audits.json()["data"]["total"] == 1
    assert invalid_role.status_code == 400
    assert "phone_encrypted" not in str(detail.json())
    assert "account_number_encrypted" not in str(detail.json())


def test_admin_can_manage_provider_status() -> None:
    client = APIClient()
    create_admin("13800130003")
    provider = User.objects.create(
        phone_hash=hash_phone("13800130004"),
        phone_masked="137****0000",
        status=User.Status.ACTIVE,
        provider_enabled=True,
        provider_status=User.ProviderStatus.APPROVED,
    )
    headers = login_headers(client, "13800130003")

    suspended = client.post(
        reverse("admin-v1-provider-action", args=[provider.public_id, "suspend"]),
        {"expected_version": provider.version, "reason": "测试停用"},
        format="json",
        **headers,
    )
    provider.refresh_from_db()
    restored = client.post(
        reverse("admin-v1-provider-action", args=[provider.public_id, "restore"]),
        {"expected_version": provider.version, "reason": "测试恢复"},
        format="json",
        **headers,
    )

    assert suspended.status_code == restored.status_code == 200
    assert suspended.json()["data"]["provider_enabled"] is False
    assert restored.json()["data"]["provider_enabled"] is True


def test_admin_dashboard_trends_todos_and_role_crud() -> None:
    client = APIClient()
    create_admin("13800130005")
    headers = login_headers(client, "13800130005")

    trends = client.get(
        reverse("admin-v1-dashboard-trends"),
        {"range": "7d"},
        **headers,
    )
    todos = client.get(reverse("admin-v1-dashboard-todos"), **headers)
    created = client.post(
        reverse("admin-v1-roles"),
        {
            "code": "REVIEWER",
            "name": "审核员",
            "permission_codes": ["admin.user.read"],
        },
        format="json",
        **headers,
    )
    role_no = created.json()["data"]["role_no"]
    updated = client.patch(
        reverse("admin-v1-role-detail", args=[role_no]),
        {
            "expected_version": created.json()["data"]["version"],
            "name": "审核员V2",
            "permission_codes": ["admin.user.read", "admin.provider.read"],
        },
        format="json",
        **headers,
    )
    deleted = client.delete(
        reverse("admin-v1-role-detail", args=[role_no]),
        **headers,
    )

    assert trends.status_code == todos.status_code == 200
    assert len(trends.json()["data"]["items"]) == 7
    assert todos.json()["data"]["pending_identity_count"] == 0
    assert created.status_code == 201
    assert updated.json()["data"]["name"] == "审核员V2"
    assert deleted.json()["data"]["deleted"] is True


def test_admin_can_list_and_view_orders() -> None:
    client = APIClient()
    create_admin("13800130006")
    provider, service, slot = create_provider_fixture("admin-order-provider")
    customer = create_booking_user("admin-order-customer")
    created = create_order(
        user=customer,
        service_id=str(service.public_id),
        slot_id=str(slot.public_id),
        note="管理员订单测试",
        expected_service_version=service.version,
        expected_slot_version=slot.version,
        idempotency_key="admin-order",
    )
    headers = login_headers(client, "13800130006")

    listing = client.get(reverse("admin-v1-orders"), **headers)
    detail = client.get(
        reverse("admin-v1-order-detail", args=[created.order.order_no]),
        **headers,
    )
    export = client.get(reverse("admin-v1-order-export"), **headers)

    assert listing.status_code == detail.status_code == export.status_code == 200
    assert listing.json()["data"]["total"] == 1
    assert detail.json()["data"]["order_no"] == str(created.order.order_no)
    assert provider.provider_enabled is True


def test_admin_can_cancel_order() -> None:
    client = APIClient()
    create_admin("13800130012")
    _provider, service, slot = create_provider_fixture("admin-cancel-provider")
    customer = create_customer(
        "admin-cancel-customer",
        create_admin("13800130013"),
    )
    created = create_order(
        user=customer,
        service_id=str(service.public_id),
        slot_id=str(slot.public_id),
        note="管理员取消测试",
        expected_service_version=service.version,
        expected_slot_version=slot.version,
        idempotency_key="admin-cancel-order",
    )
    headers = login_headers(client, "13800130012")

    response = client.post(
        reverse("admin-v1-order-cancel", args=[created.order.order_no]),
        {"expected_version": created.order.version, "reason": "管理员取消测试"},
        format="json",
        **headers,
    )
    created.order.refresh_from_db()

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "CANCELED"
    assert created.order.status == Order.Status.CANCELED


def test_admin_password_can_be_reset_with_sms_code() -> None:
    client = APIClient()
    create_admin("13800130007")

    forgot = client.post(
        reverse("admin-v1-password-forgot"),
        {"phone": "13800130007"},
        format="json",
    )
    reset = client.post(
        reverse("admin-v1-password-reset"),
        {
            "phone": "13800130007",
            "code": forgot.json()["data"]["debug_code"],
            "new_password": "NewAdminPassword!2026",
        },
        format="json",
    )

    assert forgot.status_code == reset.status_code == 200
    assert reset.json()["data"]["password_reset"] is True


def test_admin_can_view_finance_transactions_and_commission() -> None:
    client = APIClient()
    create_admin("13800130008")
    _provider, service, slot = create_provider_fixture("admin-finance-provider")
    customer = create_customer("admin-finance-customer", create_admin("13800130009"))
    created = create_order(
        user=customer,
        service_id=str(service.public_id),
        slot_id=str(slot.public_id),
        note="财务统计测试",
        expected_service_version=service.version,
        expected_slot_version=slot.version,
        idempotency_key="admin-finance-order",
    )
    pay_order(
        user=customer,
        order_no=str(created.order.order_no),
        expected_version=created.order.version,
        idempotency_key="admin-finance-payment",
    )
    headers = login_headers(client, "13800130008")

    overview = client.get(reverse("admin-v1-finance-overview"), **headers)
    transactions = client.get(reverse("admin-v1-finance-transactions"), **headers)
    export = client.get(reverse("admin-v1-finance-transactions-export"), **headers)
    commission = client.get(reverse("admin-v1-commission-overview"), **headers)
    trends = client.get(reverse("admin-v1-commission-trends"), **headers)
    details = client.get(reverse("admin-v1-commission-details"), **headers)
    reconciliation = client.get(reverse("admin-v1-finance-reconciliation"), **headers)
    withdrawals = client.get(reverse("admin-v1-withdrawals"), **headers)

    assert overview.status_code == transactions.status_code == export.status_code == 200
    assert (
        commission.status_code
        == trends.status_code
        == details.status_code
        == reconciliation.status_code
        == withdrawals.status_code
        == 200
    )
    assert overview.json()["data"]["paid_amount_minor"] == 6800
    assert transactions.json()["data"]["total"] >= 1
    assert export["Content-Type"].startswith("text/csv")
    assert commission.json()["data"]["commission_type"] == "PROVIDER_COMMISSION"
    assert len(trends.json()["data"]["items"]) == 7
    assert details.json()["data"]["total"] == 1


def test_admin_can_approve_partial_refund_without_closing_order() -> None:
    client = APIClient()
    create_admin("13800130010")
    _provider, service, slot = create_provider_fixture("admin-partial-refund-provider")
    customer = create_customer(
        "admin-partial-refund-customer",
        create_admin("13800130011"),
    )
    created = create_order(
        user=customer,
        service_id=str(service.public_id),
        slot_id=str(slot.public_id),
        note="部分退款测试",
        expected_service_version=service.version,
        expected_slot_version=slot.version,
        idempotency_key="admin-partial-refund-order",
    )
    paid = pay_order(
        user=customer,
        order_no=str(created.order.order_no),
        expected_version=created.order.version,
        idempotency_key="admin-partial-refund-payment",
    )
    refund_request, _ = create_order_refund_request(
        user=customer,
        order_no=str(created.order.order_no),
        reason="测试部分退款",
        expected_order_version=paid["order"]["version"],
    )
    headers = login_headers(client, "13800130010")

    response = client.post(
        reverse(
            "v1:admin-order-refund-request-approve",
            args=[refund_request.request_no],
        ),
        {
            "expected_version": refund_request.version,
            "review_note": "同意部分退款",
            "refund_amount_minor": 3000,
        },
        format="json",
        **headers,
    )
    created.order.refresh_from_db()

    assert response.status_code == 200
    assert response.json()["data"]["approved_refund_amount_minor"] == 3000
    assert created.order.refunded_amount_minor == 3000
    assert created.order.status != Order.Status.REFUNDED


def test_admin_can_use_platform_analytics_settings_and_announcements() -> None:
    client = APIClient()
    create_admin("13800130014")
    headers = login_headers(client, "13800130014")

    overview = client.get(reverse("admin-v1-analytics-overview"), **headers)
    trends = client.get(
        reverse("admin-v1-analytics-trends"),
        {"range": "7d"},
        **headers,
    )
    breakdown = client.get(
        reverse("admin-v1-analytics-breakdown"),
        {"dimension": "city"},
        **headers,
    )
    category_breakdown = client.get(
        reverse("admin-v1-analytics-breakdown"),
        {"dimension": "service_category"},
        **headers,
    )
    settings = client.patch(
        reverse("admin-v1-basic-settings"),
        {
            "settings": {"REVIEW_WINDOW_DAYS": 8},
            "expected_versions": {"REVIEW_WINDOW_DAYS": 0},
        },
        format="json",
        **headers,
    )
    announcement = client.post(
        reverse("admin-v1-announcements"),
        {"title": "测试公告", "content": "公告内容"},
        format="json",
        **headers,
    )
    updated_announcement = client.patch(
        reverse(
            "admin-v1-announcement-detail",
            args=[announcement.json()["data"]["announcement_no"]],
        ),
        {
            "title": "测试公告V2",
            "content": "公告内容V2",
            "status": "PUBLISHED",
            "expected_version": announcement.json()["data"]["version"],
        },
        format="json",
        **headers,
    )

    assert (
        overview.status_code
        == trends.status_code
        == breakdown.status_code
        == category_breakdown.status_code
        == 200
    )
    assert settings.status_code == 200
    assert settings.json()["data"]["settings"]["REVIEW_WINDOW_DAYS"]["value"] == 8
    assert announcement.status_code == 201
    assert updated_announcement.status_code == 200
    assert updated_announcement.json()["data"]["status"] == "PUBLISHED"


def test_admin_can_manage_city_category_and_commission_rules() -> None:
    client = APIClient()
    create_admin("13800130015")
    headers = login_headers(client, "13800130015")

    city = client.post(
        reverse("admin-v1-cities"),
        {"code": "TEST_CITY", "name": "测试城市"},
        format="json",
        **headers,
    )
    category = client.post(
        reverse("admin-v1-service-categories"),
        {"code": "TEST_CATEGORY", "name": "测试类目"},
        format="json",
        **headers,
    )
    updated_city = client.patch(
        reverse("admin-v1-city-detail", args=["TEST_CITY"]),
        {
            "name": "测试城市V2",
            "expected_version": city.json()["data"]["version"],
        },
        format="json",
        **headers,
    )
    commission = client.patch(
        reverse("admin-v1-commission-rules"),
        {
            "provider_commission_rate_bps": 1200,
            "expected_versions": {"PROVIDER_PLATFORM_COMMISSION_RATE_BPS": 0},
        },
        format="json",
        **headers,
    )

    assert city.status_code == category.status_code == 201
    assert updated_city.status_code == commission.status_code == 200
    assert updated_city.json()["data"]["name"] == "测试城市V2"
    assert commission.json()["data"]["provider_commission_rate_bps"] == 1200
