from __future__ import annotations

from datetime import date
from typing import ClassVar

from drf_spectacular.utils import extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.accounts.authentication import BearerTokenAuthentication
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.scheduling.api.serializers import (
    AvailabilityQuerySerializer,
    PublicAvailabilitySlotSerializer,
    ScheduleBulkUpdateResponseSerializer,
    ScheduleBulkUpdateSerializer,
    ScheduleCalendarQuerySerializer,
    ScheduleCalendarResponseSerializer,
    ScheduleDayQuerySerializer,
    ScheduleDayResponseSerializer,
    ScheduleRuleCreateSerializer,
    ScheduleRuleDeleteResponseSerializer,
    ScheduleRuleDeleteSerializer,
    ScheduleRuleResponseSerializer,
    ScheduleRuleUpdateSerializer,
    ScheduleSlotCreateSerializer,
    ScheduleSlotDeleteResponseSerializer,
    ScheduleSlotDeleteSerializer,
    ScheduleSlotMutationResponseSerializer,
    ScheduleSlotResponseSerializer,
    ScheduleSlotStatusSerializer,
)
from backend.scheduling.services import (
    bulk_update_schedule,
    create_schedule_rule,
    create_schedule_slot,
    delete_schedule_rule,
    delete_schedule_slot,
    get_schedule_calendar,
    get_schedule_day,
    list_available_slots,
    list_schedule_rules,
    list_schedule_slots,
    set_slot_status,
    update_schedule_rule,
)


class ProviderScheduleSlotsView(APIView):
    """服务者预约时段管理。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询服务者预约时段",
        responses={200: ScheduleSlotResponseSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        return Response(list_schedule_slots(user=request.user, request=request))

    @extend_schema(
        summary="创建服务者预约时段",
        request=ScheduleSlotCreateSerializer,
        responses={201: ScheduleSlotMutationResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = ScheduleSlotCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            create_schedule_slot(
                user=request.user,
                service_id=(
                    str(serializer.validated_data["service_id"])
                    if serializer.validated_data.get("service_id")
                    else None
                ),
                start_at=serializer.validated_data["start_at"],
                end_at=serializer.validated_data["end_at"],
            ),
            status=201,
        )


class ProviderScheduleRuleView(APIView):
    """服务者周排期规则管理。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询周排期规则",
        responses={200: ScheduleRuleResponseSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        return Response(list_schedule_rules(request.user))

    @extend_schema(
        summary="创建周排期规则",
        request=ScheduleRuleCreateSerializer,
        responses={201: ScheduleRuleResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = ScheduleRuleCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            create_schedule_rule(
                user=request.user,
                weekday=serializer.validated_data["weekday"],
                start_time=serializer.validated_data["start_time"],
                end_time=serializer.validated_data["end_time"],
                slot_minutes=serializer.validated_data["slot_minutes"],
                timezone_name=serializer.validated_data["timezone"],
            ),
            status=201,
        )


class ProviderScheduleRuleDeleteView(APIView):
    """修改或删除周排期规则。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="删除周排期规则",
        request=ScheduleRuleDeleteSerializer,
        responses={200: ScheduleRuleDeleteResponseSerializer},
    )
    def delete(self, request: Request, rule_id: int) -> Response:
        serializer = ScheduleRuleDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            delete_schedule_rule(
                user=request.user,
                rule_id=rule_id,
                expected_version=serializer.validated_data["expected_version"],
            )
        )

    @extend_schema(
        summary="修改周排期规则",
        request=ScheduleRuleUpdateSerializer,
        responses={200: ScheduleRuleResponseSerializer},
    )
    def patch(self, request: Request, rule_id: int) -> Response:
        serializer = ScheduleRuleUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        expected_version = payload.pop("expected_version")
        return Response(
            update_schedule_rule(
                user=request.user,
                rule_id=rule_id,
                expected_version=expected_version,
                payload=payload,
            )
        )


class ProviderScheduleCalendarView(APIView):
    """查询服务者月历或周历状态。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询排期月历或周历",
        operation_id="listProviderScheduleCalendar",
        parameters=[ScheduleCalendarQuerySerializer],
        responses={200: ScheduleCalendarResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        serializer = ScheduleCalendarQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        return Response(
            get_schedule_calendar(
                user=request.user,
                view=serializer.validated_data["view"],
                anchor_date=serializer.validated_data.get("date"),
                date_from=serializer.validated_data.get("date_from"),
                date_to=serializer.validated_data.get("date_to"),
                timezone_name=serializer.validated_data["timezone"],
            )
        )


class ProviderScheduleDayView(APIView):
    """查询服务者某一天的时段。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询排期某一天",
        operation_id="getProviderScheduleDay",
        parameters=[ScheduleDayQuerySerializer],
        responses={200: ScheduleDayResponseSerializer},
    )
    def get(self, request: Request, day: str) -> Response:
        serializer = ScheduleDayQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        try:
            parsed_day = date.fromisoformat(day)
        except ValueError as exc:
            raise ApiError(
                ErrorCode.SCHEDULE_INVALID,
                ERROR_MESSAGES[ErrorCode.SCHEDULE_INVALID],
                status_code=400,
                details={"day": "日期格式必须是 YYYY-MM-DD"},
            ) from exc
        return Response(
            get_schedule_day(
                user=request.user,
                day=parsed_day,
                timezone_name=serializer.validated_data["timezone"],
            )
        )


class ProviderScheduleBulkUpdateView(APIView):
    """批量设置工作日、周末或全部日期排期。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="批量设置排期",
        request=ScheduleBulkUpdateSerializer,
        responses={200: ScheduleBulkUpdateResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = ScheduleBulkUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            bulk_update_schedule(
                user=request.user,
                date_from=serializer.validated_data["date_from"],
                date_to=serializer.validated_data["date_to"],
                scope=serializer.validated_data["scope"],
                action=serializer.validated_data["action"],
                start_time=serializer.validated_data.get("start_time"),
                end_time=serializer.validated_data.get("end_time"),
                expected_revision=serializer.validated_data["expected_version"],
            )
        )


class ProviderScheduleSlotStatusView(APIView):
    """切换单个预约时段的可约状态。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="设置预约时段状态",
        request=ScheduleSlotStatusSerializer,
        responses={200: ScheduleSlotMutationResponseSerializer},
    )
    def patch(self, request: Request, slot_id: str) -> Response:
        serializer = ScheduleSlotStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            set_slot_status(
                user=request.user,
                slot_id=slot_id,
                status=serializer.validated_data["status"],
                expected_version=serializer.validated_data["expected_version"],
            )
        )


class ProviderScheduleSlotDeleteView(APIView):
    """删除服务者未锁定预约时段。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="删除预约时段",
        request=ScheduleSlotDeleteSerializer,
        responses={200: ScheduleSlotDeleteResponseSerializer},
    )
    def delete(self, request: Request, slot_id: str) -> Response:
        serializer = ScheduleSlotDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            delete_schedule_slot(
                user=request.user,
                slot_id=slot_id,
                expected_version=serializer.validated_data["expected_version"],
            )
        )


class ProviderAvailabilityView(APIView):
    """公开查询服务者可预约时段。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = []
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        summary="查询服务者可预约时间",
        parameters=[AvailabilityQuerySerializer],
        responses={200: PublicAvailabilitySlotSerializer(many=True)},
    )
    def get(self, request: Request, provider_public_id: str) -> Response:
        serializer = AvailabilityQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        return Response(
            list_available_slots(
                provider_public_id=provider_public_id,
                service_id=(
                    str(serializer.validated_data["service_id"])
                    if serializer.validated_data.get("service_id")
                    else None
                ),
                query_date=serializer.validated_data.get("date"),
                date_from=serializer.validated_data.get("date_from"),
                date_to=serializer.validated_data.get("date_to"),
                timezone_name=serializer.validated_data["timezone"],
            )
        )
