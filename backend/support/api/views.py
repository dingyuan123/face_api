"""用户客服工单和管理员客服工作台接口。"""

from __future__ import annotations

from typing import ClassVar

from drf_spectacular.utils import extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.accounts.authentication import BearerTokenAuthentication
from backend.adminops.auth import AdminBearerTokenAuthentication, require_admin_permission
from backend.support.api.serializers import (
    SupportAssignRequestSerializer,
    SupportFAQRequestSerializer,
    SupportFAQResponseSerializer,
    SupportMessageListResponseSerializer,
    SupportMessageRequestSerializer,
    SupportMessageResponseSerializer,
    SupportTicketActionRequestSerializer,
    SupportTicketCreateRequestSerializer,
    SupportTicketListResponseSerializer,
    SupportTicketResponseSerializer,
)
from backend.support.services import (
    agent_reply_support_ticket,
    assign_support_ticket,
    create_support_faq,
    create_support_message,
    create_support_ticket,
    get_support_ticket,
    list_support_faqs,
    list_support_messages,
    list_support_tickets,
    message_payload,
    resolve_support_ticket,
    ticket_payload,
    update_support_faq,
)


def _integer_query(request: Request, name: str, default: int, minimum: int, maximum: int) -> int:
    raw = request.query_params.get(name)
    if raw in {None, ""}:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


class SupportTicketView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        operation_id="support_ticket_create",
        summary="创建客服工单",
        request=SupportTicketCreateRequestSerializer,
        responses={201: SupportTicketResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = SupportTicketCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            ticket_payload(
                create_support_ticket(user=request.user, payload=dict(serializer.validated_data))
            ),
            status=201,
        )

    @extend_schema(
        operation_id="support_ticket_list",
        summary="查看我的客服工单",
        responses={200: SupportTicketListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(
            list_support_tickets(
                user=request.user,
                status=request.query_params.get("status", ""),
                category=request.query_params.get("category", ""),
                page=_integer_query(request, "page", 1, 1, 10_000),
                page_size=_integer_query(request, "page_size", 20, 1, 100),
            )
        )


class SupportTicketDetailView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        operation_id="support_ticket_detail",
        summary="查看客服工单详情",
        responses={200: SupportTicketResponseSerializer},
    )
    def get(self, request: Request, ticket_no: str) -> Response:
        return Response(ticket_payload(get_support_ticket(user=request.user, ticket_no=ticket_no)))


class SupportMessageView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        operation_id="support_message_list",
        summary="读取客服消息",
        responses={200: SupportMessageListResponseSerializer},
    )
    def get(self, request: Request, ticket_no: str) -> Response:
        return Response(
            list_support_messages(
                user=request.user,
                ticket_no=ticket_no,
                after_sequence=_integer_query(request, "after_sequence", 0, 0, 2_000_000_000),
                limit=_integer_query(request, "limit", 50, 1, 100),
            )
        )

    @extend_schema(
        operation_id="support_message_create",
        summary="发送客服消息",
        request=SupportMessageRequestSerializer,
        responses={201: SupportMessageResponseSerializer},
    )
    def post(self, request: Request, ticket_no: str) -> Response:
        serializer = SupportMessageRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            message_payload(
                create_support_message(
                    user=request.user,
                    ticket_no=ticket_no,
                    content=serializer.validated_data["content"],
                    client_message_id=serializer.validated_data.get("client_message_id", ""),
                )
            ),
            status=201,
        )


class SupportFAQView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(summary="查看常见问题", responses={200: SupportFAQResponseSerializer(many=True)})
    def get(self, request: Request) -> Response:
        return Response(list_support_faqs())


class AdminSupportTicketListView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(summary="查看客服工单", responses={200: SupportTicketListResponseSerializer})
    def get(self, request: Request) -> Response:
        require_admin_permission(request.user, "admin.support.read")
        return Response(
            list_support_tickets(
                status=request.query_params.get("status", ""),
                category=request.query_params.get("category", ""),
                page=_integer_query(request, "page", 1, 1, 10_000),
                page_size=_integer_query(request, "page_size", 20, 1, 100),
            )
        )


class AdminSupportTicketMessageView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        operation_id="admin_support_message_list",
        summary="客服查看工单消息",
        responses={200: SupportMessageListResponseSerializer},
    )
    def get(self, request: Request, ticket_no: str) -> Response:
        require_admin_permission(request.user, "admin.support.read")
        return Response(
            list_support_messages(
                user=None,
                ticket_no=ticket_no,
                after_sequence=_integer_query(request, "after_sequence", 0, 0, 2_000_000_000),
                limit=_integer_query(request, "limit", 50, 1, 100),
            )
        )

    @extend_schema(
        operation_id="admin_support_message_reply",
        summary="客服回复工单",
        request=SupportMessageRequestSerializer,
        responses={200: dict},
    )
    def post(self, request: Request, ticket_no: str) -> Response:
        require_admin_permission(request.user, "admin.support.reply")
        serializer = SupportMessageRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            agent_reply_support_ticket(
                operator=request.user,
                ticket_no=ticket_no,
                content=serializer.validated_data["content"],
                client_message_id=serializer.validated_data.get("client_message_id", ""),
            )
        )


class AdminSupportTicketAssignView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="分配客服工单",
        request=SupportAssignRequestSerializer,
        responses={200: SupportTicketResponseSerializer},
    )
    def post(self, request: Request, ticket_no: str) -> Response:
        require_admin_permission(request.user, "admin.support.assign")
        serializer = SupportAssignRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            assign_support_ticket(
                operator=request.user,
                ticket_no=ticket_no,
                expected_version=serializer.validated_data["expected_version"],
                agent_user_id=serializer.validated_data["agent_user_id"],
                reason=serializer.validated_data.get("reason", ""),
            )
        )


class AdminSupportTicketActionView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="解决或关闭客服工单",
        request=SupportTicketActionRequestSerializer,
        responses={200: SupportTicketResponseSerializer},
    )
    def post(self, request: Request, ticket_no: str, action: str) -> Response:
        require_admin_permission(request.user, "admin.support.close")
        serializer = SupportTicketActionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            resolve_support_ticket(
                operator=request.user,
                ticket_no=ticket_no,
                expected_version=serializer.validated_data["expected_version"],
                resolution=serializer.validated_data.get("resolution", ""),
                action=action,
            )
        )


class AdminSupportFAQView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(summary="查看常见问题", responses={200: SupportFAQResponseSerializer(many=True)})
    def get(self, request: Request) -> Response:
        require_admin_permission(request.user, "admin.support.read")
        return Response(list_support_faqs())

    @extend_schema(
        summary="创建常见问题",
        request=SupportFAQRequestSerializer,
        responses={201: SupportFAQResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        require_admin_permission(request.user, "admin.support.write")
        serializer = SupportFAQRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            create_support_faq(operator=request.user, payload=dict(serializer.validated_data)),
            status=201,
        )


class AdminSupportFAQDetailView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="修改常见问题",
        request=SupportFAQRequestSerializer,
        responses={200: SupportFAQResponseSerializer},
    )
    def patch(self, request: Request, faq_id: int) -> Response:
        require_admin_permission(request.user, "admin.support.write")
        serializer = SupportFAQRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            update_support_faq(
                operator=request.user, faq_id=faq_id, payload=dict(serializer.validated_data)
            )
        )

    @extend_schema(
        summary="停用常见问题",
        request=SupportFAQRequestSerializer,
        responses={200: SupportFAQResponseSerializer},
    )
    def delete(self, request: Request, faq_id: int) -> Response:
        require_admin_permission(request.user, "admin.support.write")
        return Response(
            update_support_faq(
                operator=request.user,
                faq_id=faq_id,
                payload={
                    "is_active": False,
                    "expected_version": int(request.data.get("expected_version", 0)),
                },
            )
        )
