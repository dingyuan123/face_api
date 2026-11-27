"""会员套餐、购买、支付、有效期和管理员配置接口序列化契约。"""

from __future__ import annotations

from rest_framework import serializers


class MembershipPlanResponseSerializer(serializers.Serializer):
    """会员套餐当前版本展示信息。"""

    plan_no = serializers.UUIDField(help_text="会员套餐 UUID")
    code = serializers.CharField(help_text="会员套餐稳定代码")
    name = serializers.CharField(help_text="会员套餐展示名称")
    description = serializers.CharField(help_text="会员套餐展示说明")
    duration_days = serializers.IntegerField(help_text="套餐有效天数")
    currency = serializers.CharField(help_text="套餐价格币种")
    price_amount_minor = serializers.IntegerField(help_text="套餐价格，单位为分")
    benefits = serializers.ListField(help_text="会员权益配置列表")
    status = serializers.CharField(help_text="套餐状态")
    status_text = serializers.CharField(help_text="套餐状态中文含义")
    sort_order = serializers.IntegerField(help_text="套餐展示排序值")
    version = serializers.IntegerField(help_text="套餐当前版本号")


class MembershipPlanListResponseSerializer(serializers.Serializer):
    """会员套餐列表响应。"""

    items = MembershipPlanResponseSerializer(many=True, help_text="会员套餐列表")


class MembershipBenefitResponseSerializer(serializers.Serializer):
    """当前会员权益发放摘要。"""

    grant_no = serializers.UUIDField(help_text="权益发放 UUID")
    code = serializers.CharField(help_text="权益稳定代码")
    status = serializers.CharField(help_text="权益发放状态")
    status_text = serializers.CharField(help_text="权益发放状态中文含义")
    payload = serializers.DictField(help_text="权益参数和关联券实例摘要")


class MembershipPeriodResponseSerializer(serializers.Serializer):
    """会员有效期周期。"""

    period_no = serializers.UUIDField(help_text="会员有效期周期 UUID")
    purchase_no = serializers.UUIDField(help_text="关联会员购买单 UUID")
    plan = serializers.DictField(help_text="有效期对应套餐快照")
    status = serializers.CharField(help_text="有效期状态")
    status_text = serializers.CharField(help_text="有效期状态中文含义")
    starts_at = serializers.DateTimeField(help_text="有效期开始时间")
    ends_at = serializers.DateTimeField(help_text="有效期截止时间")
    activated_at = serializers.DateTimeField(help_text="有效期首次生效时间")
    expired_at = serializers.DateTimeField(allow_null=True, help_text="有效期到期标记时间")


class MembershipSummaryResponseSerializer(serializers.Serializer):
    """当前用户会员状态响应。"""

    is_member = serializers.BooleanField(help_text="当前是否处于会员有效期")
    plan = serializers.DictField(allow_null=True, help_text="当前会员套餐快照")
    period = MembershipPeriodResponseSerializer(
        allow_null=True,
        help_text="当前会员有效期周期",
    )
    benefits = MembershipBenefitResponseSerializer(many=True, help_text="当前会员权益列表")


class MembershipPurchaseCreateRequestSerializer(serializers.Serializer):
    """创建会员购买并发起支付请求。"""

    plan_code = serializers.CharField(max_length=32, help_text="会员套餐稳定代码")
    payment_method = serializers.ChoiceField(
        choices=["BALANCE", "WECHAT_APP", "ALIPAY_APP"],
        help_text="支付方式：钱包余额、微信 App 支付或支付宝 App 支付",
    )


class MembershipPaymentResponseSerializer(serializers.Serializer):
    """会员购买关联支付单安全摘要。"""

    payment_no = serializers.UUIDField(help_text="支付单 UUID")
    order_no = serializers.CharField(help_text="兼容业务单号")
    business_type = serializers.CharField(help_text="支付业务类型")
    business_no = serializers.CharField(help_text="支付业务单号")
    payment_method = serializers.CharField(help_text="支付方式")
    payment_method_text = serializers.CharField(help_text="支付方式中文含义")
    payment_channel = serializers.CharField(help_text="支付渠道代码")
    currency = serializers.CharField(help_text="支付币种")
    amount_minor = serializers.IntegerField(help_text="支付金额，单位为分")
    status = serializers.CharField(help_text="支付单状态")
    status_text = serializers.CharField(help_text="支付单状态中文含义")
    client_payload = serializers.DictField(help_text="原生支付 SDK 参数")
    expires_at = serializers.DateTimeField(allow_null=True, help_text="支付参数失效时间")
    paid_at = serializers.DateTimeField(allow_null=True, help_text="支付成功时间")
    version = serializers.IntegerField(help_text="支付单版本号")


class MembershipPurchaseResponseSerializer(serializers.Serializer):
    """会员购买单响应。"""

    purchase_no = serializers.UUIDField(help_text="会员购买单 UUID")
    status = serializers.CharField(help_text="购买单状态")
    status_text = serializers.CharField(help_text="购买单状态中文含义")
    plan = serializers.DictField(help_text="购买时套餐价格、时长和权益快照")
    currency = serializers.CharField(help_text="购买币种")
    amount_minor = serializers.IntegerField(help_text="购买金额，单位为分")
    payment_no = serializers.UUIDField(allow_null=True, help_text="关联支付单 UUID")
    payment = MembershipPaymentResponseSerializer(
        allow_null=True,
        help_text="关联支付单；未创建支付时为空",
    )
    version = serializers.IntegerField(help_text="购买单版本号")
    paid_at = serializers.DateTimeField(allow_null=True, help_text="支付成功时间")
    created_at = serializers.DateTimeField(help_text="购买单创建时间")
    updated_at = serializers.DateTimeField(help_text="购买单最近更新时间")


class MembershipPurchaseResultSerializer(serializers.Serializer):
    """会员购买发起结果。"""

    purchase = MembershipPurchaseResponseSerializer(help_text="会员购买单")
    payment = MembershipPaymentResponseSerializer(help_text="支付单及原生支付参数")
    payment_action = serializers.ChoiceField(
        choices=["NONE", "NATIVE_PAY"],
        help_text="NONE 表示直接成功，NATIVE_PAY 表示需要调起支付 SDK",
    )
    created = serializers.BooleanField(help_text="是否新建购买单")
    reused = serializers.BooleanField(help_text="是否复用相同幂等购买请求")


class MembershipPurchaseListResponseSerializer(serializers.Serializer):
    """会员购买历史分页响应。"""

    items = MembershipPurchaseResponseSerializer(many=True, help_text="会员购买历史")
    total = serializers.IntegerField(help_text="购买记录总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")


class AdminMembershipPlanCreateRequestSerializer(serializers.Serializer):
    """管理员创建会员套餐请求。"""

    code = serializers.CharField(max_length=32, help_text="会员套餐稳定代码")
    name = serializers.CharField(max_length=100, help_text="会员套餐展示名称")
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        help_text="会员套餐展示说明",
    )
    duration_days = serializers.IntegerField(min_value=1, help_text="套餐有效天数")
    currency = serializers.CharField(required=False, default="CNY", max_length=3, help_text="币种")
    price_amount_minor = serializers.IntegerField(min_value=1, help_text="套餐价格，单位为分")
    benefits = serializers.ListField(help_text="会员权益配置列表")
    sort_order = serializers.IntegerField(
        required=False, default=0, min_value=0, help_text="展示排序值"
    )


class AdminMembershipPlanUpdateRequestSerializer(serializers.Serializer):
    """管理员修改会员套餐请求；商业字段变化生成新版本。"""

    name = serializers.CharField(required=False, max_length=100, help_text="会员套餐展示名称")
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        help_text="会员套餐展示说明",
    )
    duration_days = serializers.IntegerField(required=False, min_value=1, help_text="套餐有效天数")
    currency = serializers.CharField(required=False, max_length=3, help_text="币种")
    price_amount_minor = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="套餐价格，单位为分",
    )
    benefits = serializers.ListField(required=False, help_text="会员权益配置列表")
    status = serializers.ChoiceField(
        required=False,
        choices=["DRAFT", "ACTIVE", "PAUSED", "ENDED"],
        help_text="套餐状态",
    )
    sort_order = serializers.IntegerField(required=False, min_value=0, help_text="展示排序值")
    expected_version = serializers.IntegerField(min_value=1, help_text="修改前套餐版本号")


class AdminMembershipPurchaseListResponseSerializer(serializers.Serializer):
    """管理员会员购买记录分页响应。"""

    items = MembershipPurchaseResponseSerializer(many=True, help_text="会员购买记录")
    total = serializers.IntegerField(help_text="购买记录总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")
