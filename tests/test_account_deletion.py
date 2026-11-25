"""账号注销条件、短信确认和清理审计 API 测试。"""

from __future__ import annotations

import uuid

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from backend.accounts.deletion_services import delete_account
from backend.accounts.models import (
    AccountDeletionRecord,
    AuthToken,
    User,
    UserAuth,
)
from backend.accounts.services import encrypt_text, hash_phone, mask_phone
from backend.content.models import Moment, MomentMedia
from backend.payouts.models import EarningAccount
from backend.profiles.models import UserProfile
from backend.social.models import Comment, Favorite, UserFollow
from backend.wallets.models import WalletAccount
from tests.test_admin_v1 import create_admin, login_headers
from tests.test_booking_flow import auth_headers, create_user

pytestmark = pytest.mark.django_db


def _bind_phone(user: User, phone: str) -> None:
    user.phone_hash = hash_phone(phone)
    user.phone_masked = mask_phone(phone)
    user.phone_encrypted = encrypt_text(phone)
    user.save(update_fields=["phone_hash", "phone_masked", "phone_encrypted"])
    UserAuth.objects.create(
        user=user,
        auth_type=UserAuth.Type.PHONE,
        auth_identifier=hash_phone(phone),
    )


def test_account_deletion_check_sms_and_cleanup_are_safe() -> None:
    client = APIClient()
    user = create_user("account-deletion-user")
    target = create_user("account-deletion-target")
    _bind_phone(user, "13800001234")
    UserProfile.objects.create(
        user=user,
        nickname="注销测试用户",
        gender="MALE",
        age=28,
        city_code="LZ",
    )
    moment = Moment.objects.create(
        provider_user=user,
        content="注销后应清空",
        request_fingerprint="deletion-moment",
    )
    MomentMedia.objects.create(
        moment=moment,
        media_id=str(uuid.uuid4()),
        media_type=MomentMedia.MediaType.IMAGE,
    )
    comment = Comment.objects.create(
        moment=moment,
        user=user,
        content="注销后评论应清空",
    )
    Favorite.objects.create(
        user=user,
        target_type=Favorite.TargetType.PROVIDER,
        target_id=target.public_id,
    )
    UserFollow.objects.create(follower=user, followed=target)
    WalletAccount.objects.create(
        user=user,
        balance_amount_minor=2800,
    )
    headers = auth_headers(user)

    blocked = client.get(reverse("v1:account-deletion-check"), **headers)
    wallet = WalletAccount.objects.get(user=user)
    wallet.balance_amount_minor = 0
    wallet.save(update_fields=["balance_amount_minor"])

    checked = client.get(reverse("v1:account-deletion-check"), **headers)
    sms = client.post(
        reverse("v1:account-deletion-sms-code"),
        format="json",
        **headers,
    )
    sms_repeat = client.post(
        reverse("v1:account-deletion-sms-code"),
        format="json",
        **headers,
    )
    deleted = client.post(
        reverse("v1:account-deletion"),
        {
            "code": sms.json()["data"]["debug_code"],
            "confirm": True,
        },
        format="json",
        **headers,
    )

    assert blocked.status_code == 200
    assert blocked.json()["data"]["can_delete"] is False
    assert checked.json()["data"]["can_delete"] is True
    assert sms.status_code == 200
    assert sms.json()["data"]["phone_masked"] == mask_phone("13800001234")
    assert sms_repeat.status_code == 429
    assert deleted.status_code == 200

    user.refresh_from_db()
    moment.refresh_from_db()
    comment.refresh_from_db()
    assert user.status == User.Status.LOGOFF
    assert user.phone_hash is None
    assert not user.has_usable_password()
    assert not UserAuth.objects.filter(user=user).exists()
    assert AuthToken.objects.filter(user=user, revoked_at__isnull=True).count() == 0
    assert not UserProfile.objects.filter(user=user).exists()
    assert moment.status == Moment.Status.DELETED
    assert moment.content == ""
    assert not MomentMedia.objects.filter(moment=moment).exists()
    assert comment.status == Comment.Status.DELETED
    assert comment.content == ""
    assert not Favorite.objects.filter(user=user).exists()
    assert not UserFollow.objects.filter(follower=user).exists()
    assert AccountDeletionRecord.objects.filter(user=user).count() == 1

    replay = delete_account(user=user, code="000000", confirm=True)
    assert replay["request_no"] == deleted.json()["data"]["request_no"]


def test_account_deletion_rejects_unconfirmed_request() -> None:
    client = APIClient()
    user = create_user("account-deletion-unconfirmed")
    _bind_phone(user, "13800004321")
    headers = auth_headers(user)
    sms = client.post(
        reverse("v1:account-deletion-sms-code"),
        format="json",
        **headers,
    )

    response = client.post(
        reverse("v1:account-deletion"),
        {
            "code": sms.json()["data"]["debug_code"],
            "confirm": False,
        },
        format="json",
        **headers,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "ACCOUNT_DELETION_INVALID"
    assert AccountDeletionRecord.objects.filter(user=user).count() == 0


def test_admin_can_clear_balances_and_force_delete_user() -> None:
    client = APIClient()
    create_admin("13800130040")
    user = create_user("account-force-delete-user")
    _bind_phone(user, "13800005678")
    WalletAccount.objects.create(
        user=user,
        balance_amount_minor=2800,
    )
    EarningAccount.objects.create(
        user=user,
        account_type=EarningAccount.AccountType.REFERRAL_REWARD,
        available_amount_minor=340,
        total_income_amount_minor=340,
    )
    admin_headers = login_headers(client, "13800130040")

    cleared = client.post(
        reverse("admin-v1-user-balance-clear", args=[user.public_id]),
        {"reason": "注销测试资金清空"},
        format="json",
        **admin_headers,
    )
    forced = client.post(
        reverse("admin-v1-user-force-delete", args=[user.public_id]),
        {
            "expected_version": user.version,
            "reason": "低于提现门槛，管理员强制注销",
        },
        format="json",
        **admin_headers,
    )

    assert cleared.status_code == 200
    assert cleared.json()["data"]["cleared_amount_minor"] == 3140
    assert forced.status_code == 200
    assert forced.json()["data"]["deletion_mode"] == "ADMIN_FORCE"
    user.refresh_from_db()
    assert user.status == User.Status.LOGOFF
    assert WalletAccount.objects.get(user=user).balance_amount_minor == 0
    assert EarningAccount.objects.get(user=user).available_amount_minor == 0
    assert AccountDeletionRecord.objects.filter(user=user).count() == 1
