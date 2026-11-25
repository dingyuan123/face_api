"""客服工单提交、消息沟通、客服处理和常见问题业务服务。"""

from __future__ import annotations

from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from backend.accounts.models import User
from backend.adminops.auth import write_admin_operation
from backend.common.display import enum_label
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.support.models import SupportFAQ, SupportMessage, SupportTicket


def _invalid(field: str, message: str) -> ApiError:
    return ApiError(
        ErrorCode.VALIDATION_ERROR,
        message,
        status_code=400,
        details={field: message},
    )


def ticket_payload(ticket: SupportTicket) -> dict[str, Any]:
    """返回客服工单安全摘要。"""
    return {
        "ticket_no": str(ticket.ticket_no),
        "user_public_id": str(ticket.user.public_id),
        "category": ticket.category,
        "category_text": enum_label(SupportTicket.Category, ticket.category),
        "subject": ticket.subject,
        "description": ticket.description,
        "status": ticket.status,
        "status_text": enum_label(SupportTicket.Status, ticket.status),
        "priority": ticket.priority,
        "priority_text": enum_label(SupportTicket.Priority, ticket.priority),
        "related_order_no": ticket.related_order_no,
        "assigned_agent_id": ticket.assigned_agent_id,
        "resolution": ticket.resolution,
        "version": ticket.version,
        "created_at": ticket.created_at,
        "updated_at": ticket.updated_at,
        "resolved_at": ticket.resolved_at,
    }


def message_payload(message: SupportMessage) -> dict[str, Any]:
    """返回客服消息摘要。"""
    return {
        "message_id": message.id,
        "ticket_no": str(message.ticket.ticket_no),
        "sender_type": message.sender_type,
        "sender_type_text": enum_label(
            SupportMessage.SenderType,
            message.sender_type,
        ),
        "sender_id": message.sender_id,
        "content": message.content,
        "sequence": message.sequence,
        "client_message_id": message.client_message_id,
        "created_at": message.created_at,
    }


def create_support_ticket(*, user: User, payload: dict[str, Any]) -> SupportTicket:
    """创建用户客服工单。"""
    subject = str(payload.get("subject", "")).strip()
    description = str(payload.get("description", "")).strip()
    if not 2 <= len(subject) <= 120:
        raise _invalid("subject", "工单主题长度必须为 2 到 120 个字符")
    if not 2 <= len(description) <= 5000:
        raise _invalid("description", "问题描述长度必须为 2 到 5000 个字符")
    return SupportTicket.objects.create(
        user=user,
        category=payload.get("category", SupportTicket.Category.OTHER),
        subject=subject,
        description=description,
        priority=payload.get("priority", SupportTicket.Priority.NORMAL),
        related_order_no=str(payload.get("related_order_no", "") or "")[:64],
    )


def list_support_tickets(
    *,
    user: User | None = None,
    status: str = "",
    category: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """分页查询用户或管理员可见工单。"""
    queryset = SupportTicket.objects.select_related("user")
    if user is not None:
        queryset = queryset.filter(user=user)
    if status:
        queryset = queryset.filter(status=status)
    if category:
        queryset = queryset.filter(category=category)
    total = queryset.count()
    items = queryset.order_by("-updated_at", "-id")[(page - 1) * page_size : page * page_size]
    return {
        "items": [ticket_payload(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_support_ticket(*, user: User | None, ticket_no: str) -> SupportTicket:
    """读取工单并校验普通用户只能访问自己的工单。"""
    queryset = SupportTicket.objects.select_related("user").filter(ticket_no=ticket_no)
    if user is not None:
        queryset = queryset.filter(user=user)
    ticket = queryset.first()
    if ticket is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.NOT_FOUND],
            status_code=404,
        )
    return ticket


def list_support_messages(
    *,
    user: User | None,
    ticket_no: str,
    after_sequence: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """读取工单消息，支持断线增量补偿。"""
    ticket = get_support_ticket(user=user, ticket_no=ticket_no)
    queryset = ticket.messages.filter(sequence__gt=after_sequence).order_by("sequence", "id")
    items = [message_payload(item) for item in queryset[:limit]]
    return {
        "ticket_no": str(ticket.ticket_no),
        "items": items,
        "next_sequence": items[-1]["sequence"] if items else after_sequence,
    }


def create_support_message(
    *,
    user: User,
    ticket_no: str,
    content: str,
    client_message_id: str = "",
) -> SupportMessage:
    """用户向客服工单追加消息。"""
    return _append_message(
        ticket=get_support_ticket(user=user, ticket_no=ticket_no),
        sender_type=SupportMessage.SenderType.USER,
        sender=user,
        content=content,
        client_message_id=client_message_id,
    )


def _append_message(
    *,
    ticket: SupportTicket,
    sender_type: str,
    sender: User | None,
    content: str,
    client_message_id: str = "",
) -> SupportMessage:
    text = str(content).strip()
    if not 1 <= len(text) <= 5000:
        raise _invalid("content", "消息长度必须为 1 到 5000 个字符")
    normalized_key = str(client_message_id or "").strip()
    if len(normalized_key) > 128:
        raise _invalid("client_message_id", "消息幂等标识过长")
    with transaction.atomic():
        locked = SupportTicket.objects.select_for_update().get(pk=ticket.pk)
        if normalized_key:
            existing = SupportMessage.objects.filter(
                ticket=locked,
                sender_id=sender.id if sender else None,
                client_message_id=normalized_key,
            ).first()
            if existing:
                return existing
        sequence = (locked.messages.aggregate(value=Max("sequence"))["value"] or 0) + 1
        try:
            message = SupportMessage.objects.create(
                ticket=locked,
                sender_type=sender_type,
                sender_id=sender.id if sender else None,
                content=text,
                sequence=sequence,
                client_message_id=normalized_key,
            )
        except IntegrityError as exc:
            existing = SupportMessage.objects.filter(
                ticket=locked,
                sender_id=sender.id if sender else None,
                client_message_id=normalized_key,
            ).first()
            if existing:
                return existing
            raise ApiError(
                ErrorCode.VALIDATION_ERROR,
                "客服消息并发写入冲突",
                status_code=409,
            ) from exc
        locked.updated_at = timezone.now()
        locked.save(update_fields=["updated_at"])
        return message


def assign_support_ticket(
    *,
    operator: User,
    ticket_no: str,
    expected_version: int,
    agent_user_id: int,
    reason: str = "",
) -> dict[str, Any]:
    """分配客服处理人。"""
    with transaction.atomic():
        ticket = SupportTicket.objects.select_for_update().filter(ticket_no=ticket_no).first()
        if ticket is None:
            raise ApiError(
                ErrorCode.NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.NOT_FOUND],
                status_code=404,
            )
        if ticket.version != expected_version:
            raise _invalid("expected_version", "工单已被更新")
        before = ticket_payload(ticket)
        ticket.assigned_agent_id = agent_user_id
        ticket.status = SupportTicket.Status.OPEN
        ticket.version += 1
        ticket.save()
        write_admin_operation(
            operator=operator,
            action="SUPPORT_TICKET_ASSIGN",
            target_type="SUPPORT_TICKET",
            target_id=ticket_no,
            before_state=before,
            after_state=ticket_payload(ticket),
            reason=reason,
        )
        return ticket_payload(ticket)


def agent_reply_support_ticket(
    *,
    operator: User,
    ticket_no: str,
    content: str,
    client_message_id: str = "",
) -> dict[str, Any]:
    """客服向工单发送回复。"""
    ticket = get_support_ticket(user=None, ticket_no=ticket_no)
    message = _append_message(
        ticket=ticket,
        sender_type=SupportMessage.SenderType.AGENT,
        sender=operator,
        content=content,
        client_message_id=client_message_id,
    )
    if ticket.status == SupportTicket.Status.OPEN:
        ticket.status = SupportTicket.Status.PENDING
        ticket.save(update_fields=["status", "updated_at"])
    return {"message": message_payload(message), "ticket": ticket_payload(ticket)}


def resolve_support_ticket(
    *,
    operator: User,
    ticket_no: str,
    expected_version: int,
    resolution: str,
    action: str = "resolve",
) -> dict[str, Any]:
    """解决或关闭客服工单。"""
    if action not in {"resolve", "close"}:
        raise _invalid("action", "客服处理动作不存在")
    if len(resolution.strip()) < 2:
        raise _invalid("resolution", "处理结论至少需要 2 个字符")
    with transaction.atomic():
        ticket = SupportTicket.objects.select_for_update().filter(ticket_no=ticket_no).first()
        if ticket is None:
            raise ApiError(
                ErrorCode.NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.NOT_FOUND],
                status_code=404,
            )
        if ticket.version != expected_version:
            raise _invalid("expected_version", "工单已被更新")
        before = ticket_payload(ticket)
        ticket.status = (
            SupportTicket.Status.RESOLVED if action == "resolve" else SupportTicket.Status.CLOSED
        )
        ticket.resolution = resolution
        ticket.resolved_at = timezone.now()
        ticket.version += 1
        ticket.save()
        write_admin_operation(
            operator=operator,
            action=f"SUPPORT_TICKET_{action.upper()}",
            target_type="SUPPORT_TICKET",
            target_id=ticket_no,
            before_state=before,
            after_state=ticket_payload(ticket),
            reason=resolution,
        )
        return ticket_payload(ticket)


def list_support_faqs() -> list[dict[str, Any]]:
    """返回公开常见问题。"""
    return [
        {
            "id": item.id,
            "question": item.question,
            "answer": item.answer,
            "category": item.category,
            "sort_order": item.sort_order,
            "version": item.version,
        }
        for item in SupportFAQ.objects.filter(is_active=True).order_by("sort_order", "id")
    ]


def create_support_faq(*, operator: User, payload: dict[str, Any]) -> dict[str, Any]:
    """管理员创建常见问题。"""
    item = SupportFAQ.objects.create(
        question=payload["question"],
        answer=payload["answer"],
        category=payload.get("category", "GENERAL"),
        sort_order=payload.get("sort_order", 0),
        is_active=payload.get("is_active", True),
    )
    write_admin_operation(
        operator=operator,
        action="SUPPORT_FAQ_CREATE",
        target_type="SUPPORT_FAQ",
        target_id=str(item.id),
        after_state={
            "id": item.id,
            "question": item.question,
            "version": item.version,
        },
    )
    return {
        "id": item.id,
        "question": item.question,
        "answer": item.answer,
        "category": item.category,
        "sort_order": item.sort_order,
        "is_active": item.is_active,
        "version": item.version,
    }


def update_support_faq(*, operator: User, faq_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    """管理员修改或停用常见问题。"""
    with transaction.atomic():
        item = SupportFAQ.objects.select_for_update().filter(id=faq_id).first()
        if item is None:
            raise ApiError(
                ErrorCode.NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.NOT_FOUND],
                status_code=404,
            )
        if item.version != payload["expected_version"]:
            raise _invalid("expected_version", "常见问题已被更新")
        before = {"id": item.id, "question": item.question, "version": item.version}
        for field in ("question", "answer", "category", "sort_order", "is_active"):
            if field in payload:
                setattr(item, field, payload[field])
        item.version += 1
        item.save()
        write_admin_operation(
            operator=operator,
            action="SUPPORT_FAQ_UPDATE",
            target_type="SUPPORT_FAQ",
            target_id=str(faq_id),
            before_state=before,
            after_state={"id": item.id, "question": item.question, "version": item.version},
        )
        return {
            "id": item.id,
            "question": item.question,
            "answer": item.answer,
            "category": item.category,
            "sort_order": item.sort_order,
            "is_active": item.is_active,
            "version": item.version,
        }
