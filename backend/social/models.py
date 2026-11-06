from __future__ import annotations

import uuid
from typing import ClassVar

from django.conf import settings
from django.db import models


class UserFollow(models.Model):
    """用户关注关系。"""

    id = models.BigAutoField(primary_key=True, db_comment="关注关系自增主键")
    follower = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="following",
        db_comment="发起关注的用户",
    )
    followed = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="followers",
        db_comment="被关注的服务者用户",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="关注创建时间")

    class Meta:
        db_table = "user_follows"
        db_table_comment = "用户关注关系表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["follower", "followed"],
                name="uniq_user_follow_relation",
            ),
            models.CheckConstraint(
                condition=~models.Q(follower=models.F("followed")),
                name="check_user_follow_not_self",
            ),
        ]


class Favorite(models.Model):
    """用户收藏关系，支持服务者、服务、动态和资讯。"""

    class TargetType(models.TextChoices):
        PROVIDER = "PROVIDER", "服务者"
        SERVICE = "SERVICE", "服务"
        MOMENT = "MOMENT", "动态"
        NEWS = "NEWS", "资讯"

    id = models.BigAutoField(primary_key=True, db_comment="收藏关系自增主键")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="favorites",
        db_comment="收藏者用户",
    )
    target_type = models.CharField(
        max_length=16,
        choices=TargetType.choices,
        db_comment="收藏目标类型",
    )
    target_id = models.UUIDField(db_comment="收藏目标公开 UUID")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="收藏创建时间")

    class Meta:
        db_table = "user_favorites"
        db_table_comment = "用户收藏关系表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["user", "target_type", "target_id"],
                name="uniq_user_favorite_target",
            )
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["user", "target_type", "created_at"]),
        ]


class MomentLike(models.Model):
    """动态点赞关系。"""

    id = models.BigAutoField(primary_key=True, db_comment="点赞关系自增主键")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="moment_likes",
        db_comment="点赞用户",
    )
    moment = models.ForeignKey(
        "content.Moment",
        on_delete=models.CASCADE,
        related_name="likes",
        db_comment="被点赞动态",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="点赞创建时间")

    class Meta:
        db_table = "moment_likes"
        db_table_comment = "动态点赞关系表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["user", "moment"],
                name="uniq_moment_like_relation",
            )
        ]


class Comment(models.Model):
    """动态评论，第一阶段支持一级评论。"""

    class Status(models.TextChoices):
        VISIBLE = "VISIBLE", "可见"
        DELETED = "DELETED", "已删除"

    id = models.BigAutoField(primary_key=True, db_comment="评论自增主键")
    public_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外评论 UUID",
    )
    moment = models.ForeignKey(
        "content.Moment",
        on_delete=models.CASCADE,
        related_name="comments",
        db_comment="评论所属动态",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="moment_comments",
        db_comment="评论发布者",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="replies",
        db_comment="父评论；第一阶段只支持一级评论",
    )
    content = models.CharField(max_length=1000, db_comment="评论内容")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.VISIBLE,
        db_comment="评论状态",
    )
    version = models.PositiveIntegerField(default=1, db_comment="评论乐观锁版本号")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="评论创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="评论最近更新时间")
    deleted_at = models.DateTimeField(null=True, blank=True, db_comment="评论逻辑删除时间")

    class Meta:
        db_table = "moment_comments"
        db_table_comment = "动态评论表"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["moment", "created_at"]),
        ]


class CommentEvent(models.Model):
    """评论状态变更追加事件。"""

    class EventType(models.TextChoices):
        CREATED = "CREATED", "创建"
        DELETED = "DELETED", "删除"

    id = models.BigAutoField(primary_key=True, db_comment="评论事件自增主键")
    comment = models.ForeignKey(
        Comment,
        on_delete=models.CASCADE,
        related_name="events",
        db_comment="事件所属评论",
    )
    event_type = models.CharField(
        max_length=16, choices=EventType.choices, db_comment="评论事件类型"
    )
    actor_user_id = models.BigIntegerField(db_comment="执行事件的用户主键")
    trace_id = models.CharField(
        max_length=64, blank=True, default="", db_comment="事件请求追踪标识"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="评论事件创建时间")

    class Meta:
        db_table = "moment_comment_events"
        db_table_comment = "评论状态变更事件表"
