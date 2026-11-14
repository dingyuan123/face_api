"""支付单查询和渠道回调文档模型。"""

from __future__ import annotations

from rest_framework import serializers


class PaymentDetailSerializer(serializers.Serializer):
    """当前用户支付单安全查询响应。"""

    payment_no = serializers.UUIDField(help_text="支付单 UUID")
    order_no = serializers.UUIDField(help_text="关联订单 UUID")
    payment_method = serializers.ChoiceField(
        choices=["BALANCE", "WECHAT_APP", "ALIPAY_APP"],
        help_text="支付方式",
    )
    payment_channel = serializers.CharField(help_text="支付渠道代码")
    currency = serializers.CharField(help_text="支付币种")
    amount_minor = serializers.IntegerField(help_text="支付金额，单位为分")
    status = serializers.ChoiceField(
        choices=["PENDING", "SUCCESS", "FAILED", "CLOSED", "REFUNDED"],
        help_text="支付单状态",
    )
    client_payload = serializers.DictField(help_text="原生支付 SDK 调起参数")
    expires_at = serializers.DateTimeField(
        allow_null=True,
        help_text="支付参数失效时间",
    )
    paid_at = serializers.DateTimeField(allow_null=True, help_text="支付成功时间")
    version = serializers.IntegerField(help_text="支付单版本号")


class PaymentNotifyResponseSerializer(serializers.Serializer):
    """渠道通知处理结果；实际响应格式由支付平台要求决定。"""

    processed = serializers.BooleanField(help_text="是否处理成功")
