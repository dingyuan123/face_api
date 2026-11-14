"""订单实时聊天 WebSocket 消费者，负责连接认证、订阅和消息转发。"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.http import HttpRequest

from backend.common.context import current_trace_id
from backend.common.errors import ErrorCode
from backend.common.exceptions import ApiError
from backend.messaging.services import (
    consume_connection_ticket,
    create_message,
    mark_conversation_read,
    schedule_message_delivery,
    validate_conversation_subscription,
)

logger = logging.getLogger(__name__)


def _request_from_scope(scope: dict[str, Any]) -> HttpRequest:
    """根据 ASGI 连接信息构造媒体绝对地址所需的轻量 HTTP 请求。"""

    request = HttpRequest()
    request.META["wsgi.url_scheme"] = scope.get("scheme", "http")
    headers = {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }
    host = headers.get("host") or "localhost"
    request.META["HTTP_HOST"] = host
    request.path = scope.get("path", "/ws/messages/")
    return request


class MessagingConsumer(AsyncJsonWebsocketConsumer):
    """一个 WebSocket 连接可订阅多个当前用户参与的订单会话。"""

    async def connect(self) -> None:
        """消费一次性票据后建立连接；未认证连接立即关闭。"""

        query = parse_qs(self.scope.get("query_string", b"").decode("utf-8"))
        raw_ticket = (query.get("ticket") or [""])[0]
        try:
            self.user = await database_sync_to_async(consume_connection_ticket)(
                raw_ticket=raw_ticket
            )
        except ApiError as exc:
            await self.accept()
            await self.send_json(
                {
                    "event": "error",
                    "code": exc.machine_code,
                    "message": exc.message,
                    "trace_id": current_trace_id(),
                }
            )
            await self.close(code=4401)
            return
        except Exception:
            logger.warning("实时聊天连接认证异常 trace_id=%s", current_trace_id())
            await self.accept()
            await self.send_json(
                {
                    "event": "error",
                    "code": ErrorCode.MESSAGING_TICKET_INVALID,
                    "message": "实时聊天连接凭证无效",
                    "trace_id": current_trace_id(),
                }
            )
            await self.close(code=4401)
            return

        self.request = _request_from_scope(self.scope)
        self.subscriptions: set[str] = set()
        await self.accept()
        await self.send_json(
            {
                "event": "connection.ready",
                "user_public_id": str(self.user.public_id),
                "trace_id": current_trace_id(),
            }
        )

    async def disconnect(self, code: int) -> None:
        """连接断开时退出所有会话广播组。"""

        for conversation_id in getattr(self, "subscriptions", set()):
            await self.channel_layer.group_discard(
                f"messaging.conversation.{conversation_id}",
                self.channel_name,
            )

    async def receive_json(self, content: dict[str, Any], **kwargs: Any) -> None:
        """处理订阅、发送、已读三类客户端指令，不记录消息正文。"""

        action = content.get("action")
        try:
            if action == "subscribe":
                await self._subscribe(content)
            elif action == "message.send":
                await self._send_message(content)
            elif action == "read":
                await self._mark_read(content)
            else:
                raise ApiError(
                    ErrorCode.MESSAGING_INVALID,
                    "聊天指令不支持",
                    status_code=400,
                    details={"action": "仅支持 subscribe、message.send 或 read"},
                )
        except ApiError as exc:
            await self.send_json(
                {
                    "event": "error",
                    "action": action,
                    "code": exc.machine_code,
                    "message": exc.message,
                    "details": exc.details,
                    "trace_id": current_trace_id(),
                }
            )
        except Exception:
            logger.warning(
                "实时聊天指令处理异常 action=%s trace_id=%s",
                action,
                current_trace_id(),
            )
            await self.send_json(
                {
                    "event": "error",
                    "action": action,
                    "code": ErrorCode.INTERNAL_ERROR,
                    "message": "服务器内部错误",
                    "trace_id": current_trace_id(),
                }
            )

    async def _subscribe(self, content: dict[str, Any]) -> None:
        """校验成员身份并订阅订单会话实时消息。"""

        conversation_id = str(content.get("conversation_id") or "")
        state = await database_sync_to_async(validate_conversation_subscription)(
            user_id=self.user.id,
            conversation_id=conversation_id,
        )
        group_name = f"messaging.conversation.{state['conversation_id']}"
        await self.channel_layer.group_add(group_name, self.channel_name)
        self.subscriptions.add(state["conversation_id"])
        await self.send_json(
            {
                "event": "subscription.confirmed",
                "conversation_id": state["conversation_id"],
                "latest_sequence": state["latest_sequence"],
                "last_read_sequence": state["last_read_sequence"],
                "trace_id": current_trace_id(),
            }
        )

    async def _send_message(self, content: dict[str, Any]) -> None:
        """持久化消息后返回客户端确认，广播由 Outbox 独立完成。"""

        result = await database_sync_to_async(create_message)(
            user=self.user,
            conversation_id=str(content.get("conversation_id") or ""),
            message_type=str(content.get("message_type") or ""),
            content=str(content.get("content") or ""),
            client_message_id=str(content.get("client_message_id") or ""),
            media_id=str(content["media_id"]) if content.get("media_id") else None,
            request=self.request,
        )
        await database_sync_to_async(schedule_message_delivery)(result)
        await self.send_json(
            {
                "event": "message.ack",
                "ack": result["ack"],
                "message": result["message"],
                "trace_id": current_trace_id(),
            }
        )

    async def _mark_read(self, content: dict[str, Any]) -> None:
        """更新成员单调递增的已读位置。"""

        sequence = content.get("sequence")
        result = await database_sync_to_async(mark_conversation_read)(
            user=self.user,
            conversation_id=str(content.get("conversation_id") or ""),
            sequence=int(sequence) if sequence is not None else None,
        )
        await self.send_json(
            {
                "event": "read.updated",
                **result,
                "trace_id": current_trace_id(),
            }
        )

    async def message_created(self, event: dict[str, Any]) -> None:
        """接收 Channel Layer 消息并只向已订阅连接转发安全载荷。"""

        await self.send_json(
            {
                "event": "message.created",
                "trace_id": event.get("trace_id") or current_trace_id(),
                **event["payload"],
            }
        )
