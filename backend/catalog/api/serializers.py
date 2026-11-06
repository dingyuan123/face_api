from __future__ import annotations

from rest_framework import serializers

from backend.media.api.serializers import MediaAssetSummarySerializer


class MoneySerializer(serializers.Serializer):
    """服务基础价格金额。"""

    currency = serializers.CharField(help_text="币种代码，当前仅支持 CNY")
    amount_minor = serializers.IntegerField(help_text="金额最小单位，CNY 为分")


class ServiceCategoryResponseSerializer(serializers.Serializer):
    """服务类目配置。"""

    code = serializers.CharField(help_text="服务类目稳定代码")
    name = serializers.CharField(help_text="服务类目展示名称")
    sort_order = serializers.IntegerField(help_text="类目展示排序值")


class ServiceTagResponseSerializer(serializers.Serializer):
    """服务标签配置。"""

    code = serializers.CharField(help_text="服务标签稳定代码")
    name = serializers.CharField(help_text="服务标签展示名称")
    category = serializers.CharField(help_text="服务标签分类")
    sort_order = serializers.IntegerField(help_text="服务标签展示排序值")


class ProviderTagResponseSerializer(serializers.Serializer):
    """服务者资料标签配置。"""

    code = serializers.CharField(help_text="服务者标签稳定代码")
    name = serializers.CharField(help_text="服务者标签展示名称")
    category = serializers.CharField(help_text="服务者标签分类")
    sort_order = serializers.IntegerField(help_text="服务者标签展示排序值")


class ServiceCreateRequestSerializer(serializers.Serializer):
    """创建服务草稿请求。"""

    title = serializers.CharField(help_text="服务名称，最多 30 个字符")
    category_code = serializers.CharField(help_text="服务类目稳定代码")
    currency = serializers.CharField(default="CNY", help_text="币种代码，当前仅支持 CNY")
    price_amount_minor = serializers.IntegerField(
        help_text="服务基础价格，单位为分；例如 68.00 元填写 6800",
    )
    duration_minutes = serializers.IntegerField(help_text="服务时长，单位为分钟")
    introduction = serializers.CharField(help_text="服务介绍，不能为空")
    cover_media_id = serializers.CharField(help_text="服务封面媒体 ID，必须为本人服务封面媒体")
    gallery_media_ids = serializers.ListField(
        child=serializers.CharField(),
        allow_empty=False,
        help_text="服务图集媒体 ID，1 到 6 张",
    )
    tag_codes = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="服务标签代码列表，最多 8 个",
    )
    location_type = serializers.CharField(
        default="PUBLIC_PLACE",
        help_text="服务地点类型，当前仅支持 PUBLIC_PLACE",
    )


class ServiceUpdateRequestSerializer(ServiceCreateRequestSerializer):
    """修改服务请求。"""

    expected_version = serializers.IntegerField(
        min_value=1,
        help_text="查询接口返回的服务版本号",
    )


class ServiceResponseSerializer(serializers.Serializer):
    """服务安全响应。"""

    id = serializers.UUIDField(help_text="对外服务 UUID")
    version = serializers.IntegerField(help_text="服务版本号")
    title = serializers.CharField(help_text="服务名称")
    category_code = serializers.CharField(help_text="服务类目代码")
    pricing_unit = serializers.CharField(help_text="计价单位，当前固定为 HOUR 按小时计价")
    price = MoneySerializer(help_text="服务每小时价格")
    price_display = serializers.CharField(help_text="只读每小时价格展示字符串，不作为提交值")
    duration_minutes = serializers.IntegerField(help_text="服务时长，单位为分钟")
    introduction = serializers.CharField(help_text="服务介绍")
    cover_media = MediaAssetSummarySerializer(help_text="服务封面媒体摘要")
    gallery_media = MediaAssetSummarySerializer(many=True, help_text="服务图集媒体摘要")
    tag_codes = serializers.ListField(child=serializers.CharField(), help_text="服务标签代码")
    location_type = serializers.CharField(help_text="服务地点类型")
    status = serializers.CharField(help_text="服务状态")
    reject_reason = serializers.CharField(help_text="审核拒绝原因")
    sold_count = serializers.IntegerField(help_text="累计已售数量，只读")
    updated_at = serializers.DateTimeField(help_text="服务最近更新时间")


class ServiceSummarySerializer(serializers.Serializer):
    """服务列表汇总。"""

    total = serializers.IntegerField(help_text="全部服务数量")
    online = serializers.IntegerField(help_text="已上架服务数量")
    pending = serializers.IntegerField(help_text="审核中服务数量")
    sold_count = serializers.IntegerField(help_text="累计已售数量")


class ServiceListResponseSerializer(serializers.Serializer):
    """服务列表响应。"""

    items = ServiceResponseSerializer(many=True, help_text="服务列表")
    total = serializers.IntegerField(help_text="筛选后的服务总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")
    summary = ServiceSummarySerializer(help_text="服务汇总")


class AdminServiceProviderSerializer(serializers.Serializer):
    """管理员服务列表中的服务者摘要。"""

    user_public_id = serializers.UUIDField(help_text="服务者对外用户标识")
    nickname = serializers.CharField(allow_null=True, help_text="服务者昵称")
    phone_masked = serializers.CharField(help_text="脱敏手机号")


class AdminServiceResponseSerializer(ServiceResponseSerializer):
    """管理员服务列表对象。"""

    provider = AdminServiceProviderSerializer(help_text="服务归属服务者摘要")


class AdminServiceSummarySerializer(serializers.Serializer):
    """管理员服务状态汇总。"""

    total = serializers.IntegerField(help_text="全部未删除服务数量")
    draft = serializers.IntegerField(help_text="草稿数量")
    pending = serializers.IntegerField(help_text="审核中数量")
    approved = serializers.IntegerField(help_text="审核通过数量")
    online = serializers.IntegerField(help_text="已上架数量")
    offline = serializers.IntegerField(help_text="已下架数量")
    rejected = serializers.IntegerField(help_text="审核拒绝数量")
    sold_count = serializers.IntegerField(help_text="累计已售数量")


class AdminServiceListResponseSerializer(serializers.Serializer):
    """管理员服务列表响应。"""

    items = AdminServiceResponseSerializer(many=True, help_text="服务列表")
    total = serializers.IntegerField(help_text="筛选后的服务总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")
    summary = AdminServiceSummarySerializer(help_text="全平台服务状态汇总")


class ExpectedVersionSerializer(serializers.Serializer):
    """服务状态操作请求。"""

    expected_version = serializers.IntegerField(min_value=1, help_text="当前服务版本号")


class ServiceReviewRequestSerializer(serializers.Serializer):
    """管理员服务审核请求。"""

    expected_version = serializers.IntegerField(min_value=1, help_text="当前服务版本号")
    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="拒绝原因；拒绝时必填，通过时可省略",
    )
