"""收款方式、收益账户和提现接口的请求响应模型。"""

from __future__ import annotations

from rest_framework import serializers


class PayoutMethodCreateRequestSerializer(serializers.Serializer):
    """创建银行卡、支付宝或微信收款方式请求。"""

    method_type = serializers.ChoiceField(
        choices=["BANK_CARD", "ALIPAY", "WECHAT_PAY"],
        help_text="收款方式类型，支持银行卡、支付宝或微信支付",
    )
    account_name = serializers.CharField(help_text="收款账户姓名，服务端加密保存并脱敏返回")
    account_number = serializers.CharField(
        help_text="银行卡号、支付宝账号或微信账号，服务端加密保存并脱敏返回",
    )
    institution_name = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="银行名称；银行卡必填，支付宝和微信支付可不传",
    )
    is_default = serializers.BooleanField(
        default=True,
        help_text="是否设为默认收款方式；首个启用绑定会自动成为默认",
    )


class PayoutMethodExpectedVersionSerializer(serializers.Serializer):
    """收款方式启停和默认设置并发控制请求。"""

    expected_version = serializers.IntegerField(
        min_value=1,
        help_text="查询接口返回的收款方式版本号",
    )


class PayoutMethodResponseSerializer(serializers.Serializer):
    """收款方式脱敏响应，不包含账户明文。"""

    id = serializers.UUIDField(help_text="收款方式 UUID")
    method_type = serializers.CharField(help_text="收款方式类型")
    binding_mode = serializers.CharField(help_text="绑定方式，当前为 MANUAL，预留 OAUTH")
    status = serializers.CharField(help_text="收款方式状态")
    verification_status = serializers.CharField(help_text="账户验证状态，当前为模拟验证")
    is_default = serializers.BooleanField(help_text="是否为默认收款方式")
    account_name_masked = serializers.CharField(help_text="账户姓名脱敏值")
    account_number_masked = serializers.CharField(help_text="收款账号脱敏值")
    institution_name = serializers.CharField(help_text="银行或支付渠道名称")
    display_text = serializers.CharField(help_text="前端安全展示文案")
    version = serializers.IntegerField(help_text="收款方式版本号")
    created_at = serializers.DateTimeField(help_text="创建时间")
    updated_at = serializers.DateTimeField(help_text="更新时间")
    deactivated_at = serializers.DateTimeField(
        allow_null=True,
        help_text="停用时间，空值表示启用中",
    )


class PayoutMethodListResponseSerializer(serializers.Serializer):
    """收款方式列表响应。"""

    items = PayoutMethodResponseSerializer(many=True, help_text="当前用户收款方式列表")
    has_default = serializers.BooleanField(help_text="是否存在启用中的默认收款方式")


class EarningAccountResponseSerializer(serializers.Serializer):
    """服务者收入或普通用户推广收益账户汇总。"""

    account_type = serializers.CharField(help_text="账户类型，PROVIDER_INCOME 或 REFERRAL_REWARD")
    currency = serializers.CharField(help_text="币种代码")
    available_amount_minor = serializers.IntegerField(help_text="可提现金额，单位为分")
    frozen_amount_minor = serializers.IntegerField(help_text="提现冻结金额，单位为分")
    total_income_amount_minor = serializers.IntegerField(help_text="累计收入，单位为分")
    total_withdrawn_amount_minor = serializers.IntegerField(help_text="累计提现成功金额，单位为分")
    pending_settlement_amount_minor = serializers.IntegerField(
        help_text="待结算收益金额，单位为分",
    )
    version = serializers.IntegerField(help_text="账户版本号，申请提现时使用")
    updated_at = serializers.DateTimeField(help_text="账户更新时间")


class EarningEntryResponseSerializer(serializers.Serializer):
    """单笔收入或推广收益明细。"""

    earning_no = serializers.UUIDField(help_text="收益业务 UUID")
    business_type = serializers.CharField(help_text="收益来源业务类型")
    business_no = serializers.CharField(help_text="收益来源订单或奖励单号")
    currency = serializers.CharField(help_text="币种代码")
    gross_amount_minor = serializers.IntegerField(help_text="收益计算前金额，单位为分")
    platform_fee_amount_minor = serializers.IntegerField(help_text="平台佣金，单位为分")
    net_amount_minor = serializers.IntegerField(help_text="实际入账收益，单位为分")
    status = serializers.CharField(help_text="收益结算状态")
    available_at = serializers.DateTimeField(help_text="最早可结算时间")
    settled_at = serializers.DateTimeField(allow_null=True, help_text="实际结算时间")
    created_at = serializers.DateTimeField(help_text="收益记录创建时间")


class EarningEntryListResponseSerializer(serializers.Serializer):
    """收益明细分页响应。"""

    items = EarningEntryResponseSerializer(many=True, help_text="收益明细列表")
    total = serializers.IntegerField(help_text="筛选后的收益明细总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")


class EarningTransactionResponseSerializer(serializers.Serializer):
    """收益账户不可变资金流水。"""

    transaction_no = serializers.UUIDField(help_text="收益流水 UUID")
    direction = serializers.CharField(help_text="资金方向，CREDIT、DEBIT、HOLD 或 RELEASE")
    transaction_type = serializers.CharField(help_text="流水业务类型")
    business_type = serializers.CharField(help_text="关联业务类型")
    business_no = serializers.CharField(help_text="关联业务单号")
    currency = serializers.CharField(help_text="币种代码")
    amount_minor = serializers.IntegerField(help_text="变动金额，单位为分")
    available_after_amount_minor = serializers.IntegerField(help_text="变动后可提现金额")
    frozen_after_amount_minor = serializers.IntegerField(help_text="变动后冻结金额")
    created_at = serializers.DateTimeField(help_text="流水创建时间")


class EarningTransactionListResponseSerializer(serializers.Serializer):
    """收益流水分页响应。"""

    items = EarningTransactionResponseSerializer(many=True, help_text="收益流水列表")
    total = serializers.IntegerField(help_text="筛选后的收益流水总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")


class WithdrawalCreateRequestSerializer(serializers.Serializer):
    """服务者收入或普通用户推广收益提现申请。"""

    account_type = serializers.ChoiceField(
        choices=["PROVIDER_INCOME", "REFERRAL_REWARD"],
        help_text="提现账户类型，服务者收入或普通用户推广收益",
    )
    amount_minor = serializers.IntegerField(help_text="提现总额，单位为分，不能低于配置最低金额")
    payout_method_id = serializers.UUIDField(help_text="本人启用中的收款方式 UUID")
    expected_version = serializers.IntegerField(
        min_value=1,
        help_text="收益账户查询接口返回的版本号",
    )


class WithdrawalExpectedVersionSerializer(serializers.Serializer):
    """提现撤销、审核和重试并发控制请求。"""

    expected_version = serializers.IntegerField(
        min_value=1,
        help_text="提现单查询接口返回的版本号",
    )


class WithdrawalReviewRequestSerializer(serializers.Serializer):
    """管理员审核提现请求。"""

    expected_version = serializers.IntegerField(
        min_value=1,
        help_text="提现单查询接口返回的版本号",
    )
    review_note = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        help_text="人工审核说明，拒绝时建议填写原因",
    )


class WithdrawalPayoutMethodSerializer(serializers.Serializer):
    """提现单绑定的脱敏收款方式快照。"""

    id = serializers.UUIDField(help_text="收款方式 UUID")
    method_type = serializers.CharField(help_text="收款方式类型")
    display_text = serializers.CharField(help_text="收款账户脱敏展示文案")


class WithdrawalResponseSerializer(serializers.Serializer):
    """提现单安全响应。"""

    withdrawal_no = serializers.UUIDField(help_text="提现单 UUID")
    account_type = serializers.CharField(help_text="提现账户类型")
    currency = serializers.CharField(help_text="币种代码")
    amount_minor = serializers.IntegerField(help_text="申请提现总额，单位为分")
    fee_amount_minor = serializers.IntegerField(help_text="提现手续费，单位为分")
    payout_amount_minor = serializers.IntegerField(help_text="实际打款金额，单位为分")
    status = serializers.CharField(help_text="提现状态")
    payout_method = WithdrawalPayoutMethodSerializer(help_text="脱敏收款方式快照")
    review_note = serializers.CharField(help_text="人工审核说明")
    failure_reason = serializers.CharField(help_text="打款失败原因")
    channel_reference = serializers.CharField(help_text="模拟或真实打款渠道流水号")
    version = serializers.IntegerField(help_text="提现单版本号")
    created_at = serializers.DateTimeField(help_text="申请创建时间")
    updated_at = serializers.DateTimeField(help_text="提现单更新时间")
    reviewed_at = serializers.DateTimeField(allow_null=True, help_text="人工审核时间")
    completed_at = serializers.DateTimeField(allow_null=True, help_text="最终完成时间")


class WithdrawalListResponseSerializer(serializers.Serializer):
    """提现单分页响应。"""

    items = WithdrawalResponseSerializer(many=True, help_text="提现单列表")
    total = serializers.IntegerField(help_text="筛选后的提现单总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")
