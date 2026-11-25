"""订单会话访问、消息持久化、已读和实时投递业务服务。"""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from asgiref.sync import async_to_sync
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Max, Q
from django.http import HttpRequest
from django.utils import timezone

from backend.accounts.models import User
from backend.common.context import current_trace_id
from backend.common.display import enum_label
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.media.models import MediaAsset
from backend.media.services import (
    get_available_media_for_purposes,
    get_media_payloads,
    mark_media_referenced,
)
from backend.messaging.models import (
    Conversation,
    ConversationMember,
    ConversationOrderLink,
    Message,
    MessageDelivery,
    MessagingConnectionTicket,
)
from backend.orders.models import Order
from backend.orders.queries import (
    get_chat_orders_for_pair,
    get_latest_chat_order_between_users,
    get_order_for_chat,
    get_order_for_chat_activation,
)
from backend.profiles.models import UserProfile
from backend.providers.profile_services import get_provider_avatar_media_id

ORDER_PAID_SYSTEM_MESSAGE = "订单支付成功，现在可以联系对方沟通服务安排。"


def _error(code: ErrorCode, message: str, *, status_code: int, details: Any = None) -> ApiError:
    """构造聊天模块统一 API 异常。"""

    return ApiError(code, message, status_code=status_code, details=details)


def _format_datetime(value: datetime | None) -> str | None:
    """按项目统一时区格式化 WebSocket 和服务层时间。"""

    if value is None:
        return None
    display_value = timezone.localtime(value, ZoneInfo(settings.API_DISPLAY_TIMEZONE))
    return display_value.strftime(settings.API_DATETIME_FORMAT)


def _message_fingerprint(*, message_type: str, content: str, media_id: str | None) -> str:
    """计算消息请求摘要，用于拒绝同幂等标识的不同消息内容。"""

    raw = json.dumps(
        {
            "message_type": message_type,
            "content": content,
            "media_id": media_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _ticket_hash(raw_ticket: str) -> str:
    """计算 WebSocket 一次性凭证摘要，不保存原始凭证。"""

    return hashlib.sha256(raw_ticket.encode("utf-8")).hexdigest()


def _conversation_state(order: Order, *, now: datetime) -> tuple[bool, str, str]:
    """根据已确认订单状态计算会话是否可见、可发送和目标状态。"""

    if order.status == Order.Status.PENDING_PAYMENT:
        return False, Conversation.Status.CLOSED, "ORDER_NOT_PAID"
    if order.status in {Order.Status.CANCELED, Order.Status.REFUNDED}:
        return True, Conversation.Status.CLOSED, order.status
    if order.status == Order.Status.COMPLETED:
        if order.completed_at is None:
            return True, Conversation.Status.READ_ONLY, "COMPLETED_TIME_MISSING"
        expires_at = order.completed_at + timedelta(
            days=settings.MESSAGING_COMPLETED_SEND_WINDOW_DAYS
        )
        if now <= expires_at:
            return True, Conversation.Status.OPEN, ""
        return True, Conversation.Status.READ_ONLY, "COMPLETED_SEND_WINDOW_EXPIRED"
    return True, Conversation.Status.OPEN, ""


def _apply_conversation_state(
    conversation: Conversation,
    order: Order,
    *,
    now: datetime | None = None,
) -> Conversation:
    """同步会话展示状态，但不修改订单模块内部数据。"""

    current_time = now or timezone.now()
    _, target_status, close_reason = _conversation_state(order, now=current_time)
    if conversation.status == target_status and conversation.close_reason == close_reason:
        return conversation
    update_fields = ["status", "close_reason", "updated_at"]
    conversation.status = target_status
    conversation.close_reason = close_reason
    conversation.closed_at = current_time if target_status != Conversation.Status.OPEN else None
    conversation.version += 1
    update_fields.extend(["closed_at", "version"])
    conversation.save(update_fields=update_fields)
    return conversation


def _profile_nickname(user: User) -> str:
    """读取用户昵称，资料未填写时使用脱敏手机号作为安全兜底。"""

    profile = UserProfile.objects.filter(user_id=user.id).first()
    return getattr(profile, "nickname", None) or user.phone_masked


def _user_summary(user: User, request: HttpRequest | None = None) -> dict[str, Any]:
    """生成聊天参与人公开资料摘要，不返回完整手机号或身份信息。"""

    profile = UserProfile.objects.filter(user_id=user.id).first()
    provider_profile = getattr(user, "provider_profile", None)
    avatar_media_id = (
        get_provider_avatar_media_id(user)
        if provider_profile is not None
        else getattr(profile, "avatar_media_id", None)
    )
    avatar_media = get_media_payloads([avatar_media_id], request) if avatar_media_id else []
    return {
        "user_public_id": str(user.public_id),
        "nickname": _profile_nickname(user),
        "avatar_media": avatar_media[0] if avatar_media else None,
    }


def _order_summary(order: Order, request: HttpRequest | None = None) -> dict[str, Any]:
    """生成会话关联订单的安全展示摘要。"""

    snapshot = order.service_snapshot or {}
    cover_media_id = snapshot.get("cover_media_id")
    cover_media = get_media_payloads([cover_media_id], request) if cover_media_id else []
    return {
        "order_no": str(order.order_no),
        "status": order.status,
        "status_text": enum_label(Order.Status, order.status),
        "service_title": snapshot.get("title") or (order.service.title if order.service else ""),
        "cover_media": cover_media[0] if cover_media else None,
    }


def _member_role(conversation: Conversation, user: User) -> str:
    """读取用户在订单会话中的角色。"""

    member = ConversationMember.objects.filter(conversation=conversation, user=user).first()
    return member.role if member else ConversationMember.Role.CUSTOMER


def _message_payload(
    message: Message,
    *,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """生成消息 API 和 WebSocket 统一响应结构。"""

    media_payloads = (
        get_media_payloads([str(message.media.public_id)], request) if message.media_id else []
    )
    return {
        "message_no": str(message.message_no),
        "conversation_id": str(message.conversation.public_id),
        "sequence": message.sequence,
        "sender_public_id": str(message.sender.public_id) if message.sender_id else None,
        "sender_role": message.sender_role,
        "sender_role_text": enum_label(
            ConversationMember.Role,
            message.sender_role,
        ),
        "message_type": message.message_type,
        "message_type_text": enum_label(Message.MessageType, message.message_type),
        "content": message.content,
        "media": media_payloads[0] if media_payloads else None,
        "client_message_id": message.client_message_id,
        "created_at": _format_datetime(message.created_at),
        "revoked_at": _format_datetime(message.revoked_at),
    }


def _delivery_payload(
    delivery: MessageDelivery, request: HttpRequest | None = None
) -> dict[str, Any]:
    """生成实时消息事件内容，供 Channel Layer 广播。"""

    return {
        "event": "message.created",
        "event_id": str(delivery.event_id),
        "event_type": delivery.event_type,
        "version": delivery.version,
        "occurred_at": _format_datetime(delivery.occurred_at),
        "trace_id": delivery.trace_id,
        **_message_payload(delivery.message, request=request),
    }


def _conversation_pair_key(order: Order) -> str:
    """生成预约用户与服务者稳定配对键，用于限制双方只保留一个共享会话。"""

    return f"customer:{order.user_id}:provider:{order.provider_user_id}"


def _eligible_orders(order: Order) -> list[Order]:
    """读取双方所有已形成聊天资格的订单，最新创建的订单排在最前。"""

    return list(
        get_chat_orders_for_pair(
            customer_user_id=order.user_id,
            provider_user_id=order.provider_user_id,
        )
    )


def _latest_order_for_conversation(
    conversation: Conversation,
    *,
    fallback_order: Order | None = None,
) -> Order | None:
    """返回共享会话当前最新的订单，最新订单决定发送窗口和展示状态。"""

    anchor_order = fallback_order
    if anchor_order is None and conversation.order_id:
        anchor_order = conversation.order
    if anchor_order is None:
        return None
    orders = get_chat_orders_for_pair(
        customer_user_id=anchor_order.user_id,
        provider_user_id=anchor_order.provider_user_id,
    )
    linked_order_ids = set(conversation.order_links.values_list("order_id", flat=True))
    linked_order_ids.add(conversation.order_id)
    return orders.filter(pk__in=linked_order_ids).first() or orders.first()


def _merge_legacy_conversations(
    canonical: Conversation,
    duplicates: list[Conversation],
) -> None:
    """兼容合并旧版按订单创建的重复会话，保留消息事实且不物理删除记录。"""

    if not duplicates:
        return
    now = timezone.now()
    canonical_client_keys = set(
        Message.objects.filter(
            conversation=canonical,
            client_message_id__isnull=False,
        ).values_list("sender_id", "client_message_id")
    )
    next_sequence = canonical.next_sequence
    duplicate_ids = [item.pk for item in duplicates]
    duplicate_messages = list(
        Message.objects.filter(conversation_id__in=duplicate_ids).order_by("created_at", "id")
    )
    moved_messages = []
    for message in duplicate_messages:
        client_key = (message.sender_id, message.client_message_id)
        if message.client_message_id is not None and client_key in canonical_client_keys:
            continue
        message.conversation = canonical
        next_sequence += 1
        message.sequence = next_sequence
        message.updated_at = now
        moved_messages.append(message)
        if message.client_message_id is not None:
            canonical_client_keys.add(client_key)
    if moved_messages:
        Message.objects.bulk_update(
            moved_messages,
            ["conversation", "sequence", "updated_at"],
        )
        MessageDelivery.objects.filter(message__in=moved_messages).update(
            conversation=canonical,
            updated_at=now,
        )
        canonical.next_sequence = next_sequence
        canonical.version += 1
        canonical.updated_at = now
        canonical.save(update_fields=["next_sequence", "version", "updated_at"])
    ConversationOrderLink.objects.filter(conversation_id__in=duplicate_ids).update(
        conversation=canonical
    )
    ConversationMember.objects.filter(
        conversation_id__in=duplicate_ids,
        hidden_at__isnull=True,
    ).update(hidden_at=now)


def _find_or_create_shared_conversation(order: Order) -> Conversation:
    """查找或创建双方唯一共享会话，并兼容旧版同双方多个订单会话。"""

    pair_key = _conversation_pair_key(order)
    eligible_orders = _eligible_orders(order)
    eligible_order_ids = [item.pk for item in eligible_orders]
    candidates = list(
        Conversation.objects.filter(
            Q(order_id__in=eligible_order_ids)
            | Q(order_links__order_id__in=eligible_order_ids)
            | Q(pair_key=pair_key)
        )
        .distinct()
        .order_by("id")
    )
    canonical = next((item for item in candidates if item.pair_key == pair_key), None)
    if canonical is None and candidates:
        canonical = candidates[0]
        canonical.pair_key = pair_key
        canonical.save(update_fields=["pair_key"])
    if canonical is None:
        try:
            with transaction.atomic():
                canonical, _ = Conversation.objects.get_or_create(
                    pair_key=pair_key,
                    defaults={"order": order},
                )
        except IntegrityError:
            canonical = Conversation.objects.get(pair_key=pair_key)
    else:
        duplicates = [item for item in candidates if item.pk != canonical.pk]
        _merge_legacy_conversations(canonical, duplicates)
    for eligible_order in eligible_orders:
        ConversationOrderLink.objects.update_or_create(
            order=eligible_order,
            defaults={"conversation": canonical},
        )
    return canonical


def _ensure_members(
    conversation: Conversation,
    order: Order,
    *,
    restore_user_ids: set[int] | None = None,
) -> None:
    """创建双方稳定成员关系，并按需要恢复指定用户隐藏的会话。"""

    restore_user_ids = restore_user_ids or set()
    member_defaults = (
        (order.user_id, ConversationMember.Role.CUSTOMER),
        (order.provider_user_id, ConversationMember.Role.PROVIDER),
    )
    for user_id, role in member_defaults:
        member, _ = ConversationMember.objects.get_or_create(
            conversation=conversation,
            user_id=user_id,
            defaults={"role": role},
        )
        if user_id in restore_user_ids and member.hidden_at is not None:
            member.hidden_at = None
            member.save(update_fields=["hidden_at"])


def _ensure_conversation_and_members(
    order: Order,
    *,
    restore_user_ids: set[int] | None = None,
) -> Conversation:
    """创建或恢复双方共享会话、订单来源关系，并同步最新订单状态。"""

    conversation = _find_or_create_shared_conversation(order)
    _ensure_members(conversation, order, restore_user_ids=restore_user_ids)
    latest_order = _latest_order_for_conversation(conversation, fallback_order=order) or order
    return _apply_conversation_state(conversation, latest_order)


def create_connection_ticket(*, user: User) -> dict[str, Any]:
    """签发 60 秒级短时效、一次性的 WebSocket 连接凭证。"""

    raw_ticket = secrets.token_urlsafe(48)
    expires_at = timezone.now() + timedelta(seconds=settings.MESSAGING_WS_TICKET_TTL_SECONDS)
    MessagingConnectionTicket.objects.create(
        ticket_hash=_ticket_hash(raw_ticket),
        user=user,
        expires_at=expires_at,
    )
    return {
        "ticket": raw_ticket,
        "expires_at": _format_datetime(expires_at),
        "expires_in_seconds": settings.MESSAGING_WS_TICKET_TTL_SECONDS,
    }


def consume_connection_ticket(*, raw_ticket: str) -> User:
    """一次性消费 WebSocket 凭证并返回绑定用户，重复使用必须拒绝。"""

    now = timezone.now()
    with transaction.atomic():
        ticket = (
            MessagingConnectionTicket.objects.select_for_update()
            .select_related("user")
            .filter(ticket_hash=_ticket_hash(raw_ticket))
            .first()
        )
        if ticket is None:
            raise _error(
                ErrorCode.MESSAGING_TICKET_INVALID,
                ERROR_MESSAGES[ErrorCode.MESSAGING_TICKET_INVALID],
                status_code=401,
            )
        if ticket.used_at is not None:
            raise _error(
                ErrorCode.MESSAGING_TICKET_USED,
                ERROR_MESSAGES[ErrorCode.MESSAGING_TICKET_USED],
                status_code=401,
            )
        if ticket.expires_at <= now:
            raise _error(
                ErrorCode.MESSAGING_TICKET_EXPIRED,
                ERROR_MESSAGES[ErrorCode.MESSAGING_TICKET_EXPIRED],
                status_code=401,
            )
        ticket.used_at = now
        ticket.save(update_fields=["used_at"])
        if ticket.user.status != User.Status.ACTIVE:
            raise _error(
                ErrorCode.AUTH_ACCOUNT_NOT_ALLOWED,
                ERROR_MESSAGES[ErrorCode.AUTH_ACCOUNT_NOT_ALLOWED],
                status_code=403,
            )
        return ticket.user


def get_or_create_order_conversation(
    *,
    user: User,
    order_no: str,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """按订单号创建或读取当前用户有权访问的订单会话。"""

    order = get_order_for_chat(order_no=order_no, user_id=user.id)
    if order is None:
        raise _error(
            ErrorCode.MESSAGING_NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.MESSAGING_NOT_FOUND],
            status_code=404,
        )
    can_view, _, _ = _conversation_state(order, now=timezone.now())
    if not can_view:
        raise _error(
            ErrorCode.MESSAGING_STATE_INVALID,
            ERROR_MESSAGES[ErrorCode.MESSAGING_STATE_INVALID],
            status_code=409,
            details={"order_status": order.status},
        )
    with transaction.atomic():
        conversation = _ensure_conversation_and_members(
            order,
            restore_user_ids={user.id},
        )
    return conversation_detail(conversation=conversation, user=user, request=request)


def get_or_create_provider_conversation(
    *,
    user: User,
    provider_public_id: str,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """按服务者打开或恢复共享会话，不要求前端保存内部订单号。"""

    try:
        provider_user = User.objects.get(public_id=provider_public_id, status=User.Status.ACTIVE)
    except (User.DoesNotExist, ValueError):
        raise _error(
            ErrorCode.MESSAGING_NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.MESSAGING_NOT_FOUND],
            status_code=404,
        ) from None
    order = get_latest_chat_order_between_users(
        first_user_id=user.id,
        second_user_id=provider_user.id,
    )
    if order is None:
        raise _error(
            ErrorCode.MESSAGING_NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.MESSAGING_NOT_FOUND],
            status_code=404,
        )
    with transaction.atomic():
        conversation = _ensure_conversation_and_members(
            order,
            restore_user_ids={user.id},
        )
    return conversation_detail(conversation=conversation, user=user, request=request)


def ensure_order_paid_conversation(*, order_no: str) -> dict[str, Any]:
    """订单支付成功后幂等创建双方会话和系统提示，确保双方会话列表可见。"""

    order = get_order_for_chat_activation(order_no=order_no)
    if order is None:
        raise _error(
            ErrorCode.MESSAGING_NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.MESSAGING_NOT_FOUND],
            status_code=404,
        )
    if order.status == Order.Status.PENDING_PAYMENT:
        raise _error(
            ErrorCode.MESSAGING_STATE_INVALID,
            ERROR_MESSAGES[ErrorCode.MESSAGING_STATE_INVALID],
            status_code=409,
            details={"order_status": order.status},
        )

    content = ORDER_PAID_SYSTEM_MESSAGE
    client_message_id = f"system:order-paid:{order.order_no}"
    request_fingerprint = _message_fingerprint(
        message_type=Message.MessageType.SYSTEM,
        content=content,
        media_id=None,
    )
    with transaction.atomic():
        conversation = _ensure_conversation_and_members(
            order,
            restore_user_ids={order.user_id, order.provider_user_id},
        )
        locked_conversation = Conversation.objects.select_for_update().get(pk=conversation.pk)
        sequence = locked_conversation.next_sequence + 1
        message, created = Message.objects.get_or_create(
            conversation=locked_conversation,
            sender=None,
            client_message_id=client_message_id,
            defaults={
                "sender_role": Message.SenderRole.SYSTEM,
                "message_type": Message.MessageType.SYSTEM,
                "content": content,
                "request_fingerprint": request_fingerprint,
                "sequence": sequence,
            },
        )
        if not created and message.request_fingerprint != request_fingerprint:
            raise _error(
                ErrorCode.MESSAGING_IDEMPOTENCY_CONFLICT,
                ERROR_MESSAGES[ErrorCode.MESSAGING_IDEMPOTENCY_CONFLICT],
                status_code=409,
            )
        if created:
            locked_conversation.next_sequence = sequence
            locked_conversation.version += 1
            locked_conversation.updated_at = timezone.now()
            locked_conversation.save(update_fields=["next_sequence", "version", "updated_at"])

        event_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"jianmianliao:messaging:message:{message.message_no}:websocket.broadcast",
        )
        delivery, _ = MessageDelivery.objects.get_or_create(
            event_id=event_id,
            consumer_name="websocket.broadcast",
            defaults={
                "message": message,
                "conversation": locked_conversation,
                "event_type": "MESSAGE_CREATED",
                "occurred_at": message.created_at,
                "trace_id": current_trace_id(),
            },
        )

    result = {
        "message": _message_payload(message),
        "reused": not created,
        "delivery_event_id": str(delivery.event_id),
    }
    if created or delivery.status == MessageDelivery.Status.PENDING:
        schedule_message_delivery(result)
    return result


def _get_membership(
    *,
    conversation_id: str,
    user: User,
    allow_hidden: bool = False,
) -> ConversationMember:
    """校验用户是可见会话成员并返回成员记录，隐藏会话默认拒绝直接访问。"""

    try:
        queryset = ConversationMember.objects.select_related(
            "conversation__order__user",
            "conversation__order__provider_user",
            "conversation__order__service",
        ).filter(conversation__public_id=conversation_id, user=user)
        if not allow_hidden:
            queryset = queryset.filter(hidden_at__isnull=True)
        member = queryset.first()
    except ValueError:
        member = None
    if member is None:
        raise _error(
            ErrorCode.PERMISSION_DENIED,
            ERROR_MESSAGES[ErrorCode.PERMISSION_DENIED],
            status_code=403,
        )
    latest_order = _latest_order_for_conversation(
        member.conversation,
        fallback_order=member.conversation.order,
    )
    if latest_order is not None:
        _apply_conversation_state(member.conversation, latest_order)
    return member


def hide_conversation(*, user: User, conversation_id: str) -> dict[str, Any]:
    """按成员维度隐藏会话，不删除消息，后续可通过订单或服务者入口恢复。"""

    member = _get_membership(
        conversation_id=conversation_id,
        user=user,
        allow_hidden=True,
    )
    hidden_at = member.hidden_at
    if hidden_at is None:
        hidden_at = timezone.now()
        member.hidden_at = hidden_at
        member.save(update_fields=["hidden_at"])
    return {
        "conversation_id": str(member.conversation.public_id),
        "hidden_at": _format_datetime(hidden_at),
    }


def validate_conversation_subscription(
    *,
    user_id: int,
    conversation_id: str,
) -> dict[str, Any]:
    """校验 WebSocket 订阅请求并返回安全会话标识。"""

    user = User.objects.get(pk=user_id)
    member = _get_membership(conversation_id=conversation_id, user=user)
    return {
        "conversation_id": str(member.conversation.public_id),
        "latest_sequence": member.conversation.next_sequence,
        "last_read_sequence": member.last_read_sequence,
    }


def conversation_detail(
    *,
    conversation: Conversation,
    user: User,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """返回单个订单会话详情、参与人、订单摘要和未读数。"""

    member = ConversationMember.objects.select_related("conversation__order").get(
        conversation=conversation,
        user=user,
    )
    orders = _eligible_orders(conversation.order)
    order = (
        _latest_order_for_conversation(
            conversation,
            fallback_order=conversation.order,
        )
        or conversation.order
    )
    latest_sequence = conversation.next_sequence
    unread_count = max(latest_sequence - member.last_read_sequence, 0)
    last_message = conversation.messages.order_by("-sequence").first()
    return {
        "conversation_id": str(conversation.public_id),
        "order": _order_summary(order, request),
        "orders": [_order_summary(item, request) for item in orders],
        "order_count": len(orders),
        "participants": [
            _user_summary(order.user, request),
            _user_summary(order.provider_user, request),
        ],
        "status": conversation.status,
        "status_text": enum_label(Conversation.Status, conversation.status),
        "can_send": conversation.status == Conversation.Status.OPEN,
        "close_reason": conversation.close_reason,
        "latest_sequence": latest_sequence,
        "last_read_sequence": member.last_read_sequence,
        "unread_count": unread_count,
        "last_message": _message_payload(last_message, request=request) if last_message else None,
        "version": conversation.version,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
    }


def list_conversations(
    *,
    user: User,
    request: HttpRequest | None = None,
    cursor: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """按最近更新时间返回当前用户订单会话和未读摘要。"""

    queryset = ConversationMember.objects.filter(
        user=user,
        hidden_at__isnull=True,
    ).select_related(
        "conversation__order__user",
        "conversation__order__provider_user",
        "conversation__order__service",
    )
    if cursor:
        try:
            cursor_updated_at_raw, cursor_id_raw = cursor.rsplit(":", 1)
            cursor_updated_at = datetime.fromisoformat(cursor_updated_at_raw)
            cursor_id = int(cursor_id_raw)
        except (TypeError, ValueError):
            raise _error(
                ErrorCode.MESSAGING_INVALID,
                ERROR_MESSAGES[ErrorCode.MESSAGING_INVALID],
                status_code=400,
                details={"cursor": "游标值不正确"},
            ) from None
        queryset = queryset.filter(
            Q(conversation__updated_at__lt=cursor_updated_at)
            | Q(conversation__updated_at=cursor_updated_at, conversation__id__lt=cursor_id)
        )
    members = list(queryset.order_by("-conversation__updated_at", "-conversation__id")[: limit + 1])
    has_more = len(members) > limit
    members = members[:limit]
    items = [
        conversation_detail(conversation=item.conversation, user=user, request=request)
        for item in members
    ]
    next_cursor = None
    if has_more and members:
        last_conversation = members[-1].conversation
        next_cursor = f"{last_conversation.updated_at.isoformat()}:{last_conversation.id}"
    return {
        "items": items,
        "next_cursor": next_cursor,
        "has_more": has_more,
        "limit": limit,
    }


def list_messages(
    *,
    user: User,
    conversation_id: str,
    request: HttpRequest | None = None,
    limit: int = 20,
    before_sequence: int | None = None,
    after_sequence: int | None = None,
) -> dict[str, Any]:
    """读取会话历史或断线补偿消息，并使用 sequence 游标分页。"""

    member = _get_membership(conversation_id=conversation_id, user=user)
    conversation = member.conversation
    if before_sequence is not None and after_sequence is not None:
        raise _error(
            ErrorCode.MESSAGING_INVALID,
            ERROR_MESSAGES[ErrorCode.MESSAGING_INVALID],
            status_code=400,
            details={"before_sequence": "不能与 after_sequence 同时使用"},
        )
    queryset = Message.objects.filter(conversation=conversation, revoked_at__isnull=True)
    if after_sequence is not None:
        messages = list(
            queryset.filter(sequence__gt=after_sequence)
            .select_related("sender", "media")
            .order_by("sequence")[: limit + 1]
        )
        has_more = len(messages) > limit
        messages = messages[:limit]
        next_cursor = messages[-1].sequence if messages else after_sequence
        return {
            "conversation_id": str(conversation.public_id),
            "items": [_message_payload(item, request=request) for item in messages],
            "next_cursor": next_cursor,
            "has_more": has_more,
            "latest_sequence": conversation.next_sequence,
            "limit": limit,
        }
    cursor_sequence = (
        before_sequence if before_sequence is not None else conversation.next_sequence + 1
    )
    messages = list(
        queryset.filter(sequence__lt=cursor_sequence)
        .select_related("sender", "media")
        .order_by("-sequence")[: limit + 1]
    )
    has_more = len(messages) > limit
    messages = list(reversed(messages[:limit]))
    next_cursor = messages[0].sequence if has_more and messages else None
    return {
        "conversation_id": str(conversation.public_id),
        "items": [_message_payload(item, request=request) for item in messages],
        "next_cursor": next_cursor,
        "has_more": has_more,
        "latest_sequence": conversation.next_sequence,
        "limit": limit,
    }


def create_message(
    *,
    user: User,
    conversation_id: str,
    message_type: str,
    content: str,
    client_message_id: str,
    media_id: str | None = None,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """幂等创建聊天消息并在事务内分配严格递增序号。"""

    member = _get_membership(conversation_id=conversation_id, user=user)
    conversation = member.conversation
    content = content.strip()
    if message_type not in {Message.MessageType.TEXT, Message.MessageType.IMAGE}:
        raise _error(
            ErrorCode.MESSAGING_INVALID,
            ERROR_MESSAGES[ErrorCode.MESSAGING_INVALID],
            status_code=400,
            details={"message_type": "只支持 TEXT 或 IMAGE"},
        )
    if not client_message_id or len(client_message_id) > 64:
        raise _error(
            ErrorCode.MESSAGING_INVALID,
            ERROR_MESSAGES[ErrorCode.MESSAGING_INVALID],
            status_code=400,
            details={"client_message_id": "客户端消息幂等标识必须为 1 到 64 个字符"},
        )
    if message_type == Message.MessageType.TEXT and not content:
        raise _error(
            ErrorCode.MESSAGING_INVALID,
            ERROR_MESSAGES[ErrorCode.MESSAGING_INVALID],
            status_code=400,
            details={"content": "文本消息不能为空"},
        )
    if len(content) > settings.MESSAGING_MESSAGE_MAX_LENGTH:
        raise _error(
            ErrorCode.MESSAGING_INVALID,
            ERROR_MESSAGES[ErrorCode.MESSAGING_INVALID],
            status_code=400,
            details={"content": f"消息不能超过 {settings.MESSAGING_MESSAGE_MAX_LENGTH} 个字符"},
        )
    media_asset: MediaAsset | None = None
    if message_type == Message.MessageType.IMAGE:
        if not media_id:
            raise _error(
                ErrorCode.MESSAGING_MEDIA_INVALID,
                ERROR_MESSAGES[ErrorCode.MESSAGING_MEDIA_INVALID],
                status_code=400,
            )
        try:
            media_assets = get_available_media_for_purposes(
                user=user,
                purposes={MediaAsset.Purpose.CHAT_IMAGE},
                media_ids=[media_id],
            )
            media_asset = media_assets[0]
        except ApiError as exc:
            raise _error(
                ErrorCode.MESSAGING_MEDIA_INVALID,
                ERROR_MESSAGES[ErrorCode.MESSAGING_MEDIA_INVALID],
                status_code=exc.status_code,
            ) from exc
    elif media_id:
        raise _error(
            ErrorCode.MESSAGING_INVALID,
            ERROR_MESSAGES[ErrorCode.MESSAGING_INVALID],
            status_code=400,
            details={"media_id": "文本消息不能携带图片媒体"},
        )
    request_fingerprint = _message_fingerprint(
        message_type=message_type,
        content=content,
        media_id=media_id,
    )
    with transaction.atomic():
        locked_conversation = Conversation.objects.select_for_update().get(pk=conversation.pk)
        latest_order = _latest_order_for_conversation(
            locked_conversation,
            fallback_order=locked_conversation.order,
        )
        if latest_order is None:
            raise _error(
                ErrorCode.MESSAGING_STATE_INVALID,
                ERROR_MESSAGES[ErrorCode.MESSAGING_STATE_INVALID],
                status_code=409,
                details={"status": Conversation.Status.CLOSED},
            )
        locked_order = Order.objects.select_for_update().get(pk=latest_order.pk)
        _, target_status, _ = _conversation_state(locked_order, now=timezone.now())
        if target_status != Conversation.Status.OPEN:
            raise _error(
                ErrorCode.MESSAGING_STATE_INVALID,
                ERROR_MESSAGES[ErrorCode.MESSAGING_STATE_INVALID],
                status_code=409,
                details={"status": target_status},
            )
        existing = Message.objects.filter(
            conversation=locked_conversation,
            sender=user,
            client_message_id=client_message_id,
        ).first()
        if existing is not None:
            if existing.request_fingerprint != request_fingerprint:
                raise _error(
                    ErrorCode.MESSAGING_IDEMPOTENCY_CONFLICT,
                    ERROR_MESSAGES[ErrorCode.MESSAGING_IDEMPOTENCY_CONFLICT],
                    status_code=409,
                )
            delivery = MessageDelivery.objects.filter(
                message=existing,
                consumer_name="websocket.broadcast",
            ).first()
            return {
                "message": _message_payload(existing, request=request),
                "ack": {
                    "client_message_id": client_message_id,
                    "message_no": str(existing.message_no),
                    "sequence": existing.sequence,
                    "reused": True,
                },
                "delivery_event_id": str(delivery.event_id) if delivery else None,
            }
        sequence = locked_conversation.next_sequence + 1
        message = Message.objects.create(
            conversation=locked_conversation,
            sender=user,
            sender_role=member.role,
            message_type=message_type,
            content=content,
            media=media_asset,
            client_message_id=client_message_id,
            request_fingerprint=request_fingerprint,
            sequence=sequence,
        )
        locked_conversation.next_sequence = sequence
        locked_conversation.version += 1
        locked_conversation.updated_at = timezone.now()
        locked_conversation.save(update_fields=["next_sequence", "version", "updated_at"])
        if media_asset is not None:
            mark_media_referenced([str(media_asset.public_id)])
        delivery = MessageDelivery.objects.create(
            message=message,
            conversation=locked_conversation,
            occurred_at=message.created_at,
            trace_id=current_trace_id(),
        )
    return {
        "message": _message_payload(message, request=request),
        "ack": {
            "client_message_id": client_message_id,
            "message_no": str(message.message_no),
            "sequence": message.sequence,
            "reused": False,
        },
        "delivery_event_id": str(delivery.event_id),
    }


def dispatch_message_delivery(
    *,
    event_id: str,
    consumer_name: str = "websocket.broadcast",
) -> bool:
    """将 Outbox 消息事件投递到实时 Channel Layer，失败保留待重试。"""

    try:
        delivery = MessageDelivery.objects.select_related(
            "message__sender",
            "message__media",
            "message__conversation",
            "conversation",
        ).get(event_id=event_id, consumer_name=consumer_name)
    except (MessageDelivery.DoesNotExist, ValueError):
        return False
    if delivery.status == MessageDelivery.Status.DELIVERED:
        return True
    from channels.layers import get_channel_layer

    channel_layer = get_channel_layer()
    if channel_layer is None:
        return False
    try:
        async_to_sync(channel_layer.group_send)(
            f"messaging.conversation.{delivery.conversation.public_id}",
            {"type": "message.created", "payload": _delivery_payload(delivery)},
        )
    except Exception as exc:
        delivery.status = MessageDelivery.Status.PENDING
        delivery.retry_count += 1
        delivery.last_error = f"{type(exc).__name__}: 实时消息投递失败"[:500]
        delivery.save(update_fields=["status", "retry_count", "last_error", "updated_at"])
        return False
    delivery.status = MessageDelivery.Status.DELIVERED
    delivery.delivered_at = timezone.now()
    delivery.last_error = ""
    delivery.save(update_fields=["status", "delivered_at", "last_error", "updated_at"])
    return True


def retry_pending_message_deliveries(*, limit: int = 100) -> dict[str, int]:
    """重试尚未投递的聊天 Outbox 事件，供幂等 Celery 任务调用。"""

    deliveries = MessageDelivery.objects.filter(status=MessageDelivery.Status.PENDING).order_by(
        "created_at"
    )[:limit]
    delivered_count = 0
    for delivery in deliveries:
        if dispatch_message_delivery(
            event_id=str(delivery.event_id),
            consumer_name=delivery.consumer_name,
        ):
            delivered_count += 1
    return {"processed_count": len(deliveries), "delivered_count": delivered_count}


def mark_conversation_read(
    *,
    user: User,
    conversation_id: str,
    sequence: int | None = None,
) -> dict[str, Any]:
    """更新成员已读位置，已读位置只能单调递增。"""

    member = _get_membership(conversation_id=conversation_id, user=user)
    conversation = member.conversation
    target_sequence = sequence if sequence is not None else conversation.next_sequence
    if target_sequence < 0 or target_sequence > conversation.next_sequence:
        raise _error(
            ErrorCode.MESSAGING_INVALID,
            ERROR_MESSAGES[ErrorCode.MESSAGING_INVALID],
            status_code=400,
            details={"sequence": "已读序号必须在当前会话消息范围内"},
        )
    with transaction.atomic():
        locked_member = ConversationMember.objects.select_for_update().get(pk=member.pk)
        locked_member.last_read_sequence = max(
            locked_member.last_read_sequence,
            target_sequence,
        )
        locked_member.last_read_at = timezone.now()
        locked_member.save(update_fields=["last_read_sequence", "last_read_at"])
    unread_count = Message.objects.filter(
        conversation=conversation,
        sequence__gt=locked_member.last_read_sequence,
        revoked_at__isnull=True,
    ).count()
    return {
        "conversation_id": str(conversation.public_id),
        "last_read_sequence": locked_member.last_read_sequence,
        "unread_count": unread_count,
    }


def unread_summary(*, user: User) -> dict[str, Any]:
    """返回当前用户所有订单会话的未读消息总数和会话数。"""

    rows = (
        ConversationMember.objects.filter(user=user, hidden_at__isnull=True)
        .annotate(
            latest_sequence=Max("conversation__messages__sequence"),
            unread_count=Count(
                "conversation__messages",
                filter=Q(
                    conversation__messages__sequence__gt=F("last_read_sequence"),
                    conversation__messages__revoked_at__isnull=True,
                ),
            ),
        )
        .values("conversation__public_id", "unread_count")
    )
    items = [
        {
            "conversation_id": str(row["conversation__public_id"]),
            "unread_count": row["unread_count"],
        }
        for row in rows
    ]
    return {
        "total_unread": sum(item["unread_count"] for item in items),
        "conversation_count": sum(1 for item in items if item["unread_count"] > 0),
        "items": items,
    }


def schedule_message_delivery(result: dict[str, Any]) -> None:
    """在数据库事务提交后调度实时投递，不让 Redis 故障影响消息保存。"""

    event_id = result.get("delivery_event_id")
    if not event_id:
        return

    def _dispatch() -> None:
        dispatch_message_delivery(event_id=event_id)

    transaction.on_commit(_dispatch)
