"""订单实时聊天 HTTP 接口层，仅负责认证、参数解析和服务调用。"""

from __future__ import annotations

from typing import ClassVar

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.accounts.authentication import BearerTokenAuthentication
from backend.common.renderers import build_success_envelope
from backend.messaging.api.serializers import (
    ConversationHideResponseSerializer,
    ConversationListResponseSerializer,
    ConversationReadRequestSerializer,
    ConversationReadResponseSerializer,
    ConversationResponseSerializer,
    MessageCreateRequestSerializer,
    MessageCreateResponseSerializer,
    MessageListResponseSerializer,
    UnreadSummaryResponseSerializer,
    WebSocketTicketResponseSerializer,
)
from backend.messaging.services import (
    create_connection_ticket,
    create_message,
    get_or_create_order_conversation,
    get_or_create_provider_conversation,
    hide_conversation,
    list_conversations,
    list_messages,
    mark_conversation_read,
    schedule_message_delivery,
    unread_summary,
)


class AuthenticatedMessagingView(APIView):
    """订单聊天接口统一使用不透明 Bearer 访问令牌。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]


class OrderConversationView(AuthenticatedMessagingView):
    """按订单入口获取或恢复当前用户与服务者的共享会话。"""

    @extend_schema(
        summary="获取订单会话",
        description="只有预约用户或服务者可以访问；未支付订单不开放会话。",
        responses={200: ConversationResponseSerializer},
    )
    def get(self, request: Request, order_no: str) -> Response:
        return Response(
            get_or_create_order_conversation(
                user=request.user,
                order_no=order_no,
                request=request._request,
            )
        )


class ProviderConversationView(AuthenticatedMessagingView):
    """按服务者入口获取或恢复双方唯一共享会话。"""

    @extend_schema(
        summary="获取服务者会话",
        description="双方只要存在支付后订单关系即可打开；已隐藏会话会为当前用户恢复显示。",
        responses={200: ConversationResponseSerializer},
    )
    def get(self, request: Request, provider_public_id: str) -> Response:
        return Response(
            get_or_create_provider_conversation(
                user=request.user,
                provider_public_id=provider_public_id,
                request=request._request,
            )
        )


class ConversationListView(AuthenticatedMessagingView):
    """查看当前用户参与的共享会话。"""

    @extend_schema(
        summary="我的聊天会话",
        parameters=[
            OpenApiParameter("cursor", OpenApiTypes.STR, description="上一页返回的会话游标"),
            OpenApiParameter("limit", OpenApiTypes.INT, description="每页数量，默认 20，最大 100"),
        ],
        responses={200: ConversationListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        try:
            limit = int(request.query_params.get("limit", 20))
        except ValueError:
            limit = 0
        return Response(
            list_conversations(
                user=request.user,
                request=request._request,
                cursor=request.query_params.get("cursor"),
                limit=max(1, min(limit or 20, 100)),
            )
        )


class ConversationMessagesView(AuthenticatedMessagingView):
    """读取或发送订单会话消息。"""

    @extend_schema(
        summary="读取聊天历史",
        description="before_sequence 向前翻历史；after_sequence 用于断线后按序补偿。",
        parameters=[
            OpenApiParameter("limit", OpenApiTypes.INT, description="每页数量，默认 20，最大 100"),
            OpenApiParameter(
                "before_sequence", OpenApiTypes.INT, description="读取该序号之前的消息"
            ),
            OpenApiParameter(
                "after_sequence", OpenApiTypes.INT, description="读取该序号之后的消息"
            ),
        ],
        responses={200: MessageListResponseSerializer},
    )
    def get(self, request: Request, conversation_id: str) -> Response:
        def optional_int(name: str) -> int | None:
            raw_value = request.query_params.get(name)
            return int(raw_value) if raw_value not in {None, ""} else None

        return Response(
            list_messages(
                user=request.user,
                conversation_id=conversation_id,
                request=request._request,
                limit=max(1, min(optional_int("limit") or 20, 100)),
                before_sequence=optional_int("before_sequence"),
                after_sequence=optional_int("after_sequence"),
            )
        )

    @extend_schema(
        summary="发送聊天消息",
        description="使用 client_message_id 保证重复请求幂等；消息成功后异步广播。",
        request=MessageCreateRequestSerializer,
        responses={200: MessageCreateResponseSerializer},
    )
    def post(self, request: Request, conversation_id: str) -> Response:
        serializer = MessageCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = create_message(
            user=request.user,
            conversation_id=conversation_id,
            message_type=serializer.validated_data["message_type"],
            content=serializer.validated_data.get("content", ""),
            client_message_id=serializer.validated_data["client_message_id"],
            media_id=str(serializer.validated_data["media_id"])
            if serializer.validated_data.get("media_id")
            else None,
            request=request._request,
        )
        schedule_message_delivery(result)
        return Response(
            build_success_envelope(
                {"message": result["message"], "ack": result["ack"]},
            )
        )


class ConversationReadView(AuthenticatedMessagingView):
    """标记共享会话消息已读。"""

    @extend_schema(
        summary="标记会话已读",
        request=ConversationReadRequestSerializer,
        responses={200: ConversationReadResponseSerializer},
    )
    def post(self, request: Request, conversation_id: str) -> Response:
        serializer = ConversationReadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            mark_conversation_read(
                user=request.user,
                conversation_id=conversation_id,
                sequence=serializer.validated_data.get("sequence"),
            )
        )


class ConversationHideView(AuthenticatedMessagingView):
    """当前用户隐藏共享会话，不删除双方聊天记录。"""

    @extend_schema(
        summary="删除我的会话",
        description="只对当前用户隐藏，不影响对方；新订单或重新打开入口可恢复。",
        request=None,
        responses={200: ConversationHideResponseSerializer},
    )
    def delete(self, request: Request, conversation_id: str) -> Response:
        return Response(hide_conversation(user=request.user, conversation_id=conversation_id))


class UnreadSummaryView(AuthenticatedMessagingView):
    """查看当前用户聊天未读汇总。"""

    @extend_schema(
        summary="聊天未读汇总",
        responses={200: UnreadSummaryResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(unread_summary(user=request.user))


class WebSocketTicketView(AuthenticatedMessagingView):
    """签发 WebSocket 短时效一次性连接票据。"""

    @extend_schema(
        summary="获取实时聊天连接凭证",
        description="凭证只使用一次且很快过期；连接地址为 /ws/messages/?ticket=...。",
        request=None,
        responses={200: WebSocketTicketResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        return Response(create_connection_ticket(user=request.user))
