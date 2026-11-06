from __future__ import annotations

from rest_framework import serializers

from backend.media.api.serializers import MediaAssetSummarySerializer


class FollowResponseSerializer(serializers.Serializer):
    """关注关系操作响应。"""

    is_following = serializers.BooleanField(help_text="当前是否已关注")
    followed_user_public_id = serializers.UUIDField(help_text="被关注用户 UUID")
    created_at = serializers.DateTimeField(allow_null=True, help_text="关注创建时间")


class FavoriteRequestSerializer(serializers.Serializer):
    """收藏请求。"""

    target_type = serializers.ChoiceField(
        choices=["PROVIDER", "SERVICE", "MOMENT", "NEWS"],
        help_text="收藏目标类型",
    )
    target_id = serializers.UUIDField(help_text="收藏目标公开 UUID")


class FavoriteResponseSerializer(serializers.Serializer):
    """收藏操作响应。"""

    is_favorited = serializers.BooleanField(help_text="当前是否已收藏")
    target_type = serializers.CharField(help_text="收藏目标类型")
    target_id = serializers.UUIDField(help_text="收藏目标 UUID")
    created_at = serializers.DateTimeField(allow_null=True, help_text="收藏创建时间")


class CommentRequestSerializer(serializers.Serializer):
    """动态评论请求。"""

    content = serializers.CharField(help_text="评论内容，1 到 1000 个字符")


class CommentUserSerializer(serializers.Serializer):
    """评论用户的公开资料摘要。"""

    public_id = serializers.UUIDField(help_text="评论用户公开 UUID")
    nickname = serializers.CharField(allow_null=True, help_text="评论用户昵称")
    avatar_media = MediaAssetSummarySerializer(
        allow_null=True,
        help_text="评论用户头像媒体摘要",
    )


class CommentResponseSerializer(serializers.Serializer):
    """动态评论响应。"""

    id = serializers.UUIDField(help_text="评论 UUID")
    content = serializers.CharField(help_text="评论内容")
    user_public_id = serializers.UUIDField(help_text="评论用户 UUID")
    user = CommentUserSerializer(help_text="评论用户昵称和头像安全摘要")
    moment_id = serializers.UUIDField(help_text="所属动态 UUID")
    created_at = serializers.DateTimeField(help_text="评论创建时间")


class LikeResponseSerializer(serializers.Serializer):
    """动态点赞响应。"""

    is_liked = serializers.BooleanField(help_text="当前是否已点赞")
    moment_id = serializers.UUIDField(help_text="动态 UUID")
    like_count = serializers.IntegerField(help_text="点赞总数")
