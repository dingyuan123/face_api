from __future__ import annotations

from rest_framework import serializers


class WalletResponseSerializer(serializers.Serializer):
    """用户钱包余额响应。"""

    currency = serializers.CharField(help_text="钱包币种")
    balance_amount_minor = serializers.IntegerField(help_text="钱包总余额，单位为分")
    frozen_amount_minor = serializers.IntegerField(help_text="冻结金额，单位为分")
    available_amount_minor = serializers.IntegerField(help_text="可用余额，单位为分")
    version = serializers.IntegerField(help_text="钱包版本号")
    updated_at = serializers.DateTimeField(help_text="钱包最近更新时间")


class WalletTransactionResponseSerializer(serializers.Serializer):
    """钱包流水响应。"""

    transaction_no = serializers.UUIDField(help_text="钱包流水 UUID")
    direction = serializers.CharField(help_text="资金方向，CREDIT 或 DEBIT")
    transaction_type = serializers.CharField(help_text="交易类型")
    business_type = serializers.CharField(help_text="关联业务类型")
    business_no = serializers.CharField(help_text="关联业务单号")
    currency = serializers.CharField(help_text="币种")
    amount_minor = serializers.IntegerField(help_text="变动金额，单位为分")
    balance_after_amount_minor = serializers.IntegerField(help_text="变动后余额，单位为分")
    created_at = serializers.DateTimeField(help_text="流水创建时间")


class WalletTopUpRequestSerializer(serializers.Serializer):
    """管理员测试余额充值请求。"""

    target_user_public_id = serializers.UUIDField(help_text="获得测试余额的用户 UUID")
    currency = serializers.CharField(default="CNY", help_text="充值币种，当前仅支持 CNY")
    amount_minor = serializers.IntegerField(help_text="测试充值金额，单位为分")
    reason = serializers.CharField(help_text="测试充值原因，用于审计")


class WalletTopUpResponseSerializer(serializers.Serializer):
    """管理员测试余额充值响应。"""

    topup_no = serializers.UUIDField(help_text="测试充值单 UUID")
    status = serializers.CharField(help_text="测试充值状态")
    channel = serializers.CharField(help_text="测试充值渠道")
    currency = serializers.CharField(help_text="充值币种")
    amount_minor = serializers.IntegerField(help_text="充值金额，单位为分")
    wallet_balance_amount_minor = serializers.IntegerField(help_text="充值后钱包余额，单位为分")
    transaction_no = serializers.UUIDField(allow_null=True, help_text="钱包流水 UUID")
