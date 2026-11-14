"""订单实时聊天的权限、状态、幂等、分页、票据和 WebSocket 测试。"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from backend.accounts.models import AuthToken, User
from backend.accounts.services import _token_raw, hash_token
from backend.common.errors import ErrorCode
from backend.common.exceptions import ApiError
from backend.config.asgi import application
from backend.media.models import MediaAsset
from backend.messaging.models import (
    Conversation,
    ConversationMember,
    ConversationOrderLink,
    Message,
)
from backend.messaging.services import (
    consume_connection_ticket,
    create_connection_ticket,
    create_message,
    ensure_order_paid_conversation,
    get_or_create_order_conversation,
    get_or_create_provider_conversation,
    hide_conversation,
    list_conversations,
    list_messages,
    mark_conversation_read,
    unread_summary,
)
from backend.orders.models import Order
from backend.scheduling.models import ScheduleSlot

pytestmark = pytest.mark.django_db


def create_chat_user(phone_hash: str) -> User:
    """创建聊天测试用户。"""

    return User.objects.create(
        phone_hash=phone_hash,
        phone_masked=f"{phone_hash[:3]}****{phone_hash[-4:]}",
        initial_role_selected=True,
        primary_role=User.InitialRole.USER,
        default_workspace=User.Workspace.USER_HOME,
    )


def auth_headers(user: User) -> dict[str, str]:
    """创建有效访问令牌请求头。"""

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


def create_chat_order(
    *,
    status: Order.Status = Order.Status.PENDING_ACCEPT,
    completed_at=None,
    customer: User | None = None,
    provider: User | None = None,
) -> tuple[User, User, Order]:
    """创建不依赖真实支付和排期业务的订单聊天夹具。"""

    customer = customer or create_chat_user(f"chat-customer-{uuid.uuid4().hex[:12]}")
    provider = provider or create_chat_user(f"chat-provider-{uuid.uuid4().hex[:12]}")
    now = timezone.now()
    slot_start = now + timedelta(
        days=1,
        minutes=ScheduleSlot.objects.filter(provider_user=provider).count() * 120,
    )
    slot = ScheduleSlot.objects.create(
        provider_user=provider,
        start_at=slot_start,
        end_at=slot_start + timedelta(hours=1),
    )
    order = Order.objects.create(
        user=customer,
        provider_user=provider,
        schedule_slot=slot,
        service_snapshot={"title": "台球助教", "cover_media_id": None},
        provider_snapshot={},
        slot_snapshot={},
        original_price_amount_minor=6800,
        payable_amount_minor=6800,
        paid_amount_minor=6800,
        status=status,
        completed_at=completed_at,
    )
    return customer, provider, order


def api_client() -> APIClient:
    """创建项目 API 测试客户端。"""

    return APIClient()


def test_only_order_participants_can_open_conversation() -> None:
    """只有订单预约用户和服务者能获取订单会话。"""

    customer, provider, order = create_chat_order()
    outsider = create_chat_user("chat-outsider")
    client = api_client()

    response = client.get(
        f"/api/v1/orders/{order.order_no}/conversation/",
        **auth_headers(customer),
    )
    assert response.status_code == 200
    assert response.json()["data"]["order"]["service_title"] == "台球助教"
    assert response.json()["data"]["can_send"] is True

    provider_response = client.get(
        f"/api/v1/orders/{order.order_no}/conversation/",
        **auth_headers(provider),
    )
    assert provider_response.status_code == 200

    outsider_response = client.get(
        f"/api/v1/orders/{order.order_no}/conversation/",
        **auth_headers(outsider),
    )
    assert outsider_response.status_code == 404
    assert outsider_response.json()["code"] == ErrorCode.MESSAGING_NOT_FOUND


def test_unpaid_order_does_not_open_chat() -> None:
    """待支付订单不创建或开放聊天会话。"""

    customer, _, order = create_chat_order(status=Order.Status.PENDING_PAYMENT)
    response = api_client().get(
        f"/api/v1/orders/{order.order_no}/conversation/",
        **auth_headers(customer),
    )

    assert response.status_code == 409
    assert response.json()["code"] == ErrorCode.MESSAGING_STATE_INVALID


def test_message_creation_is_idempotent_and_conflict_safe() -> None:
    """同幂等标识只生成一条消息，不同内容必须返回冲突。"""

    customer, _, order = create_chat_order()
    conversation = get_or_create_order_conversation(user=customer, order_no=str(order.order_no))
    first = create_message(
        user=customer,
        conversation_id=str(conversation["conversation_id"]),
        message_type="TEXT",
        content="你好",
        client_message_id="client-001",
    )
    repeated = create_message(
        user=customer,
        conversation_id=str(conversation["conversation_id"]),
        message_type="TEXT",
        content="你好",
        client_message_id="client-001",
    )

    assert first["ack"]["reused"] is False
    assert repeated["ack"]["reused"] is True
    assert repeated["message"]["message_no"] == first["message"]["message_no"]
    assert Message.objects.filter(conversation__order=order).count() == 1

    with pytest.raises(ApiError) as conflict:
        create_message(
            user=customer,
            conversation_id=str(conversation["conversation_id"]),
            message_type="TEXT",
            content="内容变化",
            client_message_id="client-001",
        )
    assert conflict.value.machine_code == ErrorCode.MESSAGING_IDEMPOTENCY_CONFLICT


def test_read_position_is_monotonic_and_unread_summary_is_correct() -> None:
    """已读位置只能向前，未读汇总会过滤发送者自己的消息。"""

    customer, provider, order = create_chat_order()
    conversation = get_or_create_order_conversation(user=customer, order_no=str(order.order_no))
    conversation_id = str(conversation["conversation_id"])
    create_message(
        user=customer,
        conversation_id=conversation_id,
        message_type="TEXT",
        content="第一条",
        client_message_id="read-001",
    )
    second = create_message(
        user=provider,
        conversation_id=conversation_id,
        message_type="TEXT",
        content="第二条",
        client_message_id="read-002",
    )

    result = mark_conversation_read(user=customer, conversation_id=conversation_id, sequence=1)
    assert result["last_read_sequence"] == 1
    assert result["unread_count"] == 1
    result = mark_conversation_read(user=customer, conversation_id=conversation_id, sequence=0)
    assert result["last_read_sequence"] == 1
    assert unread_summary(user=customer)["total_unread"] == 1
    assert second["message"]["sequence"] == 2


@override_settings(MESSAGING_COMPLETED_SEND_WINDOW_DAYS=2)
def test_completed_order_send_window_is_configurable() -> None:
    """订单完成后的聊天发送窗口可由环境配置，窗口外自动转为只读。"""

    active_customer, _, active_order = create_chat_order(
        status=Order.Status.COMPLETED,
        completed_at=timezone.now() - timedelta(days=1),
    )
    expired_customer, _, expired_order = create_chat_order(
        status=Order.Status.COMPLETED,
        completed_at=timezone.now() - timedelta(days=3),
    )
    active = get_or_create_order_conversation(
        user=active_customer,
        order_no=str(active_order.order_no),
    )
    expired = get_or_create_order_conversation(
        user=expired_customer,
        order_no=str(expired_order.order_no),
    )

    assert active["can_send"] is True
    assert expired["status"] == Conversation.Status.READ_ONLY
    assert expired["can_send"] is False


def test_multiple_orders_reuse_one_conversation_and_latest_order_controls_state() -> None:
    """同一用户与服务者的多个订单复用共享会话，最新订单决定聊天状态。"""

    customer, provider, completed_order = create_chat_order(
        status=Order.Status.COMPLETED,
        completed_at=timezone.now() - timedelta(days=8),
    )
    completed = get_or_create_order_conversation(
        user=customer,
        order_no=str(completed_order.order_no),
    )
    _, _, new_order = create_chat_order(customer=customer, provider=provider)
    latest = get_or_create_order_conversation(user=customer, order_no=str(new_order.order_no))

    assert latest["conversation_id"] == completed["conversation_id"]
    assert latest["order"]["order_no"] == str(new_order.order_no)
    assert latest["order_count"] == 2
    assert latest["can_send"] is True
    assert Conversation.objects.count() == 1
    assert ConversationOrderLink.objects.count() == 2


def test_paid_order_activation_is_idempotent_and_adds_one_prompt_per_order() -> None:
    """支付成功提示按订单幂等，重复支付通知不重复生成消息。"""

    customer, provider, first_order = create_chat_order()
    first = ensure_order_paid_conversation(order_no=str(first_order.order_no))
    repeated = ensure_order_paid_conversation(order_no=str(first_order.order_no))
    _, _, second_order = create_chat_order(customer=customer, provider=provider)
    second = ensure_order_paid_conversation(order_no=str(second_order.order_no))

    assert repeated["message"]["message_no"] == first["message"]["message_no"]
    assert repeated["reused"] is True
    assert second["message"]["conversation_id"] == first["message"]["conversation_id"]
    assert Message.objects.filter(message_type=Message.MessageType.SYSTEM).count() == 2


def test_hidden_conversation_is_user_scoped_and_can_be_reopened() -> None:
    """删除会话只影响当前用户，历史保留且可按服务者入口恢复。"""

    customer, provider, order = create_chat_order()
    conversation = get_or_create_order_conversation(user=customer, order_no=str(order.order_no))
    conversation_id = str(conversation["conversation_id"])
    create_message(
        user=customer,
        conversation_id=conversation_id,
        message_type="TEXT",
        content="隐藏前消息",
        client_message_id="hide-001",
    )
    hidden = hide_conversation(user=customer, conversation_id=conversation_id)

    assert hidden["hidden_at"] is not None
    assert list_conversations(user=customer)["items"] == []
    assert unread_summary(user=customer)["total_unread"] == 0
    assert len(list_conversations(user=provider)["items"]) == 1
    with pytest.raises(ApiError) as denied:
        list_messages(user=customer, conversation_id=conversation_id)
    assert denied.value.machine_code == ErrorCode.PERMISSION_DENIED

    restored = get_or_create_provider_conversation(
        user=customer,
        provider_public_id=str(provider.public_id),
    )
    membership = ConversationMember.objects.get(
        conversation__public_id=conversation["conversation_id"],
        user=customer,
    )
    assert restored["conversation_id"] == conversation_id
    assert membership.hidden_at is None


def test_conversation_pair_key_enforces_database_uniqueness() -> None:
    """数据库唯一约束防止并发场景为同一双方创建重复共享会话。"""

    customer, provider, first_order = create_chat_order()
    _, _, second_order = create_chat_order(customer=customer, provider=provider)
    first = get_or_create_order_conversation(user=customer, order_no=str(first_order.order_no))
    conversation = Conversation.objects.get(public_id=first["conversation_id"])

    with pytest.raises(IntegrityError), transaction.atomic():
        Conversation.objects.create(
            order=second_order,
            pair_key=conversation.pair_key,
        )


def test_chat_image_requires_owned_chat_media() -> None:
    """图片消息只能引用发送者本人用途为 CHAT_IMAGE 的媒体。"""

    customer, provider, order = create_chat_order()
    conversation = get_or_create_order_conversation(user=customer, order_no=str(order.order_no))
    media_id = uuid.uuid4()
    MediaAsset.objects.create(
        public_id=media_id,
        owner=provider,
        purpose=MediaAsset.Purpose.CHAT_IMAGE,
        storage_key=f"chat/{media_id}.jpg",
        content_type="image/jpeg",
        extension="jpg",
        byte_size=10,
        width=100,
        height=100,
        sha256="a" * 64,
        request_fingerprint="b" * 64,
    )

    with pytest.raises(ApiError) as invalid_media:
        create_message(
            user=customer,
            conversation_id=str(conversation["conversation_id"]),
            message_type="IMAGE",
            content="",
            client_message_id="image-001",
            media_id=str(media_id),
        )
    assert invalid_media.value.machine_code == ErrorCode.MESSAGING_MEDIA_INVALID


def test_connection_ticket_is_one_time_and_rejects_reuse() -> None:
    """WebSocket 票据首次消费成功，第二次必须拒绝。"""

    user = create_chat_user("chat-ticket")
    ticket = create_connection_ticket(user=user)
    authenticated_user = consume_connection_ticket(raw_ticket=ticket["ticket"])

    assert authenticated_user.id == user.id
    with pytest.raises(ApiError) as reused:
        consume_connection_ticket(raw_ticket=ticket["ticket"])
    assert reused.value.machine_code == ErrorCode.MESSAGING_TICKET_USED


@pytest.mark.django_db(transaction=True)
def test_websocket_authenticates_ticket_and_rejects_reuse() -> None:
    """WebSocket 能通过一次性票据认证并拒绝重复票据。"""

    user = create_chat_user("chat-websocket")
    ticket = create_connection_ticket(user=user)

    async def scenario() -> None:
        first = WebsocketCommunicator(
            application,
            f"/ws/messages/?ticket={ticket['ticket']}",
            headers=[(b"origin", b"http://testserver")],
        )
        connected, _ = await first.connect()
        assert connected is True
        ready = await first.receive_json_from()
        assert ready["event"] == "connection.ready"
        await first.disconnect()

        second = WebsocketCommunicator(
            application,
            f"/ws/messages/?ticket={ticket['ticket']}",
            headers=[(b"origin", b"http://testserver")],
        )
        connected, _ = await second.connect()
        assert connected is True
        error = await second.receive_json_from()
        assert error["code"] == ErrorCode.MESSAGING_TICKET_USED
        await second.disconnect()

    async_to_sync(scenario)()


def test_websocket_rejects_disallowed_origin() -> None:
    """浏览器来源不在允许列表时必须在握手阶段拒绝连接。"""

    user = create_chat_user("chat-origin")
    ticket = create_connection_ticket(user=user)

    async def scenario() -> None:
        communicator = WebsocketCommunicator(
            application,
            f"/ws/messages/?ticket={ticket['ticket']}",
            headers=[(b"origin", b"http://malicious.example")],
        )
        connected, _ = await communicator.connect()
        assert connected is False
        await communicator.disconnect()

    async_to_sync(scenario)()
