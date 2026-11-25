"""客服工单、消息和常见问题接口模型。"""

from __future__ import annotations

from rest_framework import serializers


class SupportTicketCreateRequestSerializer(serializers.Serializer):
    """用户创建客服工单。"""

    category = serializers.ChoiceField(
        choices=["ORDER", "REFUND", "ACCOUNT", "CONTENT", "FEEDBACK", "OTHER"],
        default="OTHER",
        help_text="工单分类",
    )
    subject = serializers.CharField(min_length=2, max_length=120, help_text="工单主题")
    description = serializers.CharField(min_length=2, max_length=5000, help_text="问题描述")
    priority = serializers.ChoiceField(
        choices=["LOW", "NORMAL", "HIGH", "URGENT"],
        default="NORMAL",
        help_text="优先级",
    )
    related_order_no = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        help_text="关联订单号",
    )


class SupportMessageRequestSerializer(serializers.Serializer):
    """发送客服消息。"""

    content = serializers.CharField(min_length=1, max_length=5000, help_text="消息正文")
    client_message_id = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=128,
        help_text="客户端消息幂等标识",
    )


class SupportMessageResponseSerializer(serializers.Serializer):
    """客服消息响应。"""

    message_id = serializers.IntegerField(help_text="消息 ID")
    ticket_no = serializers.UUIDField(help_text="工单 UUID")
    sender_type = serializers.CharField(help_text="发送者类型")
    sender_type_text = serializers.CharField(help_text="发送者类型中文含义")
    sender_id = serializers.IntegerField(allow_null=True, help_text="发送者用户 ID")
    content = serializers.CharField(help_text="消息正文")
    sequence = serializers.IntegerField(help_text="工单内消息序号")
    client_message_id = serializers.CharField(help_text="客户端消息幂等标识")
    created_at = serializers.DateTimeField(help_text="消息创建时间")


class SupportTicketResponseSerializer(serializers.Serializer):
    """客服工单响应。"""

    ticket_no = serializers.UUIDField(help_text="工单 UUID")
    user_public_id = serializers.UUIDField(help_text="用户 UUID")
    category = serializers.CharField(help_text="工单分类")
    category_text = serializers.CharField(help_text="工单分类中文含义")
    subject = serializers.CharField(help_text="工单主题")
    description = serializers.CharField(help_text="问题描述")
    status = serializers.CharField(help_text="工单状态")
    status_text = serializers.CharField(help_text="工单状态中文含义")
    priority = serializers.CharField(help_text="优先级")
    priority_text = serializers.CharField(help_text="优先级中文含义")
    related_order_no = serializers.CharField(help_text="关联订单号")
    assigned_agent_id = serializers.IntegerField(allow_null=True, help_text="客服管理员 ID")
    resolution = serializers.CharField(help_text="处理结论")
    version = serializers.IntegerField(help_text="工单版本号")
    created_at = serializers.DateTimeField(help_text="创建时间")
    updated_at = serializers.DateTimeField(help_text="更新时间")
    resolved_at = serializers.DateTimeField(allow_null=True, help_text="解决时间")


class SupportTicketListResponseSerializer(serializers.Serializer):
    """客服工单分页响应。"""

    items = SupportTicketResponseSerializer(many=True, help_text="工单列表")
    total = serializers.IntegerField(help_text="工单总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")


class SupportMessageListResponseSerializer(serializers.Serializer):
    """客服消息增量响应。"""

    ticket_no = serializers.UUIDField(help_text="工单 UUID")
    items = SupportMessageResponseSerializer(many=True, help_text="消息列表")
    next_sequence = serializers.IntegerField(help_text="下一条消息序号")


class SupportTicketActionRequestSerializer(serializers.Serializer):
    """客服工单状态操作。"""

    expected_version = serializers.IntegerField(min_value=1, help_text="工单版本号")
    resolution = serializers.CharField(required=False, allow_blank=True, max_length=500)


class SupportAssignRequestSerializer(serializers.Serializer):
    """客服分配请求。"""

    expected_version = serializers.IntegerField(min_value=1, help_text="工单版本号")
    agent_user_id = serializers.IntegerField(min_value=1, help_text="客服管理员用户 ID")
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)


class SupportFAQRequestSerializer(serializers.Serializer):
    """常见问题创建或修改。"""

    question = serializers.CharField(max_length=200)
    answer = serializers.CharField()
    category = serializers.CharField(required=False, default="GENERAL", max_length=50)
    sort_order = serializers.IntegerField(required=False, default=0, min_value=0)
    is_active = serializers.BooleanField(required=False, default=True)
    expected_version = serializers.IntegerField(required=False, min_value=1)


class SupportFAQResponseSerializer(serializers.Serializer):
    """常见问题响应。"""

    id = serializers.IntegerField(help_text="常见问题 ID")
    question = serializers.CharField(help_text="问题")
    answer = serializers.CharField(help_text="答案")
    category = serializers.CharField(help_text="分类")
    sort_order = serializers.IntegerField(help_text="排序值")
    is_active = serializers.BooleanField(help_text="是否启用")
    version = serializers.IntegerField(help_text="版本号")
