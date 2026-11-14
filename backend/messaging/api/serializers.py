"""订单实时聊天接口的请求和响应文档模型。"""

from __future__ import annotations

from rest_framework import serializers

from backend.media.api.serializers import MediaAssetSummarySerializer


class ChatUserSummarySerializer(serializers.Serializer):
    """聊天参与人的公开资料摘要。"""

    user_public_id = serializers.UUIDField(help_text="参与用户公开 UUID")
    nickname = serializers.CharField(help_text="参与用户昵称或脱敏手机号")
    avatar_media = MediaAssetSummarySerializer(
        allow_null=True,
        help_text="参与用户头像；包含可直接展示的临时图片地址",
    )


class ChatOrderSummarySerializer(serializers.Serializer):
    """聊天会话关联订单的安全摘要。"""

    order_no = serializers.UUIDField(help_text="关联订单 UUID")
    status = serializers.CharField(help_text="订单当前状态")
    service_title = serializers.CharField(help_text="订单服务名称")
    cover_media = MediaAssetSummarySerializer(
        allow_null=True,
        help_text="服务封面；包含可直接展示的临时图片地址",
    )


class MessageResponseSerializer(serializers.Serializer):
    """文本、图片或系统聊天消息。"""

    message_no = serializers.UUIDField(help_text="消息业务 UUID")
    conversation_id = serializers.UUIDField(help_text="所属订单会话 UUID")
    sequence = serializers.IntegerField(help_text="会话内严格递增消息序号")
    sender_public_id = serializers.UUIDField(
        allow_null=True,
        help_text="发送者公开 UUID；系统消息为空",
    )
    sender_role = serializers.CharField(help_text="发送者订单角色")
    message_type = serializers.CharField(help_text="消息类型：TEXT、IMAGE 或 SYSTEM")
    content = serializers.CharField(help_text="文本内容或图片说明")
    media = MediaAssetSummarySerializer(allow_null=True, help_text="图片消息媒体")
    client_message_id = serializers.CharField(
        allow_null=True,
        help_text="客户端幂等标识；重复请求返回同一条消息",
    )
    created_at = serializers.CharField(help_text="消息创建时间，格式 YYYY-MM-DD HH:mm:ss")
    revoked_at = serializers.CharField(
        allow_null=True,
        help_text="消息撤回时间，格式 YYYY-MM-DD HH:mm:ss；未撤回为空",
    )


class ConversationResponseSerializer(serializers.Serializer):
    """用户与服务者共享会话详情和当前用户会话状态。"""

    conversation_id = serializers.UUIDField(help_text="订单会话 UUID")
    order = ChatOrderSummarySerializer(help_text="最新关联订单安全摘要，决定当前聊天窗口")
    orders = ChatOrderSummarySerializer(
        many=True,
        help_text="双方历史订单安全摘要；同一用户与服务者复用同一会话",
    )
    order_count = serializers.IntegerField(help_text="双方已关联的聊天资格订单数")
    participants = ChatUserSummarySerializer(many=True, help_text="用户与服务者公开资料")
    status = serializers.CharField(help_text="会话状态：OPEN、READ_ONLY 或 CLOSED")
    can_send = serializers.BooleanField(help_text="当前用户是否仍可发送消息")
    close_reason = serializers.CharField(help_text="只读或关闭原因；正常发送时为空")
    latest_sequence = serializers.IntegerField(help_text="当前最新消息序号")
    last_read_sequence = serializers.IntegerField(help_text="当前用户已读到的消息序号")
    unread_count = serializers.IntegerField(help_text="当前用户未读消息数")
    last_message = MessageResponseSerializer(allow_null=True, help_text="最近一条消息")
    version = serializers.IntegerField(help_text="会话版本号")
    created_at = serializers.DateTimeField(help_text="会话创建时间")
    updated_at = serializers.DateTimeField(help_text="会话最近更新时间")


class ConversationListResponseSerializer(serializers.Serializer):
    """订单会话游标分页响应。"""

    items = ConversationResponseSerializer(many=True, help_text="当前用户的订单会话")
    next_cursor = serializers.CharField(
        allow_null=True,
        help_text="下一页游标；首页为空",
    )
    has_more = serializers.BooleanField(help_text="是否还有更多会话")
    limit = serializers.IntegerField(help_text="本页最大数量")


class MessageListResponseSerializer(serializers.Serializer):
    """历史消息或断线补偿响应。"""

    conversation_id = serializers.UUIDField(help_text="订单会话 UUID")
    items = MessageResponseSerializer(many=True, help_text="按消息序号排列的消息")
    next_cursor = serializers.IntegerField(
        allow_null=True,
        help_text="继续读取时使用的 before_sequence 游标",
    )
    has_more = serializers.BooleanField(help_text="是否还有更多历史消息")
    latest_sequence = serializers.IntegerField(help_text="会话当前最新消息序号")
    limit = serializers.IntegerField(help_text="本页最大数量")


class MessageCreateRequestSerializer(serializers.Serializer):
    """通过 HTTP 创建文本或图片聊天消息。"""

    client_message_id = serializers.CharField(
        max_length=64,
        help_text="客户端生成的幂等标识，同一消息重试必须保持一致",
    )
    message_type = serializers.ChoiceField(
        choices=["TEXT", "IMAGE"],
        help_text="消息类型：TEXT 或 IMAGE",
    )
    content = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="文本消息内容；图片消息可填写说明",
    )
    media_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="聊天图片媒体 UUID；必须属于当前用户且用途为 CHAT_IMAGE",
    )


class MessageAckSerializer(serializers.Serializer):
    """消息发送幂等确认。"""

    client_message_id = serializers.CharField(help_text="客户端幂等标识")
    message_no = serializers.UUIDField(help_text="服务端消息 UUID")
    sequence = serializers.IntegerField(help_text="服务端分配的消息序号")
    reused = serializers.BooleanField(help_text="是否复用了此前相同幂等请求")


class MessageCreateResponseSerializer(serializers.Serializer):
    """消息创建和幂等确认响应。"""

    message = MessageResponseSerializer(help_text="已保存的聊天消息")
    ack = MessageAckSerializer(help_text="消息幂等确认和序号")


class ConversationReadRequestSerializer(serializers.Serializer):
    """标记订单会话已读。"""

    sequence = serializers.IntegerField(
        required=False,
        min_value=0,
        help_text="已读到的最大消息序号；省略时标记当前全部消息已读",
    )


class ConversationReadResponseSerializer(serializers.Serializer):
    """已读位置更新结果。"""

    conversation_id = serializers.UUIDField(help_text="订单会话 UUID")
    last_read_sequence = serializers.IntegerField(help_text="更新后的已读消息序号")
    unread_count = serializers.IntegerField(help_text="更新后的未读消息数")


class UnreadConversationSerializer(serializers.Serializer):
    """单个订单会话未读摘要。"""

    conversation_id = serializers.UUIDField(help_text="订单会话 UUID")
    unread_count = serializers.IntegerField(help_text="会话未读消息数")


class UnreadSummaryResponseSerializer(serializers.Serializer):
    """当前用户全部订单会话未读汇总。"""

    total_unread = serializers.IntegerField(help_text="全部未读消息总数")
    conversation_count = serializers.IntegerField(help_text="存在未读消息的会话数")
    items = UnreadConversationSerializer(many=True, help_text="各会话未读明细")


class WebSocketTicketResponseSerializer(serializers.Serializer):
    """WebSocket 短时效一次性连接凭证。"""

    ticket = serializers.CharField(help_text="WebSocket URL 使用的一次性随机凭证")
    expires_at = serializers.CharField(help_text="凭证过期时间，格式 YYYY-MM-DD HH:mm:ss")
    expires_in_seconds = serializers.IntegerField(help_text="凭证有效秒数")


class ConversationHideResponseSerializer(serializers.Serializer):
    """当前用户隐藏或恢复前的删除会话操作结果。"""

    conversation_id = serializers.UUIDField(help_text="被隐藏的共享会话 UUID")
    hidden_at = serializers.CharField(help_text="当前用户隐藏时间，格式 YYYY-MM-DD HH:mm:ss")
