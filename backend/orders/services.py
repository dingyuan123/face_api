"""预约订单创建、余额支付、履约状态和退款释放业务服务。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpRequest
from django.utils import timezone

from backend.accounts.models import User
from backend.catalog.models import ProviderService
from backend.catalog.services import format_price_amount, service_payload
from backend.common.context import current_trace_id
from backend.common.crypto import decrypt_text, sensitive_fingerprint
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.media.services import get_media_payloads
from backend.orders.models import Order, OrderRefundRequest, OrderScheduleSlot, OrderStatusLog
from backend.payments.models import Payment
from backend.payments.services import (
    charge_wallet_for_order,
    payment_payload,
    refund_wallet_for_payment,
)
from backend.payouts.services import create_provider_order_earning
from backend.providers.profile_services import get_provider_avatar_media_id
from backend.reviews.models import Review
from backend.scheduling.models import ScheduleSlot
from backend.wallets.services import get_wallet_available_amount


@dataclass(frozen=True)
class OrderResult:
    """订单创建或支付结果。"""

    order: Order
    changed: bool
    reused: bool = False


def _invalid(field: str, message: str) -> ApiError:
    return ApiError(
        ErrorCode.ORDER_INVALID,
        ERROR_MESSAGES[ErrorCode.ORDER_INVALID],
        status_code=400,
        details={field: message},
    )


def _normalize_idempotency_key(value: str | None, prefix: str) -> str:
    if value is None:
        return f"auto:{prefix}:{uuid.uuid4()}"
    key = value.strip()
    if not key or len(key) > 128:
        raise _invalid("idempotency_key", "幂等键长度必须在 1 到 128 之间")
    return key


def _booking_amount(service: ProviderService) -> tuple[int, int]:
    """按每小时价格和服务时长计算预约小时数与优惠前总价。"""

    if service.duration_minutes <= 0 or service.duration_minutes % 60 != 0:
        raise _invalid("service_id", "服务时长必须是 60 分钟的倍数")
    if (
        settings.SCHEDULE_MAX_BOOKING_MINUTES > 0
        and service.duration_minutes > settings.SCHEDULE_MAX_BOOKING_MINUTES
    ):
        raise _invalid(
            "service_id",
            "服务时长超过当前允许的最大预约时长",
        )
    booking_unit_count = service.duration_minutes // 60
    return booking_unit_count, service.price_amount_minor * booking_unit_count


def quote_order(
    *,
    user: User,
    service_id: str,
    slot_id: str,
) -> dict[str, Any]:
    """计算下单前金额并返回下单所需服务和时段版本。"""

    service = (
        ProviderService.objects.select_related("category")
        .filter(
            public_id=service_id,
            deleted_at__isnull=True,
            status=ProviderService.Status.ONLINE,
        )
        .first()
    )
    if service is None:
        raise _invalid("service_id", "服务不存在、已下架或不可预约")
    booking_unit_count, original_amount_minor = _booking_amount(service)
    anchor_slot = (
        ScheduleSlot.objects.filter(
            Q(service__isnull=True) | Q(service=service),
            public_id=slot_id,
            status=ScheduleSlot.Status.OPEN,
            deleted_at__isnull=True,
        )
        .order_by("start_at", "id")
        .first()
    )
    if anchor_slot is None:
        raise _invalid("slot_id", "预约时段不存在或不可预约")
    if anchor_slot.start_at <= timezone.now():
        raise _invalid("slot_id", "不能预约过去的时间")
    expected_starts = [
        anchor_slot.start_at + timedelta(hours=offset) for offset in range(booking_unit_count)
    ]
    expected_ends = [
        anchor_slot.end_at + timedelta(hours=offset) for offset in range(booking_unit_count)
    ]
    available_count = ScheduleSlot.objects.filter(
        Q(service__isnull=True) | Q(service=service),
        provider_user=service.provider_user,
        start_at__in=expected_starts,
        end_at__in=expected_ends,
        status=ScheduleSlot.Status.OPEN,
        deleted_at__isnull=True,
    ).count()
    if available_count != booking_unit_count:
        raise _invalid("slot_id", "连续可预约时段不足，无法完成该时长服务")
    return {
        "pricing_unit": "HOUR",
        "currency": service.currency,
        "hourly_amount_minor": service.price_amount_minor,
        "booking_unit_count": booking_unit_count,
        "original_amount_minor": original_amount_minor,
        "discount_amount_minor": 0,
        "platform_fee_amount_minor": 0,
        "payable_amount_minor": original_amount_minor,
        "payable_display": format_price_amount(
            original_amount_minor,
            service.currency,
        ),
        "service_version": service.version,
        "slot_version": anchor_slot.version,
        "breakdown": [
            {
                "type": "SERVICE",
                "name": service.title,
                "quantity": booking_unit_count,
                "unit_amount_minor": service.price_amount_minor,
                "amount_minor": original_amount_minor,
            }
        ],
        "discounts": [],
        "quoted_at": timezone.now(),
    }


def _record_event(
    *,
    order: Order,
    event_type: str,
    from_status: str,
    actor_user_id: int | None,
    reason: str = "",
) -> None:
    OrderStatusLog.objects.create(
        order=order,
        event_type=event_type,
        from_status=from_status,
        to_status=order.status,
        actor_user_id=actor_user_id,
        reason=reason,
        trace_id=current_trace_id(),
    )


def _order_status_text(status: str) -> str:
    """返回订单状态展示文案。"""

    return {
        Order.Status.PENDING_PAYMENT: "待支付",
        Order.Status.PENDING_ACCEPT: "待接单",
        Order.Status.PENDING_SERVICE: "待履约",
        Order.Status.IN_SERVICE: "履约中",
        Order.Status.PENDING_CONFIRM: "待确认",
        Order.Status.COMPLETED: "已完成",
        Order.Status.CANCELED: "已取消",
        Order.Status.REFUNDED: "已退款",
    }[status]


def _order_service_payload(
    order: Order,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """返回订单服务展示信息；服务缺失时使用下单快照和媒体 ID。"""

    if order.service:
        return service_payload(order.service, request)
    snapshot = order.service_snapshot
    cover_media_id = snapshot.get("cover_media_id")
    gallery_media_ids = snapshot.get("gallery_media_ids", [])
    cover_media = get_media_payloads([cover_media_id], request) if cover_media_id else []
    gallery_media = get_media_payloads(gallery_media_ids, request)
    currency = snapshot.get("currency", order.currency)
    hourly_amount_minor = snapshot.get(
        "hourly_amount_minor",
        snapshot.get("price_amount_minor", 0),
    )
    return {
        "id": snapshot.get("id", snapshot.get("service_id")),
        "version": snapshot.get("version", 0),
        "title": snapshot.get("title", ""),
        "category_code": snapshot.get("category_code", ""),
        "pricing_unit": snapshot.get("pricing_unit", "HOUR"),
        "price": {
            "currency": currency,
            "amount_minor": hourly_amount_minor,
        },
        "price_display": format_price_amount(hourly_amount_minor, currency),
        "duration_minutes": snapshot.get("duration_minutes", 0),
        "introduction": snapshot.get("introduction", ""),
        "cover_media": cover_media[0] if cover_media else None,
        "gallery_media": gallery_media,
        "tag_codes": snapshot.get("tag_codes", []),
        "location_type": snapshot.get("location_type", "PUBLIC_PLACE"),
        "status": snapshot.get("status", "HISTORICAL"),
    }


def _media_payload(media_id: str | None, request: HttpRequest | None) -> dict[str, Any] | None:
    """返回单个媒体安全摘要，无媒体时返回空值。"""

    if not media_id:
        return None
    payloads = get_media_payloads([media_id], request)
    return payloads[0] if payloads else None


def _order_participants_payload(
    order: Order,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """返回见面双方昵称、头像、手机号和服务者履约统计。"""

    from backend.reviews.services import provider_rating_summary

    customer_profile = getattr(order.user, "profile", None)
    provider_profile = getattr(order.provider_user, "provider_profile", None)
    provider_user_profile = getattr(order.provider_user, "profile", None)
    customer_avatar_id = getattr(customer_profile, "avatar_media_id", None)
    provider_avatar_id = get_provider_avatar_media_id(order.provider_user)
    rating = provider_rating_summary(order.provider_user)
    completed_order_count = Order.objects.filter(
        provider_user=order.provider_user,
        status=Order.Status.COMPLETED,
    ).count()
    identity_statuses = {
        "real_name_status": "NOT_SUBMITTED",
        "face_status": "NOT_SUBMITTED",
    }
    for verification in order.provider_user.identity_verifications.all():
        if verification.verification_type == "REAL_NAME":
            identity_statuses["real_name_status"] = verification.status
        if verification.verification_type == "FACE":
            identity_statuses["face_status"] = verification.status
    return {
        "customer": {
            "user_public_id": str(order.user.public_id),
            "nickname": getattr(customer_profile, "nickname", None),
            "avatar_media": _media_payload(customer_avatar_id, request),
            "phone_display": order.user.phone_masked,
        },
        "provider": {
            "user_public_id": str(order.provider_user.public_id),
            "nickname": (
                provider_profile.nickname
                if provider_profile and provider_profile.nickname
                else getattr(provider_user_profile, "nickname", None)
            ),
            "avatar_media": _media_payload(provider_avatar_id, request),
            "phone_display": order.provider_user.phone_masked,
            "rating_average": rating["rating_average"],
            "review_count": rating["review_count"],
            "completed_order_count": completed_order_count,
            "verification": identity_statuses,
        },
    }


def _contact_payload(order: Order, viewer: User) -> dict[str, Any]:
    """返回当前登录者可联系的订单对方电话和按钮文案。"""

    if viewer.id == order.user_id:
        target_role = "PROVIDER"
        target_user = order.provider_user
    elif viewer.id == order.provider_user_id:
        target_role = "USER"
        target_user = order.user
    else:
        raise ApiError(
            ErrorCode.AUTH_PERMISSION_DENIED,
            ERROR_MESSAGES[ErrorCode.AUTH_PERMISSION_DENIED],
            status_code=403,
        )
    target_profile = (
        getattr(target_user, "provider_profile", None)
        if target_role == "PROVIDER"
        else getattr(target_user, "profile", None)
    )
    target_name = getattr(target_profile, "nickname", None)
    phone_dial = decrypt_text(target_user.phone_encrypted) if target_user.phone_encrypted else None
    can_call = bool(phone_dial) and order.status in {
        Order.Status.PENDING_PAYMENT,
        Order.Status.PENDING_ACCEPT,
        Order.Status.PENDING_SERVICE,
        Order.Status.IN_SERVICE,
        Order.Status.PENDING_CONFIRM,
    }
    if order.status == Order.Status.COMPLETED and order.review_expires_at:
        can_call = bool(phone_dial) and timezone.now() <= order.review_expires_at
    return {
        "target_role": target_role,
        "target_name": target_name,
        "phone_display": target_user.phone_masked,
        "phone_dial": phone_dial,
        "tel_uri": f"tel:{phone_dial}" if phone_dial else None,
        "can_call": can_call,
        "action_label": "联系服务者" if target_role == "PROVIDER" else "联系用户",
    }


def _order_progress_payload(order: Order, viewer: User) -> dict[str, Any]:
    """返回订单时间线和当前登录者下一步按钮。"""

    viewer_role = (
        "USER"
        if viewer.id == order.user_id
        else "PROVIDER"
        if viewer.id == order.provider_user_id
        else "NONE"
    )
    review_exists = Review.objects.filter(
        order_no=order.order_no,
        status=Review.Status.VISIBLE,
    ).exists()
    if order.status != Order.Status.COMPLETED:
        review_status = "NOT_AVAILABLE"
        review_status_text = "暂不可评价"
        can_review = False
    elif review_exists:
        review_status = "REVIEWED"
        review_status_text = "已评价"
        can_review = False
    elif order.review_expires_at and timezone.now() > order.review_expires_at:
        review_status = "EXPIRED"
        review_status_text = "评价已结束"
        can_review = False
    else:
        review_status = "NOT_REVIEWED"
        review_status_text = "待评价"
        can_review = viewer_role == "USER"
    action_map = {
        Order.Status.PENDING_PAYMENT: {
            "USER": ("PAY", "去支付"),
            "PROVIDER": ("WAIT_PAYMENT", "等待用户支付"),
        },
        Order.Status.PENDING_ACCEPT: {
            "USER": ("WAIT_ACCEPT", "等待服务者接单"),
            "PROVIDER": ("ACCEPT", "接单"),
        },
        Order.Status.PENDING_SERVICE: {
            "USER": ("WAIT_SERVICE", "等待见面"),
            "PROVIDER": ("START", "开始履约"),
        },
        Order.Status.IN_SERVICE: {
            "USER": ("WAIT_COMPLETE", "服务进行中"),
            "PROVIDER": ("COMPLETE", "完成服务"),
        },
        Order.Status.PENDING_CONFIRM: {
            "USER": ("CONFIRM", "确认完成"),
            "PROVIDER": ("WAIT_CONFIRM", "等待用户确认"),
        },
        Order.Status.COMPLETED: {
            "USER": ("VIEW", "查看订单"),
            "PROVIDER": ("VIEW_REVIEW", "查看评价"),
        },
        Order.Status.CANCELED: {
            "USER": ("VIEW", "查看订单"),
            "PROVIDER": ("VIEW", "查看订单"),
        },
        Order.Status.REFUNDED: {
            "USER": ("VIEW", "查看订单"),
            "PROVIDER": ("VIEW", "查看订单"),
        },
    }
    action, label = action_map[order.status].get(viewer_role, ("NONE", "查看订单"))
    can_request_refund = False
    if viewer_role == "USER" and order.status in {
        Order.Status.PENDING_ACCEPT,
        Order.Status.PENDING_SERVICE,
    }:
        eligible_payment, _ = _refund_request_eligibility(order)
        can_request_refund = eligible_payment is not None
        pending_refund_request = OrderRefundRequest.objects.filter(
            order=order,
            status=OrderRefundRequest.Status.PENDING,
        ).exists()
        if pending_refund_request:
            action = "VIEW_REFUND_REQUEST"
            label = "查看退款申请"
        elif can_request_refund:
            action = "REQUEST_REFUND"
            label = "申请退款"
    if order.status == Order.Status.COMPLETED and viewer_role == "USER":
        if review_exists:
            action = "VIEW_REVIEW"
            label = "查看评价"
        elif can_review:
            action = "REVIEW"
            label = "去评价"
        else:
            action = "VIEW"
            label = "查看订单"
    timeline = []
    for event in order.status_logs.all().order_by("created_at", "id"):
        actor_role = (
            "USER"
            if event.actor_user_id == order.user_id
            else "PROVIDER"
            if event.actor_user_id == order.provider_user_id
            else "SYSTEM"
        )
        timeline.append(
            {
                "event_type": event.event_type,
                "status": event.to_status,
                "status_text": _order_status_text(event.to_status),
                "actor_role": actor_role,
                "occurred_at": event.created_at,
                "reason": event.reason,
            }
        )
    return {
        "current_status": order.status,
        "current_status_text": _order_status_text(order.status),
        "next_action": {
            "role": viewer_role,
            "action": action,
            "label": label,
        },
        "can_request_refund": can_request_refund,
        "review_status": review_status,
        "review_status_text": review_status_text,
        "can_review": can_review,
        "timeline": timeline,
    }


def _order_schedule_slots(order: Order, *, for_update: bool = False) -> list[ScheduleSlot]:
    """返回订单关联的连续小时单元，兼容旧的单时段订单。"""

    slot_ids = list(
        OrderScheduleSlot.objects.filter(order=order)
        .order_by("position", "id")
        .values_list("schedule_slot_id", flat=True)
    )
    if not slot_ids:
        slot_ids = [order.schedule_slot_id]
    queryset = ScheduleSlot.objects.filter(id__in=slot_ids)
    if for_update:
        queryset = queryset.select_for_update()
    slots_by_id = {slot.id: slot for slot in queryset}
    return [slots_by_id[slot_id] for slot_id in slot_ids if slot_id in slots_by_id]


def _release_schedule_slots(order: Order) -> None:
    """释放订单关联的全部时段，并保留最近一次取消结果。"""

    for slot in _order_schedule_slots(order, for_update=True):
        slot.status = ScheduleSlot.Status.OPEN
        slot.last_booking_status = ScheduleSlot.LastBookingStatus.CANCELLED
        slot.locked_order_no = ""
        slot.version += 1
        slot.save(
            update_fields=[
                "status",
                "last_booking_status",
                "locked_order_no",
                "version",
                "updated_at",
            ]
        )


def _mark_schedule_slots(
    order: Order,
    *,
    status: str,
    last_booking_status: str,
) -> None:
    """在订单状态变化时批量维护关联时段状态。"""

    for slot in _order_schedule_slots(order, for_update=True):
        slot.status = status
        slot.last_booking_status = last_booking_status
        if status in {ScheduleSlot.Status.LOCKED, ScheduleSlot.Status.BOOKED}:
            slot.locked_order_no = str(order.order_no)
        elif status == ScheduleSlot.Status.OPEN:
            slot.locked_order_no = ""
        slot.version += 1
        slot.save(
            update_fields=[
                "status",
                "last_booking_status",
                "locked_order_no",
                "version",
                "updated_at",
            ]
        )


def order_payload(
    order: Order,
    request: HttpRequest | None = None,
    viewer: User | None = None,
) -> dict[str, Any]:
    """返回订单和价格快照安全摘要。"""

    effective_viewer = viewer or getattr(request, "user", None) or order.user
    return {
        "order_no": str(order.order_no),
        "status": order.status,
        "status_text": _order_status_text(order.status),
        "user_public_id": str(order.user.public_id),
        "provider_public_id": str(order.provider_user.public_id),
        "service": _order_service_payload(order, request),
        "schedule_slot": order.slot_snapshot,
        "participants": _order_participants_payload(order, request),
        "contact": _contact_payload(order, effective_viewer),
        "progress": _order_progress_payload(order, effective_viewer),
        "price": {
            "currency": order.currency,
            "original_amount_minor": order.original_price_amount_minor,
            "discount_amount_minor": order.discount_amount_minor,
            "platform_fee_amount_minor": order.platform_fee_amount_minor,
            "payable_amount_minor": order.payable_amount_minor,
            "paid_amount_minor": order.paid_amount_minor,
            "refunded_amount_minor": order.refunded_amount_minor,
        },
        "note": order.note,
        "reject_reason": order.reject_reason,
        "version": order.version,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        "paid_at": order.paid_at,
        "completed_at": order.completed_at,
        "review_expires_at": order.review_expires_at,
    }


def create_order(
    *,
    user: User,
    service_id: str,
    slot_id: str,
    note: str,
    expected_service_version: int,
    expected_slot_version: int,
    idempotency_key: str | None = None,
) -> OrderResult:
    """创建待支付订单并锁定预约时段。"""

    normalized_key = _normalize_idempotency_key(idempotency_key, "order")
    fingerprint = sensitive_fingerprint(
        {
            "user_id": user.id,
            "service_id": service_id,
            "slot_id": slot_id,
            "note": note.strip(),
            "expected_service_version": expected_service_version,
            "expected_slot_version": expected_slot_version,
        }
    )
    try:
        with transaction.atomic():
            existing = Order.objects.filter(
                user=user,
                idempotency_key=normalized_key,
            ).first()
            if existing:
                if existing.request_fingerprint != fingerprint:
                    raise ApiError(
                        ErrorCode.ORDER_IDEMPOTENCY_CONFLICT,
                        ERROR_MESSAGES[ErrorCode.ORDER_IDEMPOTENCY_CONFLICT],
                        status_code=409,
                    )
                return OrderResult(existing, changed=False, reused=True)
            service = (
                ProviderService.objects.select_for_update()
                .select_related("category", "provider_user")
                .filter(
                    public_id=service_id,
                    deleted_at__isnull=True,
                    status=ProviderService.Status.ONLINE,
                )
                .first()
            )
            if service is None:
                raise _invalid("service_id", "服务不存在、已下架或不可预约")
            if service.version != expected_service_version:
                raise ApiError(
                    ErrorCode.ORDER_VERSION_CONFLICT,
                    ERROR_MESSAGES[ErrorCode.ORDER_VERSION_CONFLICT],
                    status_code=409,
                    details={"service_version": "服务已更新"},
                )
            required_slot_count, original_amount_minor = _booking_amount(service)
            anchor_slot = (
                ScheduleSlot.objects.select_for_update()
                .filter(
                    Q(service__isnull=True) | Q(service=service),
                    public_id=slot_id,
                    status=ScheduleSlot.Status.OPEN,
                    deleted_at__isnull=True,
                )
                .first()
            )
            if anchor_slot is None:
                raise _invalid("slot_id", "预约时段不存在或不可预约")
            if anchor_slot.version != expected_slot_version:
                raise ApiError(
                    ErrorCode.SCHEDULE_VERSION_CONFLICT,
                    ERROR_MESSAGES[ErrorCode.SCHEDULE_VERSION_CONFLICT],
                    status_code=409,
                )
            if anchor_slot.start_at <= timezone.now():
                raise _invalid("slot_id", "不能预约过去的时间")
            expected_starts = [
                anchor_slot.start_at + timedelta(hours=offset)
                for offset in range(required_slot_count)
            ]
            expected_ends = [
                anchor_slot.end_at + timedelta(hours=offset)
                for offset in range(required_slot_count)
            ]
            schedule_slots = list(
                ScheduleSlot.objects.select_for_update()
                .filter(
                    Q(service__isnull=True) | Q(service=service),
                    provider_user=service.provider_user,
                    start_at__in=expected_starts,
                    end_at__in=expected_ends,
                    status=ScheduleSlot.Status.OPEN,
                    deleted_at__isnull=True,
                )
                .order_by("start_at", "id")
            )
            if len(schedule_slots) != required_slot_count:
                raise _invalid(
                    "slot_id",
                    "连续可预约时段不足，无法完成该时长服务",
                )
            for slot in schedule_slots:
                if slot.end_at - slot.start_at != timedelta(hours=1):
                    raise _invalid("slot_id", "预约时段必须是 60 分钟单元")
            gallery_media_ids = list(
                service.gallery_links.order_by("position", "id").values_list(
                    "media_id",
                    flat=True,
                )
            )
            tag_codes = list(
                service.tag_links.order_by("position", "id").values_list(
                    "tag_id",
                    flat=True,
                )
            )
            order = Order.objects.create(
                user=user,
                provider_user=service.provider_user,
                service=service,
                schedule_slot=anchor_slot,
                service_snapshot={
                    "id": str(service.public_id),
                    "service_id": str(service.public_id),
                    "title": service.title,
                    "category_code": service.category.code,
                    "pricing_unit": "HOUR",
                    "currency": service.currency,
                    "hourly_amount_minor": service.price_amount_minor,
                    "booking_unit_count": required_slot_count,
                    "duration_minutes": service.duration_minutes,
                    "introduction": service.introduction,
                    "cover_media_id": service.cover_media_id,
                    "gallery_media_ids": gallery_media_ids,
                    "tag_codes": tag_codes,
                    "location_type": service.location_type,
                    "status": service.status,
                    "version": service.version,
                },
                provider_snapshot={
                    "user_public_id": str(service.provider_user.public_id),
                    "provider_profile_version": getattr(
                        service.provider_user.provider_profile,
                        "version",
                        0,
                    ),
                },
                slot_snapshot={
                    "slot_id": str(anchor_slot.public_id),
                    "slot_ids": [str(item.public_id) for item in schedule_slots],
                    "start_at": anchor_slot.start_at.isoformat(),
                    "end_at": schedule_slots[-1].end_at.isoformat(),
                    "required_unit_count": required_slot_count,
                    "version": anchor_slot.version,
                },
                original_price_amount_minor=original_amount_minor,
                payable_amount_minor=original_amount_minor,
                note=note.strip(),
                idempotency_key=normalized_key,
                request_fingerprint=fingerprint,
            )
            OrderScheduleSlot.objects.bulk_create(
                [
                    OrderScheduleSlot(
                        order=order,
                        schedule_slot=slot,
                        position=position,
                    )
                    for position, slot in enumerate(schedule_slots)
                ]
            )
            _mark_schedule_slots(
                order,
                status=ScheduleSlot.Status.LOCKED,
                last_booking_status=ScheduleSlot.LastBookingStatus.LOCKED,
            )
            _record_event(
                order=order,
                event_type=OrderStatusLog.EventType.CREATED,
                from_status="",
                actor_user_id=user.id,
            )
            return OrderResult(order, changed=True)
    except IntegrityError as exc:
        existing = Order.objects.filter(user=user, idempotency_key=normalized_key).first()
        if existing and existing.request_fingerprint == fingerprint:
            return OrderResult(existing, changed=False, reused=True)
        raise ApiError(
            ErrorCode.ORDER_IDEMPOTENCY_CONFLICT,
            ERROR_MESSAGES[ErrorCode.ORDER_IDEMPOTENCY_CONFLICT],
            status_code=409,
        ) from exc


def _get_owned_order(*, user: User, order_no: str) -> Order:
    order = (
        Order.objects.filter(
            Q(user=user) | Q(provider_user=user),
            order_no=order_no,
        )
        .select_related(
            "user",
            "user__profile",
            "provider_user",
            "provider_user__profile",
            "provider_user__provider_profile",
            "service",
            "schedule_slot",
        )
        .prefetch_related(
            "provider_user__identity_verifications",
            "status_logs",
        )
        .first()
    )
    if order is None:
        raise ApiError(
            ErrorCode.ORDER_NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.ORDER_NOT_FOUND],
            status_code=404,
        )
    return order


def pay_order(
    *,
    user: User,
    order_no: str,
    expected_version: int,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """使用钱包余额支付订单并推进到待接单。"""

    with transaction.atomic():
        order = (
            Order.objects.select_for_update(of=("self",))
            .select_related("user", "provider_user", "service", "schedule_slot")
            .filter(order_no=order_no, user=user)
            .first()
        )
        if order is None:
            raise ApiError(
                ErrorCode.ORDER_NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.ORDER_NOT_FOUND],
                status_code=404,
            )
        if order.version != expected_version:
            raise ApiError(
                ErrorCode.ORDER_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.ORDER_VERSION_CONFLICT],
                status_code=409,
            )
        if order.status == Order.Status.PENDING_ACCEPT:
            payment = Payment.objects.filter(
                order_no=str(order.order_no), status=Payment.Status.SUCCESS
            ).first()
            return {
                "order": order_payload(order),
                "payment": payment_payload(payment) if payment else None,
                "reused": True,
            }
        if order.status != Order.Status.PENDING_PAYMENT:
            raise ApiError(
                ErrorCode.ORDER_STATE_INVALID,
                ERROR_MESSAGES[ErrorCode.ORDER_STATE_INVALID],
                status_code=409,
            )
        available_amount_minor = get_wallet_available_amount(user)
        if available_amount_minor < order.payable_amount_minor:
            raise ApiError(
                ErrorCode.WALLET_INSUFFICIENT_BALANCE,
                ERROR_MESSAGES[ErrorCode.WALLET_INSUFFICIENT_BALANCE],
                status_code=402,
                details={
                    "available_amount_minor": available_amount_minor,
                    "required_amount_minor": order.payable_amount_minor,
                },
            )
        charge_result = charge_wallet_for_order(
            user=user,
            order_no=str(order.order_no),
            amount_minor=order.payable_amount_minor,
            idempotency_key=idempotency_key,
        )
        previous_status = order.status
        order.status = Order.Status.PENDING_ACCEPT
        order.paid_amount_minor = order.payable_amount_minor
        order.paid_at = timezone.now()
        order.version += 1
        order.save(
            update_fields=[
                "status",
                "paid_amount_minor",
                "paid_at",
                "version",
                "updated_at",
            ]
        )
        _mark_schedule_slots(
            order,
            status=ScheduleSlot.Status.BOOKED,
            last_booking_status=ScheduleSlot.LastBookingStatus.BOOKED,
        )
        _record_event(
            order=order,
            event_type=OrderStatusLog.EventType.PAID,
            from_status=previous_status,
            actor_user_id=user.id,
        )
        return {
            "order": order_payload(order),
            "payment": payment_payload(charge_result.payment),
            "reused": charge_result.reused,
        }


def _refund_and_release(*, order: Order, actor_user_id: int, reason: str) -> None:
    payment = Payment.objects.filter(
        order_no=str(order.order_no),
        status=Payment.Status.SUCCESS,
    ).first()
    if payment:
        refund_wallet_for_payment(
            payment=payment,
            refund_amount_minor=payment.amount_minor,
            idempotency_key=f"order-refund:{order.order_no}",
        )
        order.refunded_amount_minor = payment.amount_minor
    _release_schedule_slots(order)
    previous_status = order.status
    order.status = Order.Status.REFUNDED if payment else Order.Status.CANCELED
    order.version += 1
    order.save(update_fields=["status", "refunded_amount_minor", "version", "updated_at"])
    _record_event(
        order=order,
        event_type=OrderStatusLog.EventType.REFUNDED
        if payment
        else OrderStatusLog.EventType.CANCELED,
        from_status=previous_status,
        actor_user_id=actor_user_id,
        reason=reason,
    )


def cancel_order(
    *,
    user: User,
    order_no: str,
    expected_version: int,
    reason: str = "",
) -> Order:
    """用户取消订单，未支付直接取消，已支付原路退回余额。"""

    with transaction.atomic():
        order = (
            Order.objects.select_for_update()
            .select_related("schedule_slot")
            .filter(order_no=order_no, user=user)
            .first()
        )
        if order is None:
            raise ApiError(
                ErrorCode.ORDER_NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.ORDER_NOT_FOUND],
                status_code=404,
            )
        if order.version != expected_version:
            raise ApiError(
                ErrorCode.ORDER_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.ORDER_VERSION_CONFLICT],
                status_code=409,
            )
        if order.status not in {
            Order.Status.PENDING_PAYMENT,
            Order.Status.PENDING_ACCEPT,
            Order.Status.PENDING_SERVICE,
            Order.Status.IN_SERVICE,
            Order.Status.PENDING_CONFIRM,
        }:
            raise ApiError(
                ErrorCode.ORDER_STATE_INVALID,
                ERROR_MESSAGES[ErrorCode.ORDER_STATE_INVALID],
                status_code=409,
            )
        if order.status == Order.Status.PENDING_PAYMENT:
            previous_status = order.status
            _release_schedule_slots(order)
            order.status = Order.Status.CANCELED
            order.version += 1
            order.save(update_fields=["status", "version", "updated_at"])
            _record_event(
                order=order,
                event_type=OrderStatusLog.EventType.CANCELED,
                from_status=previous_status,
                actor_user_id=user.id,
                reason=reason,
            )
            return order
        _refund_and_release(order=order, actor_user_id=user.id, reason=reason)
        return order


def transition_order(
    *,
    user: User,
    order_no: str,
    expected_version: int,
    action: str,
    reason: str = "",
) -> Order:
    """执行服务者接单、履约、完成或用户确认订单。"""

    allowed = {
        "accept": (Order.Status.PENDING_ACCEPT, Order.Status.PENDING_SERVICE),
        "start": (Order.Status.PENDING_SERVICE, Order.Status.IN_SERVICE),
        "complete": (Order.Status.IN_SERVICE, Order.Status.PENDING_CONFIRM),
        "confirm": (Order.Status.PENDING_CONFIRM, Order.Status.COMPLETED),
    }
    if action not in allowed:
        raise _invalid("action", "订单操作不存在")
    with transaction.atomic():
        order = (
            Order.objects.select_for_update()
            .select_related("schedule_slot")
            .filter(order_no=order_no)
            .first()
        )
        if order is None:
            raise ApiError(
                ErrorCode.ORDER_NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.ORDER_NOT_FOUND],
                status_code=404,
            )
        is_provider_action = action in {"accept", "start", "complete"}
        if is_provider_action and order.provider_user_id != user.id:
            raise ApiError(
                ErrorCode.AUTH_PERMISSION_DENIED,
                ERROR_MESSAGES[ErrorCode.AUTH_PERMISSION_DENIED],
                status_code=403,
            )
        if not is_provider_action and order.user_id != user.id:
            raise ApiError(
                ErrorCode.AUTH_PERMISSION_DENIED,
                ERROR_MESSAGES[ErrorCode.AUTH_PERMISSION_DENIED],
                status_code=403,
            )
        expected_status, new_status = allowed[action]
        if order.status != expected_status:
            raise ApiError(
                ErrorCode.ORDER_STATE_INVALID,
                ERROR_MESSAGES[ErrorCode.ORDER_STATE_INVALID],
                status_code=409,
            )
        if order.version != expected_version:
            raise ApiError(
                ErrorCode.ORDER_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.ORDER_VERSION_CONFLICT],
                status_code=409,
            )
        previous_status = order.status
        order.status = new_status
        if action == "confirm":
            order.completed_at = timezone.now()
            order.review_expires_at = order.completed_at + timedelta(
                days=settings.REVIEW_WINDOW_DAYS
            )
            create_provider_order_earning(order)
            _mark_schedule_slots(
                order,
                status=ScheduleSlot.Status.BOOKED,
                last_booking_status=ScheduleSlot.LastBookingStatus.COMPLETED,
            )
        order.version += 1
        order.save()
        _record_event(
            order=order,
            event_type={
                "accept": OrderStatusLog.EventType.ACCEPTED,
                "start": OrderStatusLog.EventType.STARTED,
                "complete": OrderStatusLog.EventType.COMPLETED_BY_PROVIDER,
                "confirm": OrderStatusLog.EventType.CONFIRMED,
            }[action],
            from_status=previous_status,
            actor_user_id=user.id,
            reason=reason,
        )
        return order


def reject_order(
    *,
    provider_user: User,
    order_no: str,
    expected_version: int,
    reason: str,
) -> Order:
    """服务者拒绝订单并按当前阶段原路退款。"""

    if len(reason.strip()) < 2:
        raise _invalid("reason", "拒绝原因至少需要 2 个字符")
    with transaction.atomic():
        order = (
            Order.objects.select_for_update()
            .select_related("schedule_slot")
            .filter(order_no=order_no, provider_user=provider_user)
            .first()
        )
        if order is None:
            raise ApiError(
                ErrorCode.ORDER_NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.ORDER_NOT_FOUND],
                status_code=404,
            )
        if order.status != Order.Status.PENDING_ACCEPT:
            raise ApiError(
                ErrorCode.ORDER_STATE_INVALID,
                ERROR_MESSAGES[ErrorCode.ORDER_STATE_INVALID],
                status_code=409,
            )
        if order.version != expected_version:
            raise ApiError(
                ErrorCode.ORDER_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.ORDER_VERSION_CONFLICT],
                status_code=409,
            )
        order.reject_reason = reason.strip()
        order.save(update_fields=["reject_reason", "updated_at"])
        _refund_and_release(
            order=order,
            actor_user_id=provider_user.id,
            reason=reason.strip(),
        )
        return order


def list_orders(
    *,
    user: User,
    role: str,
    status: str | None = None,
    request: HttpRequest | None = None,
) -> list[dict[str, Any]]:
    """返回当前用户或服务者订单列表。"""

    if role not in {"USER", "PROVIDER"}:
        raise _invalid("role", "订单角色参数不正确")
    if status and status not in Order.Status.values:
        raise _invalid("status", "订单状态不存在")
    queryset = Order.objects.select_related(
        "user",
        "user__profile",
        "provider_user",
        "provider_user__profile",
        "provider_user__provider_profile",
        "service",
        "schedule_slot",
    ).prefetch_related("provider_user__identity_verifications", "status_logs")
    queryset = queryset.filter(user=user) if role == "USER" else queryset.filter(provider_user=user)
    if status:
        queryset = queryset.filter(status=status)
    return [order_payload(item, request) for item in queryset.order_by("-created_at", "-id")]


def order_summary(*, user: User, role: str) -> dict[str, Any]:
    """返回当前用户或服务者订单总数和状态数量。"""

    if role not in {"USER", "PROVIDER"}:
        raise _invalid("role", "订单角色参数不正确")
    queryset = (
        Order.objects.filter(user=user)
        if role == "USER"
        else Order.objects.filter(provider_user=user)
    )
    status_counts = {
        status.value: queryset.filter(status=status.value).count() for status in Order.Status
    }
    return {
        "total": queryset.count(),
        "status_counts": status_counts,
    }


def _refund_request_status_text(status: str) -> str:
    """返回退款申请状态展示文案。"""

    return {
        OrderRefundRequest.Status.PENDING: "待审核",
        OrderRefundRequest.Status.REJECTED: "审核拒绝",
        OrderRefundRequest.Status.REFUNDED: "已退款",
        OrderRefundRequest.Status.FAILED: "退款失败",
        OrderRefundRequest.Status.CANCELED: "用户撤销",
    }[status]


def _refund_request_payload(request: OrderRefundRequest) -> dict[str, Any]:
    """返回退款申请安全摘要。"""

    return {
        "request_no": str(request.request_no),
        "order_no": str(request.order.order_no),
        "status": request.status,
        "status_text": _refund_request_status_text(request.status),
        "reason": request.reason,
        "currency": request.currency,
        "refund_amount_minor": request.refund_amount_minor,
        "review_note": request.review_note,
        "reviewed_at": request.reviewed_at,
        "failure_reason": request.failure_reason,
        "version": request.version,
        "created_at": request.created_at,
        "updated_at": request.updated_at,
    }


def _refund_request_eligibility(order: Order) -> tuple[Payment, None] | tuple[None, str]:
    """校验退款申请条件并返回成功支付单或错误说明。"""

    payment = (
        Payment.objects.filter(
            order_no=str(order.order_no),
            status=Payment.Status.SUCCESS,
        )
        .order_by("-created_at", "-id")
        .first()
    )
    if payment is None:
        return None, "订单尚未支付或没有成功支付记录"
    scheduled_start_at = order.schedule_slot.start_at
    if scheduled_start_at <= timezone.now():
        return None, "服务已经开始或超过预约时间，不能申请退款"
    if order.status == Order.Status.PENDING_ACCEPT:
        return payment, None
    if order.status != Order.Status.PENDING_SERVICE:
        return None, "当前订单状态不允许申请退款"
    minimum_start_at = timezone.now() + timedelta(
        hours=settings.REFUND_REQUEST_MIN_HOURS_BEFORE_START
    )
    if scheduled_start_at <= minimum_start_at:
        return None, (
            f"服务开始前不足 {settings.REFUND_REQUEST_MIN_HOURS_BEFORE_START} 小时，不能申请退款"
        )
    return payment, None


def create_order_refund_request(
    *,
    user: User,
    order_no: str,
    reason: str,
    expected_order_version: int,
    idempotency_key: str | None = None,
) -> tuple[OrderRefundRequest, bool]:
    """创建订单退款申请，同一订单只允许一个待审核申请。"""

    normalized_reason = reason.strip()
    if not 2 <= len(normalized_reason) <= 500:
        raise ApiError(
            ErrorCode.REFUND_REQUEST_INVALID,
            ERROR_MESSAGES[ErrorCode.REFUND_REQUEST_INVALID],
            status_code=400,
            details={"reason": "退款原因必须为 2 到 500 个字符"},
        )
    normalized_key = (
        idempotency_key.strip()
        if idempotency_key and idempotency_key.strip()
        else f"auto:refund-request:{uuid.uuid4()}"
    )
    if len(normalized_key) > 128:
        raise ApiError(
            ErrorCode.REFUND_REQUEST_INVALID,
            ERROR_MESSAGES[ErrorCode.REFUND_REQUEST_INVALID],
            status_code=400,
            details={"idempotency_key": "幂等键长度不能超过 128"},
        )
    fingerprint = sensitive_fingerprint(
        {
            "order_no": str(order_no),
            "reason": normalized_reason,
            "expected_order_version": expected_order_version,
        }
    )
    try:
        with transaction.atomic():
            existing = OrderRefundRequest.objects.filter(
                requested_by=user,
                idempotency_key=normalized_key,
            ).first()
            if existing:
                if existing.request_fingerprint != fingerprint:
                    raise ApiError(
                        ErrorCode.REFUND_REQUEST_VERSION_CONFLICT,
                        ERROR_MESSAGES[ErrorCode.REFUND_REQUEST_VERSION_CONFLICT],
                        status_code=409,
                    )
                return existing, False
            order = (
                Order.objects.select_for_update()
                .select_related("schedule_slot")
                .filter(order_no=order_no, user=user)
                .first()
            )
            if order is None:
                raise ApiError(
                    ErrorCode.ORDER_NOT_FOUND,
                    ERROR_MESSAGES[ErrorCode.ORDER_NOT_FOUND],
                    status_code=404,
                )
            if order.version != expected_order_version:
                raise ApiError(
                    ErrorCode.ORDER_VERSION_CONFLICT,
                    ERROR_MESSAGES[ErrorCode.ORDER_VERSION_CONFLICT],
                    status_code=409,
                )
            payment, error = _refund_request_eligibility(order)
            if error or payment is None:
                raise ApiError(
                    ErrorCode.REFUND_REQUEST_INVALID,
                    ERROR_MESSAGES[ErrorCode.REFUND_REQUEST_INVALID],
                    status_code=400,
                    details={"order_no": error},
                )
            request = OrderRefundRequest.objects.create(
                order=order,
                payment=payment,
                requested_by=user,
                reason=normalized_reason,
                currency=payment.currency,
                refund_amount_minor=payment.amount_minor,
                idempotency_key=normalized_key,
                request_fingerprint=fingerprint,
            )
            return request, True
    except IntegrityError as exc:
        existing = OrderRefundRequest.objects.filter(
            requested_by=user,
            idempotency_key=normalized_key,
        ).first()
        if existing and existing.request_fingerprint == fingerprint:
            return existing, False
        raise ApiError(
            ErrorCode.REFUND_REQUEST_INVALID,
            ERROR_MESSAGES[ErrorCode.REFUND_REQUEST_INVALID],
            status_code=409,
            details={"order_no": "该订单已有待审核退款申请"},
        ) from exc


def list_order_refund_requests(*, user: User, order_no: str) -> list[dict[str, Any]]:
    """返回当前用户指定订单的退款申请历史。"""

    order = Order.objects.filter(order_no=order_no, user=user).first()
    if order is None:
        raise ApiError(
            ErrorCode.ORDER_NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.ORDER_NOT_FOUND],
            status_code=404,
        )
    requests = (
        OrderRefundRequest.objects.select_related("order", "payment")
        .filter(order=order)
        .order_by("-created_at", "-id")
    )
    return [_refund_request_payload(item) for item in requests]


def list_admin_refund_requests(
    *,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """返回后台退款申请列表和页码信息。"""

    queryset = OrderRefundRequest.objects.select_related("order", "payment")
    if status:
        if status not in OrderRefundRequest.Status.values:
            raise ApiError(
                ErrorCode.REFUND_REQUEST_INVALID,
                ERROR_MESSAGES[ErrorCode.REFUND_REQUEST_INVALID],
                status_code=400,
                details={"status": "退款申请状态不存在"},
            )
        queryset = queryset.filter(status=status)
    total = queryset.count()
    start = (page - 1) * page_size
    items = queryset.order_by("-created_at", "-id")[start : start + page_size]
    return {
        "items": [_refund_request_payload(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _validate_review_note(review_note: str) -> str:
    """校验后台审核说明，保证审核操作可追溯。"""

    normalized = review_note.strip()
    if not 2 <= len(normalized) <= 500:
        raise ApiError(
            ErrorCode.REFUND_REQUEST_INVALID,
            ERROR_MESSAGES[ErrorCode.REFUND_REQUEST_INVALID],
            status_code=400,
            details={"review_note": "审核说明必须为 2 到 500 个字符"},
        )
    return normalized


def approve_order_refund_request(
    *,
    admin_user: User,
    request_no: str,
    expected_version: int,
    review_note: str,
) -> dict[str, Any]:
    """后台同意退款并原子执行全额余额退款和时段释放。"""

    normalized_note = _validate_review_note(review_note)
    with transaction.atomic():
        refund_request = (
            OrderRefundRequest.objects.select_for_update()
            .select_related("order", "order__schedule_slot", "payment")
            .filter(request_no=request_no)
            .first()
        )
        if refund_request is None:
            raise ApiError(
                ErrorCode.REFUND_REQUEST_NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.REFUND_REQUEST_NOT_FOUND],
                status_code=404,
            )
        if refund_request.status != OrderRefundRequest.Status.PENDING:
            raise ApiError(
                ErrorCode.REFUND_REQUEST_STATE_INVALID,
                ERROR_MESSAGES[ErrorCode.REFUND_REQUEST_STATE_INVALID],
                status_code=409,
            )
        if refund_request.version != expected_version:
            raise ApiError(
                ErrorCode.REFUND_REQUEST_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.REFUND_REQUEST_VERSION_CONFLICT],
                status_code=409,
            )
        order = refund_request.order
        payment, eligibility_error = _refund_request_eligibility(order)
        if eligibility_error or payment is None:
            raise ApiError(
                ErrorCode.REFUND_REQUEST_STATE_INVALID,
                ERROR_MESSAGES[ErrorCode.REFUND_REQUEST_STATE_INVALID],
                status_code=409,
                details={"order_no": eligibility_error},
            )
        try:
            payment_refund = refund_wallet_for_payment(
                payment=payment,
                refund_amount_minor=refund_request.refund_amount_minor,
                idempotency_key=f"order-refund-request:{refund_request.request_no}",
            )
        except ApiError as exc:
            refund_request.status = OrderRefundRequest.Status.FAILED
            refund_request.reviewed_by_user_id = admin_user.id
            refund_request.review_note = normalized_note
            refund_request.reviewed_at = timezone.now()
            refund_request.failure_reason = str(exc)
            refund_request.version += 1
            refund_request.save(
                update_fields=[
                    "status",
                    "reviewed_by_user_id",
                    "review_note",
                    "reviewed_at",
                    "failure_reason",
                    "version",
                    "updated_at",
                ]
            )
            return _refund_request_payload(refund_request)
        order.refunded_amount_minor = refund_request.refund_amount_minor
        previous_status = order.status
        order.status = Order.Status.REFUNDED
        order.version += 1
        order.save(
            update_fields=[
                "status",
                "refunded_amount_minor",
                "version",
                "updated_at",
            ]
        )
        _release_schedule_slots(order)
        refund_request.status = OrderRefundRequest.Status.REFUNDED
        refund_request.reviewed_by_user_id = admin_user.id
        refund_request.review_note = normalized_note
        refund_request.reviewed_at = timezone.now()
        refund_request.payment_refund = payment_refund
        refund_request.failure_reason = ""
        refund_request.version += 1
        refund_request.save(
            update_fields=[
                "status",
                "reviewed_by_user_id",
                "review_note",
                "reviewed_at",
                "payment_refund",
                "failure_reason",
                "version",
                "updated_at",
            ]
        )
        _record_event(
            order=order,
            event_type=OrderStatusLog.EventType.REFUNDED,
            from_status=previous_status,
            actor_user_id=admin_user.id,
            reason=normalized_note,
        )
        return _refund_request_payload(refund_request)


def reject_order_refund_request(
    *,
    admin_user: User,
    request_no: str,
    expected_version: int,
    review_note: str,
) -> dict[str, Any]:
    """后台拒绝退款申请，订单和支付状态保持不变。"""

    normalized_note = _validate_review_note(review_note)
    with transaction.atomic():
        refund_request = (
            OrderRefundRequest.objects.select_for_update()
            .select_related("order")
            .filter(request_no=request_no)
            .first()
        )
        if refund_request is None:
            raise ApiError(
                ErrorCode.REFUND_REQUEST_NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.REFUND_REQUEST_NOT_FOUND],
                status_code=404,
            )
        if refund_request.status != OrderRefundRequest.Status.PENDING:
            raise ApiError(
                ErrorCode.REFUND_REQUEST_STATE_INVALID,
                ERROR_MESSAGES[ErrorCode.REFUND_REQUEST_STATE_INVALID],
                status_code=409,
            )
        if refund_request.version != expected_version:
            raise ApiError(
                ErrorCode.REFUND_REQUEST_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.REFUND_REQUEST_VERSION_CONFLICT],
                status_code=409,
            )
        refund_request.status = OrderRefundRequest.Status.REJECTED
        refund_request.reviewed_by_user_id = admin_user.id
        refund_request.review_note = normalized_note
        refund_request.reviewed_at = timezone.now()
        refund_request.version += 1
        refund_request.save(
            update_fields=[
                "status",
                "reviewed_by_user_id",
                "review_note",
                "reviewed_at",
                "version",
                "updated_at",
            ]
        )
        return _refund_request_payload(refund_request)


def cancel_order_refund_request(
    *,
    user: User,
    request_no: str,
    expected_version: int,
) -> dict[str, Any]:
    """用户撤销仍待审核的退款申请。"""

    with transaction.atomic():
        refund_request = (
            OrderRefundRequest.objects.select_for_update()
            .select_related("order")
            .filter(request_no=request_no, requested_by=user)
            .first()
        )
        if refund_request is None:
            raise ApiError(
                ErrorCode.REFUND_REQUEST_NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.REFUND_REQUEST_NOT_FOUND],
                status_code=404,
            )
        if refund_request.status != OrderRefundRequest.Status.PENDING:
            raise ApiError(
                ErrorCode.REFUND_REQUEST_STATE_INVALID,
                ERROR_MESSAGES[ErrorCode.REFUND_REQUEST_STATE_INVALID],
                status_code=409,
            )
        if refund_request.version != expected_version:
            raise ApiError(
                ErrorCode.REFUND_REQUEST_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.REFUND_REQUEST_VERSION_CONFLICT],
                status_code=409,
            )
        refund_request.status = OrderRefundRequest.Status.CANCELED
        refund_request.version += 1
        refund_request.save(update_fields=["status", "version", "updated_at"])
        return _refund_request_payload(refund_request)


def retry_order_refund_request(
    *,
    admin_user: User,
    request_no: str,
    expected_version: int,
) -> dict[str, Any]:
    """后台将退款失败的申请恢复为待审核后重新处理。"""

    with transaction.atomic():
        refund_request = (
            OrderRefundRequest.objects.select_for_update()
            .select_related("order")
            .filter(request_no=request_no)
            .first()
        )
        if refund_request is None:
            raise ApiError(
                ErrorCode.REFUND_REQUEST_NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.REFUND_REQUEST_NOT_FOUND],
                status_code=404,
            )
        if refund_request.status != OrderRefundRequest.Status.FAILED:
            raise ApiError(
                ErrorCode.REFUND_REQUEST_STATE_INVALID,
                ERROR_MESSAGES[ErrorCode.REFUND_REQUEST_STATE_INVALID],
                status_code=409,
            )
        if refund_request.version != expected_version:
            raise ApiError(
                ErrorCode.REFUND_REQUEST_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.REFUND_REQUEST_VERSION_CONFLICT],
                status_code=409,
            )
        refund_request.status = OrderRefundRequest.Status.PENDING
        refund_request.reviewed_by_user_id = admin_user.id
        refund_request.reviewed_at = timezone.now()
        refund_request.failure_reason = ""
        refund_request.version += 1
        refund_request.save(
            update_fields=[
                "status",
                "reviewed_by_user_id",
                "reviewed_at",
                "failure_reason",
                "version",
                "updated_at",
            ]
        )
        return _refund_request_payload(refund_request)
