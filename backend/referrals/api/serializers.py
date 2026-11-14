"""分享推广接口请求和响应模型。"""

from __future__ import annotations

from rest_framework import serializers


class ReferralContextRequestSerializer(serializers.Serializer):
    """分享访问和注册归因上下文。"""

    share_no = serializers.CharField(required=False, allow_blank=True, help_text="分享链接 UUID")
    share_id = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="share_no 的兼容别名",
    )
    invite_code = serializers.CharField(required=False, allow_blank=True, help_text="邀请码")
    visitor_id = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="客户端匿名访问标识，服务端只保存摘要",
    )


class ReferralVisitResponseSerializer(serializers.Serializer):
    """匿名分享访问记录结果。"""

    visit_no = serializers.UUIDField(help_text="访问记录 UUID")
    share_no = serializers.UUIDField(help_text="来源分享链接 UUID")
    invite_code = serializers.CharField(help_text="来源邀请码")
    occurred_at = serializers.DateTimeField(help_text="访问时间")


class ShareLinkRequestSerializer(serializers.Serializer):
    """创建分享链接请求。"""

    channel = serializers.ChoiceField(
        choices=["WECHAT", "MOMENTS", "POSTER", "SYSTEM", "OTHER"],
        help_text="分享渠道",
    )
    campaign_code = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        help_text="运营活动代码",
    )


class ShareLinkResponseSerializer(serializers.Serializer):
    """分享链接响应。"""

    share_no = serializers.UUIDField(help_text="分享链接 UUID")
    invite_code = serializers.CharField(help_text="专属邀请码")
    channel = serializers.CharField(help_text="分享渠道")
    campaign_code = serializers.CharField(help_text="运营活动代码")
    status = serializers.CharField(help_text="分享链接状态")
    share_url = serializers.CharField(help_text="带邀请归因参数的公开分享链接")
    created_at = serializers.DateTimeField(help_text="创建时间")
    expires_at = serializers.DateTimeField(allow_null=True, help_text="过期时间，可为空")


class RewardSummaryItemSerializer(serializers.Serializer):
    """奖励状态汇总项。"""

    status = serializers.CharField(help_text="奖励状态")
    count = serializers.IntegerField(help_text="奖励数量")
    amount_minor = serializers.IntegerField(help_text="奖励金额合计，单位为分")


class ReferralOverviewResponseSerializer(serializers.Serializer):
    """分享赚钱页总览。"""

    invite_code = serializers.CharField(help_text="当前用户专属邀请码")
    share_link = ShareLinkResponseSerializer(help_text="个人海报稳定分享链接")
    registered_count = serializers.IntegerField(help_text="直接邀请注册人数")
    ordered_user_count = serializers.IntegerField(help_text="产生已完成订单的被邀请人数")
    valid_order_amount_minor = serializers.IntegerField(help_text="有效订单奖励基数合计，单位为分")
    reward_summary = serializers.DictField(help_text="按奖励状态汇总数量和金额")


class RewardResponseSerializer(serializers.Serializer):
    """推广奖励安全明细。"""

    reward_no = serializers.UUIDField(help_text="奖励业务 UUID")
    order_no = serializers.CharField(help_text="关联订单号")
    currency = serializers.CharField(help_text="奖励币种")
    reward_base_minor = serializers.IntegerField(help_text="有效奖励基数，单位为分")
    reward_rate_bps = serializers.IntegerField(help_text="订单锁定奖励比例万分比")
    amount_minor = serializers.IntegerField(help_text="当前奖励金额，单位为分")
    status = serializers.CharField(help_text="奖励状态")
    settle_after = serializers.DateTimeField(help_text="最早结算时间")
    settled_at = serializers.DateTimeField(allow_null=True, help_text="实际结算时间")
    cancel_reason = serializers.CharField(help_text="冻结或取消原因")
    version = serializers.IntegerField(help_text="奖励乐观锁版本号")
    policy_version = serializers.IntegerField(help_text="奖励政策版本号")
    created_at = serializers.DateTimeField(help_text="奖励创建时间")
    updated_at = serializers.DateTimeField(help_text="奖励最近更新时间")


class RewardListResponseSerializer(serializers.Serializer):
    """推广奖励分页列表。"""

    items = RewardResponseSerializer(many=True, help_text="奖励明细")
    total = serializers.IntegerField(help_text="筛选后奖励总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")


class ReferralPolicyRequestSerializer(serializers.Serializer):
    """创建不可变奖励政策版本请求。"""

    version = serializers.IntegerField(min_value=1, help_text="递增政策版本号")
    name = serializers.CharField(required=False, allow_blank=True, help_text="政策名称")
    reward_rate_bps = serializers.IntegerField(
        min_value=0,
        max_value=10000,
        help_text="奖励比例万分比，1000 表示 10%",
    )
    max_reward_amount_minor = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        help_text="单笔奖励上限，单位为分；null 表示不限制",
    )
    min_order_amount_minor = serializers.IntegerField(
        required=False,
        min_value=0,
        help_text="最低有效订单金额，单位为分",
    )
    funding_cap_to_platform_fee = serializers.BooleanField(
        required=False,
        help_text="奖励是否受订单平台服务费资金来源限制",
    )
    settlement_delay_days = serializers.IntegerField(
        required=False,
        min_value=0,
        help_text="订单完成后的观察和结算延迟天数",
    )
    effective_from = serializers.DateTimeField(help_text="政策开始生效时间")
    effective_to = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="政策停止生效时间",
    )


class ReferralPolicyResponseSerializer(serializers.Serializer):
    """奖励政策版本响应。"""

    policy_no = serializers.UUIDField(help_text="政策版本 UUID")
    version = serializers.IntegerField(help_text="政策版本号")
    name = serializers.CharField(help_text="政策名称")
    status = serializers.CharField(help_text="政策状态")
    reward_rate_bps = serializers.IntegerField(help_text="奖励比例万分比")
    max_reward_amount_minor = serializers.IntegerField(
        allow_null=True,
        help_text="单笔奖励上限，单位为分",
    )
    min_order_amount_minor = serializers.IntegerField(help_text="最低有效订单金额，单位为分")
    funding_cap_to_platform_fee = serializers.BooleanField(help_text="是否受平台服务费限制")
    settlement_delay_days = serializers.IntegerField(help_text="结算延迟天数")
    effective_from = serializers.DateTimeField(help_text="开始生效时间")
    effective_to = serializers.DateTimeField(allow_null=True, help_text="停止生效时间")
    created_at = serializers.DateTimeField(help_text="创建时间")


class ReferralPolicyRetireResponseSerializer(serializers.Serializer):
    """停止奖励政策版本结果。"""

    policy_no = serializers.UUIDField(help_text="政策版本 UUID")
    status = serializers.CharField(help_text="停止后的政策状态")


class RewardStateRequestSerializer(serializers.Serializer):
    """奖励冻结、解冻或取消请求。"""

    expected_version = serializers.IntegerField(min_value=1, help_text="查询返回的奖励版本号")
    reason = serializers.CharField(min_length=2, max_length=255, help_text="操作原因")


class RewardAdjustRequestSerializer(serializers.Serializer):
    """奖励人工调整请求。"""

    expected_version = serializers.IntegerField(min_value=1, help_text="查询返回的奖励版本号")
    amount_delta_minor = serializers.IntegerField(help_text="奖励变化量，单位为分，可正可负")
    reason = serializers.CharField(min_length=2, max_length=255, help_text="调整原因")
