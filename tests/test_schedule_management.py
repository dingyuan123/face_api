from __future__ import annotations

import uuid
from datetime import date, time, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from backend.accounts.models import AuthToken, User
from backend.accounts.services import _token_raw, hash_token
from backend.catalog.models import ProviderService, ServiceCategory
from backend.common.errors import ErrorCode
from backend.common.exceptions import ApiError
from backend.providers.models import ProviderProfile
from backend.scheduling.models import ScheduleSlot
from backend.scheduling.services import (
    bulk_update_schedule,
    create_schedule_rule,
    create_schedule_slot,
    get_schedule_calendar,
    get_schedule_day,
    set_slot_status,
    update_schedule_rule,
)

pytestmark = pytest.mark.django_db


def create_provider(phone_hash: str) -> tuple[User, ProviderService]:
    user = User.objects.create(
        phone_hash=phone_hash,
        phone_masked="138****8000",
        initial_role_selected=True,
        primary_role=User.InitialRole.PROVIDER,
        default_workspace=User.Workspace.PROVIDER_WORKSPACE,
        provider_status=User.ProviderStatus.APPROVED,
        provider_enabled=True,
    )
    ProviderProfile.objects.create(
        user=user,
        nickname=f"schedule-{user.id}",
        signature="耐心细致",
        introduction="擅长台球基础教学和轻松陪练，适合新手入门练习。",
        avatar_media_id=str(uuid.uuid4()),
    )
    service = ProviderService.objects.create(
        provider_user=user,
        category=ServiceCategory.objects.get(code="SPORT"),
        title="台球助教",
        price_amount_minor=6800,
        duration_minutes=60,
        introduction="适合新手学习基础动作。",
        cover_media_id=str(uuid.uuid4()),
        status=ProviderService.Status.ONLINE,
        request_fingerprint="fingerprint",
    )
    return user, service


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


def test_schedule_rules_generate_calendar_and_day_slots() -> None:
    user, _service = create_provider("schedule-calendar-user")
    today = date.today()
    create_schedule_rule(
        user=user,
        weekday=today.weekday(),
        start_time=time(9, 0),
        end_time=time(11, 0),
        slot_minutes=60,
    )

    calendar = get_schedule_calendar(
        user=user,
        view="CUSTOM",
        date_from=today,
        date_to=today,
    )
    day = get_schedule_day(user=user, day=today)

    assert calendar["summary"]["available_count"] == 2
    assert calendar["days"][0]["status"] == "PARTIAL"
    assert sum(item["status"] == ScheduleSlot.Status.OPEN for item in day["slots"]) == 2
    assert day["schedule_version"] == calendar["schedule_version"]


def test_bulk_schedule_restores_open_slots_and_keeps_locked_slots() -> None:
    user, _service = create_provider("schedule-bulk-user")
    today = date.today()
    create_schedule_rule(
        user=user,
        weekday=today.weekday(),
        start_time=time(9, 0),
        end_time=time(11, 0),
        slot_minutes=60,
    )
    from backend.scheduling.services import materialize_schedule_slots

    slots = materialize_schedule_slots(user=user, start_date=today, end_date=today)
    slot = next(item for item in slots if item.status == ScheduleSlot.Status.OPEN)
    slot.status = ScheduleSlot.Status.LOCKED
    slot.locked_order_no = "ORDER-LOCKED"
    slot.save(update_fields=["status", "locked_order_no", "updated_at"])

    result = bulk_update_schedule(
        user=user,
        date_from=today,
        date_to=today,
        scope="ALL",
        action="REST",
        expected_revision=2,
    )
    slot.refresh_from_db()
    unlocked = bulk_update_schedule(
        user=user,
        date_from=today,
        date_to=today,
        scope="ALL",
        action="AVAILABLE",
        expected_revision=result["schedule_version"],
    )
    slot.refresh_from_db()

    assert result["updated_count"] == 1
    assert result["skipped_locked_count"] >= 1
    assert result["failed_count"] == 0
    assert slot.status == ScheduleSlot.Status.LOCKED
    assert unlocked["schedule_version"] == result["schedule_version"] + 1


def test_single_slot_status_requires_expected_version() -> None:
    user, _service = create_provider("schedule-status-user")
    today = date.today()
    create_schedule_rule(
        user=user,
        weekday=today.weekday(),
        start_time=time(9, 0),
        end_time=time(10, 0),
        slot_minutes=60,
    )
    from backend.scheduling.services import materialize_schedule_slots

    materialize_schedule_slots(user=user, start_date=today, end_date=today)
    slot = ScheduleSlot.objects.get(
        provider_user=user,
        status=ScheduleSlot.Status.OPEN,
    )
    result = set_slot_status(
        user=user,
        slot_id=str(slot.public_id),
        status=ScheduleSlot.Status.CLOSED,
        expected_version=slot.version,
    )
    with pytest.raises(ApiError) as error:
        set_slot_status(
            user=user,
            slot_id=str(slot.public_id),
            status=ScheduleSlot.Status.OPEN,
            expected_version=slot.version,
        )

    assert result["status"] == "CLOSED"
    assert result["schedule_version"] >= 1
    assert error.value.machine_code == ErrorCode.SCHEDULE_VERSION_CONFLICT


def test_schedule_rule_can_be_updated_with_expected_version() -> None:
    user, _service = create_provider("schedule-rule-update-user")
    created = create_schedule_rule(
        user=user,
        weekday=0,
        start_time=time(9, 0),
        end_time=time(12, 0),
        slot_minutes=60,
    )

    updated = update_schedule_rule(
        user=user,
        rule_id=created["rule_id"],
        expected_version=created["version"],
        payload={
            "start_time": time(10, 0),
            "end_time": time(13, 0),
            "slot_minutes": 60,
            "is_active": True,
        },
    )

    assert updated["start_time"] == time(10, 0)
    assert updated["end_time"] == time(13, 0)
    assert updated["slot_minutes"] == 60
    assert updated["version"] == created["version"] + 1
    assert updated["schedule_version"] == created["schedule_version"] + 1


def test_calendar_day_and_bulk_api_return_documented_shapes() -> None:
    client = APIClient()
    user, _service = create_provider("schedule-api-user")
    today = date.today()
    create_schedule_rule(
        user=user,
        weekday=today.weekday(),
        start_time=time(9, 0),
        end_time=time(11, 0),
        slot_minutes=60,
    )

    month = client.get(
        reverse("v1:provider-schedule-calendar"),
        {
            "view": "month",
            "date": today.isoformat(),
            "timezone": "Asia/Shanghai",
        },
        **auth_headers(user),
    )
    week = client.get(
        reverse("v1:provider-schedule-calendar"),
        {
            "view": "week",
            "date": today.isoformat(),
            "timezone": "Asia/Shanghai",
        },
        **auth_headers(user),
    )
    no_parameters = client.get(
        reverse("v1:provider-schedule-calendar"),
        **auth_headers(user),
    )
    invalid_view = client.get(
        reverse("v1:provider-schedule-calendar"),
        {"view": "day"},
        **auth_headers(user),
    )
    month_data = month.json()["data"]
    bulk = client.post(
        reverse("v1:provider-schedule-bulk-update"),
        {
            "date_from": today.isoformat(),
            "date_to": today.isoformat(),
            "scope": "ALL",
            "action": "REST",
            "expected_version": month_data["schedule_version"],
        },
        format="json",
        **auth_headers(user),
    )
    day = client.get(
        reverse("v1:provider-schedule-day", args=[today.isoformat()]),
        {"timezone": "Asia/Shanghai"},
        **auth_headers(user),
    )

    assert month.status_code == week.status_code == no_parameters.status_code == 200
    assert invalid_view.status_code == 400
    assert invalid_view.json()["code"] == ErrorCode.VALIDATION_ERROR
    assert "view" in invalid_view.json()["details"]
    assert month_data["view"] == "MONTH"
    assert len(week.json()["data"]["days"]) == 7
    today_payload = next(item for item in month_data["days"] if item["date"] == today.isoformat())
    assert today_payload["slots"][0]["status_text"]
    assert today_payload["available_count"] == 2
    assert month_data["summary"]["available_count"] >= 2
    assert bulk.status_code == 200
    assert bulk.json()["data"]["closed_count"] == 2
    assert bulk.json()["data"]["failed_count"] == 0
    assert bulk.json()["data"]["schedule_version"] > month_data["schedule_version"]
    assert day.status_code == 200
    assert day.json()["data"]["status"] == "REST"
    assert len(day.json()["data"]["slots"]) == 24


def test_public_availability_returns_only_booking_fields() -> None:
    client = APIClient()
    user, service = create_provider("schedule-public-user")
    today = date.today()
    create_schedule_rule(
        user=user,
        weekday=today.weekday(),
        start_time=time(9, 0),
        end_time=time(10, 0),
        slot_minutes=60,
    )
    get_schedule_calendar(
        user=user,
        view="CUSTOM",
        date_from=today,
        date_to=today,
    )

    response = client.get(
        reverse("v1:provider-availability", args=[user.public_id]),
        {
            "date": today.isoformat(),
            "timezone": "Asia/Shanghai",
        },
    )
    default_response = client.get(
        reverse("v1:provider-availability", args=[user.public_id]),
        {
            "service_id": str(service.public_id),
            "timezone": "Asia/Shanghai",
        },
    )
    payload = response.json()["data"][0]

    assert response.status_code == 200
    assert set(payload) == {
        "slot_id",
        "service_id",
        "service",
        "start_at",
        "end_at",
        "status",
        "slot_version",
    }
    assert payload["status"] == "OPEN"
    assert payload["slot_version"] >= 1
    assert response.json()["data"] == default_response.json()["data"]
    assert "locked_order_no" not in str(response.json())
    assert "reject_reason" not in str(response.json())
    assert "sold_count" not in str(response.json())


def test_provider_can_create_unbound_schedule_slot() -> None:
    user, _service = create_provider("schedule-unbound-slot-user")
    start_at = (timezone.now() + timedelta(days=1)).replace(
        minute=0,
        second=0,
        microsecond=0,
    ) + timedelta(hours=1)

    result = create_schedule_slot(
        user=user,
        service_id=None,
        start_at=start_at,
        end_at=start_at + timedelta(hours=1),
    )

    assert result["service_id"] is None
    assert result["service"] is None
    assert result["schedule_version"] >= 1


def test_partial_rest_range_is_not_regenerated_on_next_calendar_query() -> None:
    user, _service = create_provider("schedule-partial-rest-user")
    today = date.today()
    create_schedule_rule(
        user=user,
        weekday=today.weekday(),
        start_time=time(9, 0),
        end_time=time(12, 0),
        slot_minutes=60,
    )
    calendar = get_schedule_calendar(
        user=user,
        view="CUSTOM",
        date_from=today,
        date_to=today,
    )

    result = bulk_update_schedule(
        user=user,
        date_from=today,
        date_to=today,
        scope="ALL",
        action="REST",
        start_time=time(10, 0),
        end_time=time(11, 0),
        expected_revision=calendar["schedule_version"],
    )
    refreshed = get_schedule_calendar(
        user=user,
        view="CUSTOM",
        date_from=today,
        date_to=today,
    )

    assert result["closed_count"] == 1
    assert refreshed["days"][0]["status"] == "PARTIAL"
    assert refreshed["days"][0]["available_count"] == 2
    assert refreshed["days"][0]["closed_count"] == 22


def test_default_day_has_24_closed_hour_units_without_provider_rule() -> None:
    user, _service = create_provider("schedule-default-grid-user")
    today = date.today()

    calendar = get_schedule_calendar(
        user=user,
        view="CUSTOM",
        date_from=today,
        date_to=today,
    )
    day = get_schedule_day(user=user, day=today)

    assert len(calendar["days"][0]["slots"]) == 24
    assert calendar["days"][0]["status"] == "CLOSED"
    assert calendar["days"][0]["closed_count"] == 24
    assert {item["status"] for item in day["slots"]} == {ScheduleSlot.Status.CLOSED}
