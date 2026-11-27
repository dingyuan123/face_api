"""优惠券用户查询、领取和管理员配置接口序列化契约。"""

from __future__ import annotations

from rest_framework import serializers


class CouponResponseSerializer(serializers.Serializer):
    """用户优惠券实例和使用条件。"""

    coupon_no = serializers.UUIDField(help_text="用户优惠券 UUID")
    template_no = serializers.UUIDField(help_text="优惠券模板 UUID")
    code = serializers.CharField(help_text="优惠券模板稳定代码")
    name = serializers.CharField(help_text="优惠券展示名称")
    status = serializers.CharField(help_text="优惠券状态")
    status_text = serializers.CharField(help_text="优惠券状态中文含义")
    currency = serializers.CharField(help_text="优惠金额币种")
    discount_amount_minor = serializers.IntegerField(help_text="固定优惠金额，单位为分")
    min_spend_amount_minor = serializers.IntegerField(help_text="最低使用门槛，单位为分")
    scope_type = serializers.CharField(help_text="适用范围类型")
    scope_type_text = serializers.CharField(help_text="适用范围中文含义")
    scope_value = serializers.CharField(help_text="适用城市、类目、服务或服务者代码")
    valid_from = serializers.DateTimeField(help_text="优惠券可用开始时间")
    valid_to = serializers.DateTimeField(help_text="优惠券可用截止时间")
    source_type = serializers.CharField(help_text="优惠券发放来源")
    source_type_text = serializers.CharField(help_text="优惠券发放来源中文含义")
    issued_at = serializers.DateTimeField(help_text="优惠券发放时间")
    used_at = serializers.DateTimeField(allow_null=True, help_text="优惠券使用时间")
    revoked_at = serializers.DateTimeField(allow_null=True, help_text="优惠券撤销时间")
    version = serializers.IntegerField(help_text="优惠券实例版本号")


class CouponListResponseSerializer(serializers.Serializer):
    """用户优惠券分页响应。"""

    items = CouponResponseSerializer(many=True, help_text="优惠券列表")
    total = serializers.IntegerField(help_text="优惠券总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")
    status = serializers.CharField(help_text="当前优惠券状态筛选")


class CouponClaimRequestSerializer(serializers.Serializer):
    """用户领取优惠券请求。"""

    idempotency_key = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=128,
        help_text="可选领取幂等键；未提供时建议客户端通过 Idempotency-Key 请求头传入",
    )


class CouponClaimResponseSerializer(serializers.Serializer):
    """用户领取优惠券结果。"""

    coupon = CouponResponseSerializer(help_text="领取的用户优惠券")
    created = serializers.BooleanField(help_text="是否新建券；幂等重放时为 false")
    reused = serializers.BooleanField(help_text="是否复用相同幂等领取请求")


class CouponRedemptionResponseSerializer(serializers.Serializer):
    """优惠券订单锁定、核销和释放记录。"""

    redemption_no = serializers.UUIDField(help_text="优惠券核销记录 UUID")
    coupon_no = serializers.UUIDField(help_text="用户优惠券 UUID")
    coupon_name = serializers.CharField(help_text="优惠券展示名称")
    order_no = serializers.CharField(help_text="关联订单业务 UUID")
    status = serializers.CharField(help_text="核销状态")
    status_text = serializers.CharField(help_text="核销状态中文含义")
    currency = serializers.CharField(help_text="金额币种")
    original_amount_minor = serializers.IntegerField(help_text="优惠前原价，单位为分")
    discount_amount_minor = serializers.IntegerField(help_text="优惠金额，单位为分")
    payable_amount_minor = serializers.IntegerField(help_text="优惠后应付金额，单位为分")
    reserved_at = serializers.DateTimeField(help_text="下单锁定时间")
    used_at = serializers.DateTimeField(allow_null=True, help_text="支付核销时间")
    released_at = serializers.DateTimeField(allow_null=True, help_text="订单释放时间")


class CouponRedemptionListResponseSerializer(serializers.Serializer):
    """优惠券核销记录分页响应。"""

    items = CouponRedemptionResponseSerializer(many=True, help_text="优惠券核销记录列表")
    total = serializers.IntegerField(help_text="记录总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")


class AdminCouponTemplateResponseSerializer(serializers.Serializer):
    """管理员优惠券模板配置。"""

    template_no = serializers.UUIDField(help_text="优惠券模板 UUID")
    code = serializers.CharField(help_text="模板稳定代码")
    name = serializers.CharField(help_text="优惠券展示名称")
    description = serializers.CharField(help_text="优惠券使用说明")
    discount_type = serializers.CharField(help_text="优惠类型")
    discount_type_text = serializers.CharField(help_text="优惠类型中文含义")
    currency = serializers.CharField(help_text="优惠金额币种")
    discount_amount_minor = serializers.IntegerField(help_text="固定优惠金额，单位为分")
    min_spend_amount_minor = serializers.IntegerField(help_text="最低消费门槛，单位为分")
    scope_type = serializers.CharField(help_text="适用范围类型")
    scope_type_text = serializers.CharField(help_text="适用范围中文含义")
    scope_value = serializers.CharField(help_text="适用范围代码")
    validity_type = serializers.CharField(help_text="有效期类型")
    validity_type_text = serializers.CharField(help_text="有效期类型中文含义")
    valid_from = serializers.DateTimeField(allow_null=True, help_text="固定有效期开始时间")
    valid_to = serializers.DateTimeField(allow_null=True, help_text="固定有效期截止时间")
    validity_days = serializers.IntegerField(allow_null=True, help_text="领取后有效天数")
    total_issue_limit = serializers.IntegerField(allow_null=True, help_text="发放总量上限")
    per_user_issue_limit = serializers.IntegerField(help_text="单用户领取上限")
    issued_count = serializers.IntegerField(help_text="累计发放数量")
    status = serializers.CharField(help_text="模板状态")
    status_text = serializers.CharField(help_text="模板状态中文含义")
    version = serializers.IntegerField(help_text="模板版本号")
    created_at = serializers.DateTimeField(help_text="模板创建时间")
    updated_at = serializers.DateTimeField(help_text="模板最近更新时间")


class AdminCouponTemplateListResponseSerializer(serializers.Serializer):
    """管理员优惠券模板分页响应。"""

    items = AdminCouponTemplateResponseSerializer(many=True, help_text="优惠券模板列表")
    total = serializers.IntegerField(help_text="模板总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")


class AdminCouponTemplateCreateRequestSerializer(serializers.Serializer):
    """管理员创建优惠券模板请求。"""

    code = serializers.CharField(max_length=64, help_text="模板稳定代码")
    name = serializers.CharField(max_length=100, help_text="优惠券展示名称")
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        help_text="优惠券使用说明",
    )
    discount_type = serializers.ChoiceField(
        choices=["FIXED_AMOUNT"],
        default="FIXED_AMOUNT",
        help_text="优惠类型，当前仅支持固定金额",
    )
    currency = serializers.CharField(required=False, default="CNY", max_length=3, help_text="币种")
    discount_amount_minor = serializers.IntegerField(
        min_value=1, help_text="固定优惠金额，单位为分"
    )
    min_spend_amount_minor = serializers.IntegerField(
        required=False,
        default=0,
        min_value=0,
        help_text="最低消费门槛，单位为分",
    )
    scope_type = serializers.ChoiceField(
        choices=["ALL", "CITY", "SERVICE_CATEGORY", "SERVICE", "PROVIDER"],
        default="ALL",
        help_text="适用范围类型",
    )
    scope_value = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=100,
        help_text="适用城市、类目、服务或服务者代码",
    )
    validity_type = serializers.ChoiceField(
        choices=["FIXED_PERIOD", "ISSUE_RELATIVE"],
        default="FIXED_PERIOD",
        help_text="有效期类型",
    )
    valid_from = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="固定有效期开始时间",
    )
    valid_to = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="固定有效期截止时间",
    )
    validity_days = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        help_text="领取后有效天数",
    )
    total_issue_limit = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        help_text="发放总量上限",
    )
    per_user_issue_limit = serializers.IntegerField(
        required=False,
        default=1,
        min_value=0,
        help_text="单用户领取上限，0 表示不限制",
    )
    status = serializers.ChoiceField(
        choices=["DRAFT", "ACTIVE", "PAUSED", "ENDED"],
        default="DRAFT",
        help_text="模板状态",
    )


class AdminCouponTemplateUpdateRequestSerializer(AdminCouponTemplateCreateRequestSerializer):
    """管理员修改优惠券模板请求。"""

    code = serializers.CharField(required=False, max_length=64, help_text="模板稳定代码")
    name = serializers.CharField(required=False, max_length=100, help_text="优惠券展示名称")
    expected_version = serializers.IntegerField(min_value=1, help_text="修改前模板版本号")


class AdminCouponIssueRequestSerializer(serializers.Serializer):
    """管理员向用户发放优惠券请求。"""

    user_public_id = serializers.UUIDField(help_text="目标用户公开 UUID")
    template_no = serializers.UUIDField(help_text="优惠券模板 UUID")
    source_no = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        help_text="可选发放来源业务单号，用于幂等去重",
    )
    valid_from = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="可选券有效期开始时间，仅领取后生效模板允许覆盖",
    )
    valid_to = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="可选券有效期截止时间，仅领取后生效模板允许覆盖",
    )


class AdminCouponIssueResponseSerializer(serializers.Serializer):
    """管理员发放优惠券结果。"""

    coupon = CouponResponseSerializer(help_text="发放的用户优惠券")
    created = serializers.BooleanField(help_text="是否新建券实例")


class AdminCouponRevokeRequestSerializer(serializers.Serializer):
    """管理员撤销未使用优惠券请求。"""

    reason = serializers.CharField(min_length=2, max_length=500, help_text="撤销原因")
    expected_version = serializers.IntegerField(min_value=1, help_text="撤销前券实例版本号")
