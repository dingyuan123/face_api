from __future__ import annotations

from rest_framework import serializers

from backend.media.api.serializers import MediaAssetSummarySerializer
from backend.providers.services import validate_application_payload


class ProviderApplicationInputSerializer(serializers.Serializer):
    """服务者入驻申请提交请求。"""

    introduction = serializers.CharField(help_text="服务者个人简介")
    real_name = serializers.CharField(write_only=True, help_text="真实姓名；仅写入，不返回")
    id_card_number = serializers.CharField(
        write_only=True,
        help_text="中国大陆身份证号；仅写入并加密保存，不返回",
    )
    id_card_front_media_id = serializers.CharField(
        help_text="本人上传的身份证正面照片媒体 ID，仅用于实名认证和审核",
    )
    id_card_back_media_id = serializers.CharField(
        help_text="本人上传的身份证反面照片媒体 ID，仅用于实名认证和审核",
    )
    emergency_contact_name = serializers.CharField(
        help_text="紧急联系人姓名；服务端加密保存",
    )
    emergency_contact_phone = serializers.CharField(
        help_text="紧急联系人手机号；服务端加密保存，只返回脱敏值",
    )
    avatar_media_id = serializers.CharField(help_text="本人上传的服务者申请头像媒体 ID")
    life_photo_media_ids = serializers.ListField(
        child=serializers.CharField(),
        allow_empty=True,
        help_text="本人上传的生活照媒体 ID 列表，数量受服务端配置限制",
    )

    def validate(self, attrs: dict) -> dict:
        validate_application_payload(attrs)
        return attrs


class ProviderApplicationUpdateRequestSerializer(ProviderApplicationInputSerializer):
    """被拒绝或已取消申请的重提请求。"""

    expected_version = serializers.IntegerField(
        min_value=1,
        help_text="查询时返回的当前申请版本号，用于防止并发覆盖",
    )


class ProviderApplicationResponseSerializer(serializers.Serializer):
    """脱敏服务者申请响应。"""

    application_no = serializers.CharField(allow_null=True, help_text="服务者申请业务编号")
    status = serializers.CharField(help_text="申请状态")
    status_text = serializers.CharField(help_text="申请状态中文含义")
    introduction = serializers.CharField(help_text="服务者个人简介")
    avatar_media_id = serializers.CharField(allow_null=True, help_text="头像媒体 ID")
    id_card_front_media_id = serializers.CharField(
        allow_null=True,
        help_text="身份证正面照片媒体 ID，不返回身份证号码或姓名",
    )
    id_card_back_media_id = serializers.CharField(
        allow_null=True,
        help_text="身份证反面照片媒体 ID，不返回身份证号码或姓名",
    )
    emergency_contact_name = serializers.CharField(help_text="紧急联系人姓名")
    emergency_contact_phone_masked = serializers.CharField(
        help_text="紧急联系人手机号脱敏展示值，不返回完整手机号",
    )
    life_photo_media_ids = serializers.ListField(
        child=serializers.CharField(),
        help_text="生活照媒体 ID 列表",
    )
    real_name_status = serializers.CharField(help_text="实名认证状态，不返回真实姓名")
    real_name_status_text = serializers.CharField(help_text="实名认证状态中文含义")
    face_status = serializers.CharField(help_text="人脸认证状态")
    face_status_text = serializers.CharField(help_text="人脸认证状态中文含义")
    reject_reason = serializers.CharField(help_text="管理员拒绝原因；未拒绝时为空")
    submitted_at = serializers.DateTimeField(allow_null=True, help_text="申请提交时间")
    updated_at = serializers.DateTimeField(allow_null=True, help_text="申请最近更新时间")
    version = serializers.IntegerField(help_text="申请乐观锁版本号")
    user_public_id = serializers.UUIDField(help_text="申请人对外用户标识")
    user_phone_masked = serializers.CharField(help_text="申请人脱敏手机号")
    avatar_media = MediaAssetSummarySerializer(allow_null=True, help_text="头像媒体安全摘要")
    id_card_front_media = MediaAssetSummarySerializer(
        allow_null=True,
        help_text="身份证正面照片安全摘要，仅本人和管理员审核接口可读取",
    )
    id_card_back_media = MediaAssetSummarySerializer(
        allow_null=True,
        help_text="身份证反面照片安全摘要，仅本人和管理员审核接口可读取",
    )
    life_photo_media = MediaAssetSummarySerializer(many=True, help_text="生活照媒体安全摘要列表")


class ProviderReviewRequestSerializer(serializers.Serializer):
    """管理员审核请求。"""

    expected_version = serializers.IntegerField(
        min_value=1,
        help_text="审核前申请版本号，用于防止重复或并发审核",
    )
    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="拒绝原因；拒绝时必填，通过时可省略",
    )


class ProviderDashboardPendingSerializer(serializers.Serializer):
    """服务者工作台待处理事项数量。"""

    new_order_count = serializers.IntegerField(help_text="待接单的新订单数量")
    pending_confirm_count = serializers.IntegerField(help_text="待用户确认的订单数量")
    pending_review_count = serializers.IntegerField(
        help_text="已完成但用户尚未评价且仍在评价期限内的订单数量",
    )


class ProviderDashboardTodaySerializer(serializers.Serializer):
    """服务者今日经营概览。"""

    income_minor = serializers.IntegerField(help_text="今日服务者收入，单位为分")
    income_display = serializers.CharField(help_text="今日收入展示金额")
    created_order_count = serializers.IntegerField(help_text="今日创建订单数量")
    pending_items = ProviderDashboardPendingSerializer(help_text="当前待处理事项")


class ProviderDashboardOverviewSerializer(serializers.Serializer):
    """选定周期的数据概览。"""

    view_count = serializers.IntegerField(help_text="主页浏览量")
    visitor_count = serializers.IntegerField(help_text="主页独立访客数")
    created_order_count = serializers.IntegerField(help_text="周期内创建订单数量")
    completed_order_count = serializers.IntegerField(help_text="周期内完成订单数量")
    conversion_rate_bps = serializers.IntegerField(
        allow_null=True,
        help_text="完成订单/浏览量转化率万分比，无浏览量时为空",
    )
    income_minor = serializers.IntegerField(help_text="周期内服务者收入，单位为分")
    income_display = serializers.CharField(help_text="周期收入展示金额")
    tracking_available = serializers.BooleanField(help_text="是否已有浏览分析数据")


class ProviderDashboardComparisonSerializer(serializers.Serializer):
    """当前周期相对上一周期的变化。"""

    view_count_delta_percent = serializers.FloatField(
        allow_null=True,
        help_text="浏览量变化百分比",
    )
    visitor_count_delta_percent = serializers.FloatField(
        allow_null=True,
        help_text="访客数变化百分比",
    )
    order_count_delta_percent = serializers.FloatField(
        allow_null=True,
        help_text="订单量变化百分比",
    )
    conversion_rate_delta_percent = serializers.FloatField(
        allow_null=True,
        help_text="转化率变化百分比",
    )
    income_delta_percent = serializers.FloatField(
        allow_null=True,
        help_text="收入变化百分比",
    )


class ProviderIncomeTrendItemSerializer(serializers.Serializer):
    """按自然日的服务者收入趋势。"""

    date = serializers.CharField(help_text="统计日期 YYYY-MM-DD")
    income_minor = serializers.IntegerField(help_text="当日收入，单位为分")
    income_display = serializers.CharField(help_text="当日收入展示金额")
    order_count = serializers.IntegerField(help_text="当日收益记录数量")


class ProviderFunnelItemSerializer(serializers.Serializer):
    """转化漏斗阶段。"""

    event_type = serializers.CharField(help_text="分析事件类型")
    label = serializers.CharField(help_text="前端展示阶段名称")
    count = serializers.IntegerField(help_text="阶段事件数量")


class ProviderDashboardResponseSerializer(serializers.Serializer):
    """服务者工作台和数据看板响应。"""

    range = serializers.DictField(help_text="统计周期、日期范围和时区")
    today = ProviderDashboardTodaySerializer(help_text="今日概览")
    overview = ProviderDashboardOverviewSerializer(help_text="周期概览")
    comparison = ProviderDashboardComparisonSerializer(help_text="较上期变化")
    income_trend = ProviderIncomeTrendItemSerializer(many=True, help_text="收入趋势")
    funnel = ProviderFunnelItemSerializer(many=True, help_text="转化漏斗")
    suggestions = serializers.ListField(
        child=serializers.CharField(),
        help_text="规则化经营建议",
    )
