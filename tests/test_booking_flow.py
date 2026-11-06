from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from backend.accounts.models import AuthToken, User
from backend.accounts.services import _token_raw, hash_token
from backend.catalog.models import ProviderService, ServiceCategory
from backend.common.crypto import encrypt_text
from backend.common.errors import ErrorCode
from backend.common.exceptions import ApiError
from backend.media.models import MediaAsset
from backend.orders.models import Order, OrderScheduleSlot
from backend.orders.services import (
    cancel_order,
    create_order,
    pay_order,
    quote_order,
    reject_order,
    transition_order,
)
from backend.profiles.models import UserProfile
from backend.providers.models import ProviderProfile
from backend.reviews.models import ProviderRatingStat, Review
from backend.reviews.services import create_review
from backend.scheduling.models import ScheduleSlot
from backend.social.models import Favorite, UserFollow
from backend.wallets.services import admin_top_up_wallet

pytestmark = pytest.mark.django_db


def create_user(phone_hash: str, *, is_staff: bool = False, provider: bool = False) -> User:
    user = User.objects.create(
        phone_hash=phone_hash,
        phone_masked="138****8000",
        is_staff=is_staff,
        initial_role_selected=True,
        primary_role=User.InitialRole.PROVIDER if provider else User.InitialRole.USER,
        default_workspace=User.Workspace.PROVIDER_WORKSPACE
        if provider
        else User.Workspace.USER_HOME,
        provider_status=User.ProviderStatus.APPROVED
        if provider
        else User.ProviderStatus.NOT_SUBMITTED,
        provider_enabled=provider,
    )
    return user


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


def create_provider_fixture(
    phone_hash: str = "booking-provider",
) -> tuple[User, ProviderService, ScheduleSlot]:
    provider = create_user(phone_hash, provider=True)
    provider_avatar_id = str(uuid.uuid4())
    avatar_hash = uuid.uuid4().hex + uuid.uuid4().hex
    MediaAsset.objects.create(
        public_id=provider_avatar_id,
        owner=provider,
        purpose=MediaAsset.Purpose.PROVIDER_PROFILE_AVATAR,
        storage_key=f"booking-provider-avatar/{provider.id}/{provider_avatar_id}",
        content_type="image/jpeg",
        extension="jpg",
        byte_size=1024,
        width=800,
        height=800,
        sha256=avatar_hash,
        request_fingerprint=avatar_hash,
    )
    ProviderProfile.objects.create(
        user=provider,
        nickname=f"provider-{provider.id}",
        signature="耐心细致",
        introduction="擅长台球基础教学和轻松陪练，适合新手入门练习。",
        avatar_media_id=provider_avatar_id,
    )
    cover_media_id = str(uuid.uuid4())
    content_hash = uuid.uuid4().hex + uuid.uuid4().hex
    MediaAsset.objects.create(
        public_id=cover_media_id,
        owner=provider,
        purpose=MediaAsset.Purpose.PROVIDER_SERVICE_COVER,
        storage_key=f"booking-service/{provider.id}/{cover_media_id}",
        content_type="image/jpeg",
        extension="jpg",
        byte_size=1024,
        width=800,
        height=800,
        sha256=content_hash,
        request_fingerprint=content_hash,
    )
    service = ProviderService.objects.create(
        provider_user=provider,
        category=ServiceCategory.objects.get(code="SPORT"),
        title="台球助教",
        price_amount_minor=6800,
        duration_minutes=60,
        introduction="适合新手学习基础动作。",
        cover_media_id=cover_media_id,
        status=ProviderService.Status.ONLINE,
        request_fingerprint="service-fingerprint",
    )
    slot_start = timezone.now() + timedelta(days=1)
    slot = ScheduleSlot.objects.create(
        provider_user=provider,
        service=service,
        start_at=slot_start,
        end_at=slot_start + timedelta(hours=1),
    )
    return provider, service, slot


def create_customer(phone_hash: str, admin: User) -> User:
    customer = create_user(phone_hash)
    admin_top_up_wallet(
        target_user=customer,
        created_by=admin,
        amount_minor=10000,
        reason="测试余额",
        idempotency_key=f"topup-{phone_hash}",
    )
    return customer


def test_booking_order_can_be_paid_completed_and_reviewed() -> None:
    provider, service, slot = create_provider_fixture()
    admin = create_user("booking-admin", is_staff=True)
    customer = create_customer("booking-customer", admin)
    customer_avatar_id = str(uuid.uuid4())
    customer_avatar_hash = uuid.uuid4().hex + uuid.uuid4().hex
    MediaAsset.objects.create(
        public_id=customer_avatar_id,
        owner=customer,
        purpose=MediaAsset.Purpose.USER_PROFILE_AVATAR,
        storage_key=f"booking-customer-avatar/{customer.id}/{customer_avatar_id}",
        content_type="image/jpeg",
        extension="jpg",
        byte_size=1024,
        width=800,
        height=800,
        sha256=customer_avatar_hash,
        request_fingerprint=customer_avatar_hash,
    )
    UserProfile.objects.create(
        user=customer,
        nickname="下单用户",
        avatar_media_id=customer_avatar_id,
        gender="MALE",
        age=28,
        city_code="LZ",
    )
    customer.phone_encrypted = encrypt_text("13800002000")
    customer.save(update_fields=["phone_encrypted", "updated_at"])
    provider.phone_encrypted = encrypt_text("13800001000")
    provider.save(update_fields=["phone_encrypted", "updated_at"])
    ProviderRatingStat.objects.create(
        provider_user=provider,
        review_count=36,
        rating_sum=173,
        rating_average=Decimal("4.80"),
    )
    created = create_order(
        user=customer,
        service_id=str(service.public_id),
        slot_id=str(slot.public_id),
        note="第一次见面",
        expected_service_version=service.version,
        expected_slot_version=slot.version,
        idempotency_key="order-1",
    )
    slot.refresh_from_db()
    assert slot.status == ScheduleSlot.Status.LOCKED
    assert slot.last_booking_status == ScheduleSlot.LastBookingStatus.LOCKED
    paid = pay_order(
        user=customer,
        order_no=str(created.order.order_no),
        expected_version=created.order.version,
        idempotency_key="payment-1",
    )
    slot.refresh_from_db()
    assert slot.status == ScheduleSlot.Status.BOOKED
    assert slot.last_booking_status == ScheduleSlot.LastBookingStatus.BOOKED
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
    completed = transition_order(
        user=customer,
        order_no=str(created.order.order_no),
        expected_version=completed_by_provider.version,
        action="confirm",
    )
    review = create_review(
        user=customer,
        order_no=str(created.order.order_no),
        rating=5,
        content="非常耐心",
        tag_codes=["PATIENT"],
        is_anonymous=False,
    )
    Favorite.objects.create(
        user=customer,
        target_type=Favorite.TargetType.SERVICE,
        target_id=service.public_id,
    )
    UserFollow.objects.create(follower=customer, followed=provider)
    client = APIClient()
    slot.refresh_from_db()

    assert created.order.status == Order.Status.PENDING_PAYMENT
    assert slot.status == ScheduleSlot.Status.BOOKED
    assert slot.last_booking_status == ScheduleSlot.LastBookingStatus.COMPLETED
    assert paid["order"]["status"] == "PENDING_ACCEPT"
    assert accepted.status == Order.Status.PENDING_SERVICE
    assert started.status == Order.Status.IN_SERVICE
    assert completed.status == Order.Status.COMPLETED
    assert completed.review_expires_at is not None
    assert review["rating"] == 5
    assert Review.objects.count() == 1
    assert created.order.service_snapshot["cover_media_id"] == service.cover_media_id
    order_list = client.get(
        f"{reverse('v1:orders')}?role=USER&status=COMPLETED",
        **auth_headers(customer),
    )
    assert order_list.json()["data"][0]["status_text"] == "已完成"
    assert order_list.json()["data"][0]["service"]["title"] == service.title
    assert order_list.json()["data"][0]["service"]["cover_media"]["display_url"]

    Order.objects.filter(pk=created.order.pk).update(service=None)
    historical_detail = client.get(
        reverse("v1:order-detail", args=[created.order.order_no]),
        **auth_headers(customer),
    )
    assert historical_detail.json()["data"]["service"]["cover_media"]["media_id"] == (
        service.cover_media_id
    )
    participants = historical_detail.json()["data"]["participants"]
    contact = historical_detail.json()["data"]["contact"]
    progress = historical_detail.json()["data"]["progress"]
    provider_detail = client.get(
        reverse("v1:order-detail", args=[created.order.order_no]),
        **auth_headers(provider),
    )

    assert participants["customer"]["nickname"] == "下单用户"
    assert participants["customer"]["avatar_media"]["display_url"]
    assert participants["provider"]["avatar_media"]["display_url"]
    assert participants["provider"]["rating_average"] == "4.81"
    assert participants["provider"]["review_count"] == 37
    assert participants["provider"]["completed_order_count"] == 1
    assert contact["target_role"] == "PROVIDER"
    assert contact["phone_dial"] == "13800001000"
    assert contact["tel_uri"] == "tel:13800001000"
    assert contact["can_call"] is True
    assert contact["action_label"] == "联系服务者"
    assert progress["next_action"]["role"] == "USER"
    assert progress["next_action"]["action"] == "VIEW_REVIEW"
    assert progress["next_action"]["label"] == "查看评价"
    assert progress["can_request_refund"] is False
    assert progress["review_status"] == "REVIEWED"
    assert progress["review_status_text"] == "已评价"
    assert progress["can_review"] is False
    assert next(item["event_type"] for item in progress["timeline"]) == "CREATED"
    assert provider_detail.status_code == 200
    assert provider_detail.json()["data"]["contact"]["target_role"] == "USER"
    assert provider_detail.json()["data"]["contact"]["phone_dial"] == "13800002000"
    assert provider_detail.json()["data"]["contact"]["action_label"] == "联系用户"
    user_summary = client.get(
        reverse("v1:order-summary"),
        {"role": "USER"},
        **auth_headers(customer),
    )
    provider_summary = client.get(
        reverse("v1:order-summary"),
        {"role": "PROVIDER"},
        **auth_headers(provider),
    )
    me_summary = client.get(
        reverse("v1:users-me-summary"),
        **auth_headers(customer),
    )
    assert user_summary.json()["data"]["total"] == 1
    assert user_summary.json()["data"]["status_counts"]["COMPLETED"] == 1
    assert provider_summary.json()["data"]["total"] == 1
    assert me_summary.json()["data"]["order_count"] == 1
    assert me_summary.json()["data"]["favorite_count"] == 1
    assert me_summary.json()["data"]["following_count"] == 1


def test_order_reject_refunds_wallet_and_releases_slot() -> None:
    provider, service, slot = create_provider_fixture("booking-refund-provider")
    admin = create_user("booking-refund-admin", is_staff=True)
    customer = create_customer("booking-refund-customer", admin)
    created = create_order(
        user=customer,
        service_id=str(service.public_id),
        slot_id=str(slot.public_id),
        note="需要取消",
        expected_service_version=service.version,
        expected_slot_version=slot.version,
        idempotency_key="order-refund",
    )
    paid = pay_order(
        user=customer,
        order_no=str(created.order.order_no),
        expected_version=created.order.version,
        idempotency_key="payment-refund",
    )
    rejected = reject_order(
        provider_user=provider,
        order_no=str(created.order.order_no),
        expected_version=paid["order"]["version"],
        reason="时间冲突",
    )

    assert rejected.status == Order.Status.REFUNDED
    assert rejected.refunded_amount_minor == 6800
    slot.refresh_from_db()
    assert slot.status == ScheduleSlot.Status.OPEN
    assert slot.last_booking_status == ScheduleSlot.LastBookingStatus.CANCELLED


def test_order_creation_is_idempotent_and_insufficient_balance_is_rejected() -> None:
    _provider, service, slot = create_provider_fixture("booking-idempotent-provider")
    customer = create_user("booking-idempotent-customer")
    create_order(
        user=customer,
        service_id=str(service.public_id),
        slot_id=str(slot.public_id),
        note="幂等测试",
        expected_service_version=service.version,
        expected_slot_version=slot.version,
        idempotency_key="same-order",
    )
    repeated = create_order(
        user=customer,
        service_id=str(service.public_id),
        slot_id=str(slot.public_id),
        note="幂等测试",
        expected_service_version=service.version,
        expected_slot_version=slot.version,
        idempotency_key="same-order",
    )
    with pytest.raises(ApiError) as error:
        pay_order(
            user=customer,
            order_no=str(repeated.order.order_no),
            expected_version=repeated.order.version,
        )
    assert error.value.machine_code == ErrorCode.WALLET_INSUFFICIENT_BALANCE
    assert repeated.reused is True
    client = APIClient()
    response = client.post(
        reverse("v1:order-pay", args=[repeated.order.order_no]),
        {
            "payment_method": "BALANCE",
            "expected_version": repeated.order.version,
        },
        format="json",
        **auth_headers(customer),
    )
    assert response.status_code == 402
    assert response.json()["code"] == ErrorCode.WALLET_INSUFFICIENT_BALANCE


def test_multi_hour_service_locks_and_releases_all_contiguous_units() -> None:
    provider, service, _legacy_slot = create_provider_fixture("booking-multi-hour-provider")
    customer = create_user("booking-multi-hour-customer")
    service.duration_minutes = 120
    service.save(update_fields=["duration_minutes", "updated_at"])
    start_at = (timezone.now() + timedelta(days=1)).replace(
        minute=0,
        second=0,
        microsecond=0,
    ) + timedelta(hours=2)
    first = ScheduleSlot.objects.create(
        provider_user=provider,
        service=None,
        start_at=start_at,
        end_at=start_at + timedelta(hours=1),
    )
    second = ScheduleSlot.objects.create(
        provider_user=provider,
        service=None,
        start_at=start_at + timedelta(hours=1),
        end_at=start_at + timedelta(hours=2),
    )
    quote = quote_order(
        user=customer,
        service_id=str(service.public_id),
        slot_id=str(first.public_id),
    )

    created = create_order(
        user=customer,
        service_id=str(service.public_id),
        slot_id=str(first.public_id),
        note="两小时预约",
        expected_service_version=quote["service_version"],
        expected_slot_version=quote["slot_version"],
        idempotency_key="multi-hour-order",
    )
    first.refresh_from_db()
    second.refresh_from_db()
    assert OrderScheduleSlot.objects.filter(order=created.order).count() == 2
    assert quote["pricing_unit"] == "HOUR"
    assert quote["booking_unit_count"] == 2
    assert quote["hourly_amount_minor"] == 6800
    assert quote["original_amount_minor"] == 13600
    assert quote["discount_amount_minor"] == 0
    assert quote["payable_amount_minor"] == 13600
    assert quote["discounts"] == []
    assert created.order.original_price_amount_minor == 13600
    assert created.order.payable_amount_minor == 13600
    assert first.status == second.status == ScheduleSlot.Status.LOCKED
    assert first.locked_order_no == second.locked_order_no == str(created.order.order_no)

    cancel_order(
        user=customer,
        order_no=str(created.order.order_no),
        expected_version=created.order.version,
        reason="时间不合适",
    )
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.status == second.status == ScheduleSlot.Status.OPEN
    assert (
        first.last_booking_status
        == second.last_booking_status
        == ScheduleSlot.LastBookingStatus.CANCELLED
    )


def test_multi_hour_booking_requires_every_contiguous_unit() -> None:
    provider, service, _legacy_slot = create_provider_fixture("booking-partial-provider")
    customer = create_user("booking-partial-customer")
    service.duration_minutes = 120
    service.save(update_fields=["duration_minutes", "updated_at"])
    start_at = (timezone.now() + timedelta(days=1)).replace(
        minute=0,
        second=0,
        microsecond=0,
    ) + timedelta(hours=2)
    first = ScheduleSlot.objects.create(
        provider_user=provider,
        service=None,
        start_at=start_at,
        end_at=start_at + timedelta(hours=1),
    )
    second = ScheduleSlot.objects.create(
        provider_user=provider,
        service=None,
        start_at=start_at + timedelta(hours=1),
        end_at=start_at + timedelta(hours=2),
        status=ScheduleSlot.Status.CLOSED,
    )

    with pytest.raises(ApiError) as error:
        create_order(
            user=customer,
            service_id=str(service.public_id),
            slot_id=str(first.public_id),
            note="连续时段不足",
            expected_service_version=service.version,
            expected_slot_version=first.version,
            idempotency_key="partial-hour-order",
        )

    first.refresh_from_db()
    second.refresh_from_db()
    assert error.value.machine_code == ErrorCode.ORDER_INVALID
    assert first.status == ScheduleSlot.Status.OPEN
    assert second.status == ScheduleSlot.Status.CLOSED


def test_service_duration_must_be_sixty_minute_multiple() -> None:
    _provider, service, slot = create_provider_fixture("booking-duration-provider")
    customer = create_user("booking-duration-customer")
    service.duration_minutes = 90
    service.save(update_fields=["duration_minutes", "updated_at"])

    with pytest.raises(ApiError) as error:
        create_order(
            user=customer,
            service_id=str(service.public_id),
            slot_id=str(slot.public_id),
            note="非整小时服务",
            expected_service_version=service.version,
            expected_slot_version=slot.version,
            idempotency_key="duration-order",
        )

    assert error.value.machine_code == ErrorCode.ORDER_INVALID


def test_refund_request_requires_admin_approval_and_refunds_full_balance() -> None:
    _provider, service, slot = create_provider_fixture("refund-request-provider")
    admin = create_user("refund-request-admin", is_staff=True)
    customer = create_customer("refund-request-customer", admin)
    created = create_order(
        user=customer,
        service_id=str(service.public_id),
        slot_id=str(slot.public_id),
        note="申请退款",
        expected_service_version=service.version,
        expected_slot_version=slot.version,
        idempotency_key="refund-request-order",
    )
    paid = pay_order(
        user=customer,
        order_no=str(created.order.order_no),
        expected_version=created.order.version,
        idempotency_key="refund-request-payment",
    )
    client = APIClient()
    before_request = client.get(
        reverse("v1:order-detail", args=[created.order.order_no]),
        **auth_headers(customer),
    )

    first = client.post(
        reverse("v1:order-refund-requests", args=[created.order.order_no]),
        {
            "reason": "临时有事无法参加",
            "expected_order_version": paid["order"]["version"],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="refund-request-1",
        **auth_headers(customer),
    )
    assert first.status_code == 201, first.content
    assert before_request.json()["data"]["progress"]["can_request_refund"] is True
    assert before_request.json()["data"]["progress"]["next_action"]["action"] == "REQUEST_REFUND"
    replay = client.post(
        reverse("v1:order-refund-requests", args=[created.order.order_no]),
        {
            "reason": "临时有事无法参加",
            "expected_order_version": paid["order"]["version"],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="refund-request-1",
        **auth_headers(customer),
    )
    admin_list = client.get(
        reverse("v1:admin-order-refund-requests"),
        {"status": "PENDING"},
        **auth_headers(admin),
    )
    approved = client.post(
        reverse(
            "v1:admin-order-refund-request-approve",
            args=[first.json()["data"]["request_no"]],
        ),
        {
            "expected_version": first.json()["data"]["version"],
            "review_note": "确认符合退款条件",
        },
        format="json",
        **auth_headers(admin),
    )

    created.order.refresh_from_db()
    slot.refresh_from_db()
    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["data"]["request_no"] == first.json()["data"]["request_no"]
    assert admin_list.json()["data"]["total"] == 1
    assert approved.status_code == 200
    assert approved.json()["data"]["status"] == "REFUNDED"
    assert approved.json()["data"]["refund_amount_minor"] == 6800
    assert created.order.status == Order.Status.REFUNDED
    assert created.order.refunded_amount_minor == 6800
    assert slot.status == ScheduleSlot.Status.OPEN
    assert paid["payment"]["status"] == "SUCCESS"


def test_refund_can_be_rejected_and_six_hour_window_is_enforced() -> None:
    provider, service, slot = create_provider_fixture("refund-window-provider")
    admin = create_user("refund-window-admin", is_staff=True)
    customer = create_customer("refund-window-customer", admin)
    created = create_order(
        user=customer,
        service_id=str(service.public_id),
        slot_id=str(slot.public_id),
        note="退款窗口测试",
        expected_service_version=service.version,
        expected_slot_version=slot.version,
        idempotency_key="refund-window-order",
    )
    paid = pay_order(
        user=customer,
        order_no=str(created.order.order_no),
        expected_version=created.order.version,
        idempotency_key="refund-window-payment",
    )
    transition_order(
        user=provider,
        order_no=str(created.order.order_no),
        expected_version=paid["order"]["version"],
        action="accept",
    )
    client = APIClient()

    accepted_request = client.post(
        reverse("v1:order-refund-requests", args=[created.order.order_no]),
        {
            "reason": "距离开始还有足够时间",
            "expected_order_version": 3,
        },
        format="json",
        **auth_headers(customer),
    )
    rejected = client.post(
        reverse(
            "v1:admin-order-refund-request-reject",
            args=[accepted_request.json()["data"]["request_no"]],
        ),
        {
            "expected_version": accepted_request.json()["data"]["version"],
            "review_note": "暂时不满足退款条件",
        },
        format="json",
        **auth_headers(admin),
    )
    slot.refresh_from_db()
    slot.start_at = timezone.now() + timedelta(hours=5)
    slot.end_at = slot.start_at + timedelta(hours=1)
    slot.save(update_fields=["start_at", "end_at", "updated_at"])
    created.order.refresh_from_db()
    too_late = client.post(
        reverse("v1:order-refund-requests", args=[created.order.order_no]),
        {
            "reason": "距离开始不足六小时",
            "expected_order_version": created.order.version,
        },
        format="json",
        **auth_headers(customer),
    )

    assert accepted_request.status_code == 201
    assert rejected.status_code == 200
    assert rejected.json()["data"]["status"] == "REJECTED"
    assert too_late.status_code == 400
    assert too_late.json()["code"] == ErrorCode.REFUND_REQUEST_INVALID


def test_provider_public_profile_and_review_window_are_enforced() -> None:
    client = APIClient()
    provider, service, _slot = create_provider_fixture("booking-public-provider")
    admin = create_user("booking-public-admin", is_staff=True)
    customer = create_customer("booking-public-customer", admin)
    created = create_order(
        user=customer,
        service_id=str(service.public_id),
        slot_id=str(_slot.public_id),
        note="公开资料和评价窗口",
        expected_service_version=service.version,
        expected_slot_version=_slot.version,
        idempotency_key="order-review-window",
    )
    Order.objects.filter(pk=created.order.pk).update(
        status=Order.Status.COMPLETED,
        completed_at=timezone.now() - timedelta(days=8),
        review_expires_at=timezone.now() - timedelta(days=1),
    )
    with pytest.raises(ApiError) as error:
        create_review(
            user=customer,
            order_no=str(created.order.order_no),
            rating=5,
            content="超过评价时间",
            tag_codes=[],
            is_anonymous=False,
        )
    profile = client.get(reverse("v1:public-provider-profile", args=[provider.public_id]))
    order_detail = client.get(
        reverse("v1:order-detail", args=[created.order.order_no]),
        **auth_headers(customer),
    )

    assert error.value.machine_code == ErrorCode.REVIEW_WINDOW_EXPIRED
    assert profile.status_code == 200
    assert profile.json()["data"]["provider"]["public_id"] == str(provider.public_id)
    assert order_detail.json()["data"]["progress"]["review_status"] == "EXPIRED"
    assert order_detail.json()["data"]["progress"]["review_status_text"] == "评价已结束"
    assert order_detail.json()["data"]["progress"]["can_review"] is False
    assert order_detail.json()["data"]["progress"]["next_action"]["action"] == "VIEW"
