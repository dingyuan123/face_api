"""服务者排期接口请求和响应序列化模型。"""

from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from rest_framework import serializers

from backend.catalog.api.serializers import MoneySerializer


class ScheduleSlotServiceSerializer(serializers.Serializer):
    """预约时段关联服务的最小安全摘要。"""

    id = serializers.UUIDField(help_text="服务 UUID；服务者通用时段为空")
    title = serializers.CharField(help_text="服务名称")
    duration_minutes = serializers.IntegerField(help_text="服务时长，单位为分钟")
    pricing_unit = serializers.CharField(help_text="计价单位，当前固定为 HOUR 按小时计价")
    price = MoneySerializer(help_text="服务每小时价格，金额使用最小货币单位")
    price_display = serializers.CharField(help_text="只读金额展示字符串，不作为提交值")


class ScheduleSlotCreateSerializer(serializers.Serializer):
    """服务者预约时段创建请求。"""

    service_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="历史兼容参数；当前排期不绑定服务，请传空值",
    )
    start_at = serializers.DateTimeField(help_text="时段开始时间，RFC 3339 UTC 时间")
    end_at = serializers.DateTimeField(help_text="时段结束时间，RFC 3339 UTC 时间")


class ScheduleSlotResponseSerializer(serializers.Serializer):
    """服务者预约时段响应。"""

    slot_id = serializers.UUIDField(help_text="预约时段 UUID")
    service_id = serializers.UUIDField(
        allow_null=True,
        help_text="绑定服务 UUID；服务者通用时段为空",
    )
    service = ScheduleSlotServiceSerializer(
        allow_null=True,
        help_text="绑定服务摘要；服务者通用时段为空",
    )
    start_at = serializers.DateTimeField(help_text="时段开始时间")
    end_at = serializers.DateTimeField(help_text="时段结束时间")
    status = serializers.ChoiceField(
        choices=["OPEN", "CLOSED", "LOCKED", "BOOKED"],
        help_text="当前状态：OPEN 可约、CLOSED 不可约、LOCKED 待支付锁定、BOOKED 已支付预约",
    )
    status_text = serializers.CharField(help_text="当前状态中文文案")
    last_booking_status = serializers.ChoiceField(
        choices=["NONE", "LOCKED", "BOOKED", "CANCELLED", "COMPLETED"],
        help_text="最近一次预约结果；取消后时段恢复可约但保留 CANCELLED 历史",
    )
    locked_order_no = serializers.CharField(
        allow_null=True,
        help_text="当前锁定订单号；仅服务者管理接口返回",
    )
    version = serializers.IntegerField(help_text="时段乐观锁版本号")


class ScheduleSlotMutationResponseSerializer(ScheduleSlotResponseSerializer):
    """时段创建和状态切换响应。"""

    schedule_version = serializers.IntegerField(help_text="修改后服务者排期版本号")


class ScheduleSlotDeleteResponseSerializer(serializers.Serializer):
    """预约时段删除响应。"""

    slot_id = serializers.UUIDField(help_text="被删除预约时段 UUID")
    deleted = serializers.BooleanField(help_text="时段是否已删除")
    schedule_version = serializers.IntegerField(help_text="修改后服务者排期版本号")


class ScheduleSlotDeleteSerializer(serializers.Serializer):
    """预约时段删除请求。"""

    expected_version = serializers.IntegerField(
        min_value=1,
        help_text="查询时段响应中的 version",
    )


class ScheduleSlotStatusSerializer(serializers.Serializer):
    """单个时段状态切换请求。"""

    status = serializers.ChoiceField(
        choices=["OPEN", "CLOSED"],
        help_text="目标状态；服务者只能在 OPEN 和 CLOSED 之间切换",
    )
    expected_version = serializers.IntegerField(
        min_value=1,
        help_text="查询时段响应中的 version",
    )


class ScheduleCalendarQuerySerializer(serializers.Serializer):
    """月历、周历或自定义日期范围查询参数。"""

    view = serializers.CharField(
        default="MONTH",
        help_text="视图：MONTH 月历、WEEK 周历、CUSTOM 自定义范围",
    )
    date = serializers.DateField(
        required=False,
        help_text="月份或周的锚点日期，格式 YYYY-MM-DD；不传默认服务者本地今天",
    )
    date_from = serializers.DateField(
        required=False,
        help_text="自定义范围开始日期；与 date_to 同时提供",
    )
    date_to = serializers.DateField(
        required=False,
        help_text="自定义范围结束日期；与 date_from 同时提供",
    )
    timezone = serializers.CharField(
        default=settings.SCHEDULE_DEFAULT_TIMEZONE,
        help_text="排期时区，IANA 时区名称，默认 Asia/Shanghai",
    )

    def validate_view(self, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"MONTH", "WEEK", "CUSTOM"}:
            raise serializers.ValidationError("view 必须是 MONTH、WEEK 或 CUSTOM")
        return normalized

    def validate_timezone(self, value: str) -> str:
        timezone_name = value.strip()
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise serializers.ValidationError("timezone 不是有效的 IANA 时区") from exc
        return timezone_name

    def validate(self, attrs: dict) -> dict:
        date_from = attrs.get("date_from")
        date_to = attrs.get("date_to")
        if (date_from is None) != (date_to is None):
            raise serializers.ValidationError("date_from 和 date_to 必须同时提供")
        if date_from and date_to:
            if date_to < date_from:
                raise serializers.ValidationError("date_to 不能早于 date_from")
            if date_to - date_from > timedelta(days=366):
                raise serializers.ValidationError("自定义日期范围不能超过 366 天")
            attrs["view"] = "CUSTOM"
        elif attrs["view"] == "CUSTOM":
            raise serializers.ValidationError("CUSTOM 视图必须提供 date_from 和 date_to")
        return attrs


class ScheduleDayQuerySerializer(serializers.Serializer):
    """单日排期查询参数。"""

    timezone = serializers.CharField(
        default=settings.SCHEDULE_DEFAULT_TIMEZONE,
        help_text="排期时区，IANA 时区名称，默认 Asia/Shanghai",
    )

    def validate_timezone(self, value: str) -> str:
        timezone_name = value.strip()
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise serializers.ValidationError("timezone 不是有效的 IANA 时区") from exc
        return timezone_name


class ScheduleDaySerializer(serializers.Serializer):
    """某一天的排期状态和时段。"""

    date = serializers.DateField(help_text="服务者本地日期")
    weekday = serializers.IntegerField(help_text="星期几，0 表示周一，6 表示周日")
    is_today = serializers.BooleanField(help_text="是否为查询时区下的今天")
    is_rest = serializers.BooleanField(help_text="是否为休息日")
    status = serializers.ChoiceField(
        choices=["AVAILABLE", "PARTIAL", "BOOKED", "REST", "CLOSED"],
        help_text="日期状态：可约、部分可约、已约、休息或不可约",
    )
    available_count = serializers.IntegerField(help_text="可预约时段数量")
    booked_count = serializers.IntegerField(help_text="已锁定或已预约时段数量")
    closed_count = serializers.IntegerField(help_text="不可约时段数量")
    slots = ScheduleSlotResponseSerializer(many=True, help_text="当天全部预约时段")


class ScheduleCalendarSummarySerializer(serializers.Serializer):
    """排期范围汇总。"""

    available_count = serializers.IntegerField(help_text="可预约时段总数")
    booked_count = serializers.IntegerField(help_text="已锁定或已预约时段总数")
    rest_day_count = serializers.IntegerField(help_text="休息日数量")


class ScheduleCalendarResponseSerializer(serializers.Serializer):
    """月历、周历或自定义范围排期响应。"""

    schedule_version = serializers.IntegerField(
        help_text="排期版本号；批量更新时作为 expected_version"
    )
    view = serializers.ChoiceField(
        choices=["MONTH", "WEEK", "CUSTOM"],
        help_text="实际查询视图",
    )
    timezone = serializers.CharField(help_text="排期时区")
    date_from = serializers.DateField(help_text="响应范围开始日期")
    date_to = serializers.DateField(help_text="响应范围结束日期")
    days = ScheduleDaySerializer(many=True, help_text="日期排期列表")
    summary = ScheduleCalendarSummarySerializer(help_text="排期范围汇总")


class ScheduleDayResponseSerializer(ScheduleDaySerializer):
    """单日排期响应。"""

    schedule_version = serializers.IntegerField(
        help_text="排期版本号；批量更新时作为 expected_version"
    )
    timezone = serializers.CharField(help_text="排期时区")


class ScheduleBulkUpdateSerializer(serializers.Serializer):
    """批量设置排期请求。"""

    date_from = serializers.DateField(help_text="开始日期")
    date_to = serializers.DateField(help_text="结束日期")
    scope = serializers.ChoiceField(
        choices=["WEEKDAY", "WEEKEND", "ALL"],
        help_text="批量范围：工作日、周末或全部日期",
    )
    action = serializers.ChoiceField(
        choices=["AVAILABLE", "REST"],
        help_text="批量动作：恢复可约或设置休息",
    )
    start_time = serializers.TimeField(
        required=False,
        help_text="可选时间范围开始；与 end_time 同时提供",
    )
    end_time = serializers.TimeField(
        required=False,
        help_text="可选时间范围结束；与 start_time 同时提供",
    )
    expected_version = serializers.IntegerField(
        min_value=1,
        help_text="日历或单日响应中的 schedule_version",
    )


class ScheduleBulkErrorSerializer(serializers.Serializer):
    """批量排期操作的结构化跳过或失败说明。"""

    code = serializers.CharField(help_text="结果代码")
    message = serializers.CharField(help_text="结果说明")
    date = serializers.DateField(allow_null=True, help_text="相关日期")
    slot_id = serializers.UUIDField(allow_null=True, help_text="相关预约时段 UUID")


class ScheduleBulkUpdateResponseSerializer(serializers.Serializer):
    """批量设置排期结果。"""

    schedule_version = serializers.IntegerField(help_text="修改后排期版本号")
    updated_count = serializers.IntegerField(help_text="实际发生变化的时段数量")
    opened_count = serializers.IntegerField(help_text="恢复可约的时段数量")
    closed_count = serializers.IntegerField(help_text="设置为不可约的时段数量")
    deleted_count = serializers.IntegerField(help_text="逻辑删除的时段数量")
    skipped_locked_count = serializers.IntegerField(help_text="因待支付锁定而跳过的时段数量")
    skipped_booked_count = serializers.IntegerField(help_text="因已支付预约而跳过的时段数量")
    failed_count = serializers.IntegerField(help_text="执行失败数量")
    warnings = ScheduleBulkErrorSerializer(many=True, help_text="保护性跳过说明")
    errors = ScheduleBulkErrorSerializer(many=True, help_text="执行失败说明")


class ScheduleRuleCreateSerializer(serializers.Serializer):
    """周排期规则创建请求。"""

    weekday = serializers.IntegerField(help_text="星期几，0 表示周一，6 表示周日")
    start_time = serializers.TimeField(help_text="每日开始时间")
    end_time = serializers.TimeField(help_text="每日结束时间")
    slot_minutes = serializers.IntegerField(
        default=60,
        help_text="小时单元长度，当前固定为 60 分钟",
    )
    timezone = serializers.CharField(
        default=settings.SCHEDULE_DEFAULT_TIMEZONE,
        help_text="规则使用的 IANA 时区",
    )


class ScheduleRuleUpdateSerializer(serializers.Serializer):
    """周排期规则修改请求；除版本外均可局部更新。"""

    weekday = serializers.IntegerField(required=False, help_text="星期几，0 表示周一，6 表示周日")
    start_time = serializers.TimeField(required=False, help_text="每日开始时间")
    end_time = serializers.TimeField(required=False, help_text="每日结束时间")
    slot_minutes = serializers.IntegerField(
        required=False,
        help_text="小时单元长度，当前固定为 60 分钟",
    )
    timezone = serializers.CharField(required=False, help_text="规则使用的 IANA 时区")
    is_active = serializers.BooleanField(required=False, help_text="是否启用规则")
    expected_version = serializers.IntegerField(
        min_value=1,
        help_text="查询规则响应中的 version",
    )


class ScheduleRuleResponseSerializer(serializers.Serializer):
    """周排期规则响应。"""

    rule_id = serializers.IntegerField(help_text="规则 ID")
    weekday = serializers.IntegerField(help_text="星期几")
    start_time = serializers.TimeField(help_text="开始时间")
    end_time = serializers.TimeField(help_text="结束时间")
    timezone = serializers.CharField(help_text="规则时区")
    slot_minutes = serializers.IntegerField(help_text="小时单元长度，当前固定为 60 分钟")
    is_active = serializers.BooleanField(help_text="规则是否启用")
    version = serializers.IntegerField(help_text="规则乐观锁版本号")
    schedule_version = serializers.IntegerField(help_text="修改后服务者排期版本号")


class ScheduleRuleDeleteSerializer(serializers.Serializer):
    """周排期规则删除请求。"""

    expected_version = serializers.IntegerField(
        min_value=1,
        help_text="查询规则响应中的 version",
    )


class ScheduleRuleDeleteResponseSerializer(serializers.Serializer):
    """周排期规则删除响应。"""

    deleted = serializers.BooleanField(help_text="规则是否已删除")
    rule_id = serializers.IntegerField(help_text="已删除规则 ID")
    schedule_version = serializers.IntegerField(help_text="修改后服务者排期版本号")


class AvailabilityQuerySerializer(serializers.Serializer):
    """公开查询可预约时间参数。"""

    service_id = serializers.UUIDField(
        required=False,
        help_text="预留服务 UUID 参数；当前排期不绑定服务，传入后暂不参与筛选",
    )
    date = serializers.DateField(
        required=False,
        help_text="查询日期，格式 YYYY-MM-DD；不传默认查询服务者本地当天",
    )
    date_from = serializers.DateField(
        required=False,
        help_text="自定义范围开始日期；与 date_to 同时提供",
    )
    date_to = serializers.DateField(
        required=False,
        help_text="自定义范围结束日期；与 date_from 同时提供",
    )
    timezone = serializers.CharField(
        default=settings.SCHEDULE_DEFAULT_TIMEZONE,
        help_text="查询时区，IANA 时区名称",
    )

    def validate_timezone(self, value: str) -> str:
        timezone_name = value.strip()
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise serializers.ValidationError("timezone 不是有效的 IANA 时区") from exc
        return timezone_name

    def validate(self, attrs: dict) -> dict:
        query_date = attrs.get("date")
        date_from = attrs.get("date_from")
        date_to = attrs.get("date_to")
        if query_date and (date_from or date_to):
            raise serializers.ValidationError("date 不能与 date_from/date_to 同时提供")
        if (date_from is None) != (date_to is None):
            raise serializers.ValidationError("date_from 和 date_to 必须同时提供")
        if date_from and date_to and date_to < date_from:
            raise serializers.ValidationError("date_to 不能早于 date_from")
        return attrs


class PublicAvailabilitySlotSerializer(serializers.Serializer):
    """公开可预约时段安全响应。"""

    slot_id = serializers.UUIDField(help_text="预约时段 UUID")
    service_id = serializers.UUIDField(
        allow_null=True,
        help_text="绑定服务 UUID；服务者通用时段为空",
    )
    service = ScheduleSlotServiceSerializer(
        allow_null=True,
        help_text="可预约服务最小摘要",
    )
    start_at = serializers.DateTimeField(help_text="时段开始时间")
    end_at = serializers.DateTimeField(help_text="时段结束时间")
    status = serializers.ChoiceField(
        choices=["OPEN"],
        help_text="公开接口只返回 OPEN 可预约时段",
    )
    slot_version = serializers.IntegerField(
        help_text="创建订单时作为 expected_slot_version",
    )
