"""账号注销条件检查、短信确认和注销请求响应模型。"""

from __future__ import annotations

from rest_framework import serializers


class AccountDeletionCheckItemSerializer(serializers.Serializer):
    """账号注销单项条件检查结果。"""

    key = serializers.CharField(help_text="固定条件代码：orders、wallet、services 或 security")
    title = serializers.CharField(help_text="条件分组标题")
    description = serializers.CharField(help_text="条件检查中文说明")
    passed = serializers.BooleanField(help_text="该条件是否通过")
    action = serializers.CharField(help_text="未通过时的操作按钮文案")
    action_route = serializers.CharField(help_text="操作按钮跳转路由；通过时为空")


class AccountDeletionCheckResponseSerializer(serializers.Serializer):
    """账号注销四项条件检查响应。"""

    can_delete = serializers.BooleanField(help_text="四项条件是否全部通过")
    items = AccountDeletionCheckItemSerializer(
        many=True,
        help_text="固定顺序的订单、资金、服务和安全条件",
    )


class AccountDeletionSmsResponseSerializer(serializers.Serializer):
    """账号注销验证码发送结果。"""

    phone_masked = serializers.CharField(help_text="绑定手机号脱敏展示值")
    request_id = serializers.UUIDField(help_text="验证码请求标识")
    expires_in = serializers.IntegerField(help_text="验证码剩余有效秒数")
    debug_code = serializers.CharField(
        allow_null=True,
        help_text="开发 Mock 验证码；生产环境不返回",
    )


class AccountDeletionConfirmRequestSerializer(serializers.Serializer):
    """不可恢复的账号注销确认请求。"""

    code = serializers.CharField(
        min_length=6,
        max_length=6,
        help_text="发送到绑定手机号的 6 位注销验证码",
    )
    confirm = serializers.BooleanField(help_text="必须为 true 确认不可恢复注销")


class AccountDeletionResponseSerializer(serializers.Serializer):
    """账号注销完成和清理审计响应。"""

    request_no = serializers.UUIDField(help_text="账号注销审计 UUID")
    phone_masked = serializers.CharField(help_text="注销前手机号脱敏审计快照")
    deleted_at = serializers.DateTimeField(help_text="账号注销完成时间")
    cleanup_counts = serializers.DictField(help_text="个人资料、绑定和内容清理数量")
    retained_categories = serializers.ListField(
        child=serializers.CharField(),
        help_text="依法保留或匿名化的数据类别",
    )
