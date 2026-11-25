"""客服工单、客服消息和常见问题接口测试。"""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from backend.support.models import SupportMessage, SupportTicket
from tests.test_admin_v1 import create_admin, login_headers
from tests.test_booking_flow import auth_headers, create_user

pytestmark = pytest.mark.django_db


def test_user_can_create_support_ticket_and_exchange_messages() -> None:
    client = APIClient()
    user = create_user("support-user")
    headers = auth_headers(user)
    created = client.post(
        reverse("v1:support-tickets"),
        {
            "category": "ORDER",
            "subject": "订单需要帮助",
            "description": "订单支付后需要咨询",
            "priority": "HIGH",
        },
        format="json",
        **headers,
    )
    ticket_no = created.json()["data"]["ticket_no"]
    user_message = client.post(
        reverse("v1:support-ticket-messages", args=[ticket_no]),
        {"content": "请帮我查看订单", "client_message_id": "support-msg-1"},
        format="json",
        **headers,
    )
    messages = client.get(
        reverse("v1:support-ticket-messages", args=[ticket_no]),
        **headers,
    )

    assert created.status_code == 201
    assert user_message.status_code == 201
    assert messages.status_code == 200
    assert messages.json()["data"]["items"][0]["sequence"] == 1
    assert SupportTicket.objects.count() == 1
    assert SupportMessage.objects.count() == 1


def test_admin_can_assign_reply_and_resolve_support_ticket() -> None:
    client = APIClient()
    user = create_user("support-admin-user")
    admin = create_admin("13800130030")
    ticket = SupportTicket.objects.create(
        user=user,
        category=SupportTicket.Category.REFUND,
        subject="退款咨询",
        description="请帮助确认退款进度",
    )
    headers = login_headers(client, "13800130030")

    assigned = client.post(
        reverse("admin-v1-support-ticket-assign", args=[ticket.ticket_no]),
        {"expected_version": ticket.version, "agent_user_id": admin.id},
        format="json",
        **headers,
    )
    reply = client.post(
        reverse("admin-v1-support-ticket-messages", args=[ticket.ticket_no]),
        {"content": "已经收到，正在核实退款", "client_message_id": "agent-msg-1"},
        format="json",
        **headers,
    )
    resolved = client.post(
        reverse("admin-v1-support-ticket-action", args=[ticket.ticket_no, "resolve"]),
        {
            "expected_version": assigned.json()["data"]["version"],
            "resolution": "退款状态已确认",
        },
        format="json",
        **headers,
    )

    assert assigned.status_code == reply.status_code == resolved.status_code == 200
    assert assigned.json()["data"]["assigned_agent_id"] == admin.id
    assert reply.json()["data"]["message"]["sender_type"] == "AGENT"
    assert resolved.json()["data"]["status"] == "RESOLVED"


def test_admin_can_create_and_update_support_faq() -> None:
    client = APIClient()
    create_admin("13800130031")
    headers = login_headers(client, "13800130031")
    created = client.post(
        reverse("admin-v1-support-faqs"),
        {"question": "如何退款？", "answer": "在订单详情提交退款申请。"},
        format="json",
        **headers,
    )
    updated = client.patch(
        reverse("admin-v1-support-faq-detail", args=[created.json()["data"]["id"]]),
        {
            "question": "如何申请退款？",
            "answer": "在订单详情提交退款申请并等待审核。",
            "expected_version": created.json()["data"]["version"],
        },
        format="json",
        **headers,
    )

    assert created.status_code == 201
    assert updated.status_code == 200
    assert updated.json()["data"]["question"] == "如何申请退款？"
