"""开发测试管理后台页面和人工审核流程测试。"""

from __future__ import annotations

import uuid

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from backend.accounts.models import User
from backend.common.crypto import encrypt_text, hash_sensitive_text
from backend.identity.models import IdentityVerification
from backend.providers.models import ProviderApplication

pytestmark = pytest.mark.django_db


def create_user(phone_hash: str, *, is_staff: bool = False) -> User:
    return User.objects.create(
        phone_hash=phone_hash,
        phone_masked="138****8000",
        is_staff=is_staff,
    )


def create_identity(user: User) -> IdentityVerification:
    return IdentityVerification.objects.create(
        user=user,
        verification_no=uuid.uuid4(),
        verification_type=IdentityVerification.Type.REAL_NAME,
        status=IdentityVerification.Status.PENDING,
        real_name_encrypted=encrypt_text("测试用户"),
        id_card_number_encrypted=encrypt_text("11010519491231002X"),
        id_card_hash=hash_sensitive_text("11010519491231002X"),
        request_fingerprint="fingerprint",
    )


def create_provider_application(user: User) -> ProviderApplication:
    return ProviderApplication.objects.create(
        application_no=ProviderApplication.make_application_no(),
        user=user,
        status=ProviderApplication.Status.PENDING,
        introduction="测试服务者申请简介",
        real_name_encrypted=encrypt_text("测试服务者"),
        id_card_encrypted=encrypt_text("11010519491231002X"),
        id_card_hash=hash_sensitive_text("11010519491231002X"),
        request_fingerprint="provider-fingerprint",
    )


def test_management_dashboard_lists_identity_and_provider_reviews() -> None:
    client = APIClient()
    admin = create_user("management-admin", is_staff=True)
    applicant = create_user("management-applicant")
    create_identity(applicant)
    create_provider_application(applicant)
    client.force_login(admin)

    dashboard = client.get(reverse("management-dashboard"))
    identity_list = client.get(reverse("management-identity-list"))
    provider_list = client.get(reverse("management-provider-list"))

    assert dashboard.status_code == 200
    assert identity_list.status_code == 200
    assert provider_list.status_code == 200
    assert "实名待审核" in dashboard.content.decode()
    assert "服务者待审核" in dashboard.content.decode()


def test_management_dashboard_can_approve_identity_and_provider_application() -> None:
    client = APIClient()
    admin = create_user("management-review-admin", is_staff=True)
    applicant = create_user("management-review-applicant")
    identity = create_identity(applicant)
    application = create_provider_application(applicant)
    client.force_login(admin)

    identity_review = client.post(
        reverse("management-identity-review", args=[identity.verification_no]),
        {"action": "approve", "expected_version": identity.version, "reason": ""},
    )
    provider_review = client.post(
        reverse("management-provider-review", args=[application.application_no]),
        {"action": "approve", "expected_version": application.version, "reason": ""},
    )

    identity.refresh_from_db()
    application.refresh_from_db()
    applicant.refresh_from_db()
    assert identity_review.status_code == 302
    assert provider_review.status_code == 302
    assert identity.status == IdentityVerification.Status.PASSED
    assert application.status == ProviderApplication.Status.APPROVED
    assert applicant.provider_enabled is True


def test_management_dashboard_requires_staff_user() -> None:
    client = APIClient()

    response = client.get(reverse("management-dashboard"))

    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]
