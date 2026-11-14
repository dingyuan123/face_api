"""服务者工作台数据看板统计测试。"""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from backend.providers.models import ProviderAnalyticsEvent
from tests.test_booking_flow import (
    auth_headers,
    create_customer,
    create_order,
    create_provider_fixture,
    create_user,
    pay_order,
    transition_order,
)

pytestmark = pytest.mark.django_db


def test_provider_dashboard_returns_today_range_and_funnel_metrics() -> None:
    provider, service, slot = create_provider_fixture("dashboard-provider")
    admin = create_user("dashboard-admin", is_staff=True)
    customer = create_customer("dashboard-customer", admin)
    client = APIClient()

    ProviderAnalyticsEvent.objects.create(
        provider_user=provider,
        event_type=ProviderAnalyticsEvent.EventType.PROFILE_VIEW,
        visitor_hash="visitor-a",
    )
    ProviderAnalyticsEvent.objects.create(
        provider_user=provider,
        event_type=ProviderAnalyticsEvent.EventType.PROFILE_VIEW,
        visitor_hash="visitor-a",
    )
    ProviderAnalyticsEvent.objects.create(
        provider_user=provider,
        event_type=ProviderAnalyticsEvent.EventType.SERVICE_VIEW,
        service_public_id=service.public_id,
        visitor_hash="visitor-a",
    )
    created = create_order(
        user=customer,
        service_id=str(service.public_id),
        slot_id=str(slot.public_id),
        note="数据看板测试",
        expected_service_version=service.version,
        expected_slot_version=slot.version,
        idempotency_key="dashboard-order",
    )
    paid = pay_order(
        user=customer,
        order_no=str(created.order.order_no),
        expected_version=created.order.version,
        idempotency_key="dashboard-payment",
    )
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
    transition_order(
        user=customer,
        order_no=str(created.order.order_no),
        expected_version=completed_by_provider.version,
        action="confirm",
    )

    response = client.get(
        reverse("v1:provider-dashboard"),
        {"range": "7d"},
        **auth_headers(provider),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["range"]["name"] == "7d"
    assert data["today"]["created_order_count"] == 1
    assert data["today"]["pending_items"]["pending_review_count"] == 1
    assert data["overview"]["view_count"] == 2
    assert data["overview"]["visitor_count"] == 1
    assert data["overview"]["created_order_count"] == 1
    assert data["overview"]["completed_order_count"] == 1
    assert data["overview"]["conversion_rate_bps"] == 5000
    assert len(data["income_trend"]) == 7
    assert data["funnel"][0]["count"] == 2
    assert data["funnel"][1]["count"] >= 1
    assert data["funnel"][4]["count"] == 1


def test_provider_dashboard_rejects_non_provider_user() -> None:
    provider, _, _ = create_provider_fixture("dashboard-guest-provider")
    user = create_user("dashboard-guest-user")
    client = APIClient()

    response = client.get(reverse("v1:provider-dashboard"), **auth_headers(user))

    assert response.status_code == 403
    assert provider.provider_enabled is True
