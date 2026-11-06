from __future__ import annotations

import uuid
from typing import ClassVar

from django.conf import settings
from django.db import models

from backend.content import news_models  # noqa: F401


class MomentTag(models.Model):
    """动态标签配置表。"""

    id = models.BigAutoField(primary_key=True, db_comment="动态标签自增主键")
    code = models.CharField(max_length=32, unique=True, db_comment="动态标签稳定代码")
    name = models.CharField(max_length=50, db_comment="动态标签展示名称")
    category = models.CharField(max_length=32, db_comment="动态标签分类名称")
    sort_order = models.PositiveIntegerField(default=0, db_comment="标签展示排序值")
    is_active = models.BooleanField(default=True, db_comment="标签是否允许选择")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="标签创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="标签最近更新时间")

    class Meta:
        db_table = "moment_tags"
        db_table_comment = "动态标签配置表"
        ordering: ClassVar[list[str]] = ["sort_order", "id"]


class MomentCategory(models.Model):
    """动态内容类目配置表。"""

    id = models.BigAutoField(primary_key=True, db_comment="动态类目自增主键")
    code = models.CharField(max_length=32, unique=True, db_comment="动态类目稳定代码")
    name = models.CharField(max_length=50, db_comment="动态类目展示名称")
    sort_order = models.PositiveIntegerField(default=0, db_comment="类目展示排序值")
    is_active = models.BooleanField(default=True, db_comment="类目是否允许选择")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="类目创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="类目最近更新时间")

    class Meta:
        db_table = "moment_categories"
        db_table_comment = "动态内容类目配置表"
        ordering: ClassVar[list[str]] = ["sort_order", "id"]


class Moment(models.Model):
    """服务者图文动态主表。"""

    class Type(models.TextChoices):
        IMAGE_TEXT = "IMAGE_TEXT", "图文"
        VIDEO = "VIDEO", "视频"

    class Visibility(models.TextChoices):
        PUBLIC = "PUBLIC", "公开"
        FOLLOWERS = "FOLLOWERS", "仅粉丝"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "草稿"
        PENDING = "PENDING", "审核中"
        PUBLISHED = "PUBLISHED", "已发布"
        REJECTED = "REJECTED", "审核拒绝"
        DELETED = "DELETED", "已删除"

    id = models.BigAutoField(primary_key=True, db_comment="动态自增主键")
    public_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外动态 UUID",
    )
    provider_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="moments",
        db_comment="动态发布服务者用户",
    )
    category = models.ForeignKey(
        MomentCategory,
        to_field="code",
        db_column="category_code",
        on_delete=models.PROTECT,
        related_name="moments",
        null=True,
        blank=True,
        db_comment="动态内容类目稳定代码；旧数据可为空",
    )
    type = models.CharField(
        max_length=16,
        choices=Type.choices,
        default=Type.IMAGE_TEXT,
        db_comment="动态类型：当前支持图文，视频预留",
    )
    content = models.CharField(max_length=2000, db_comment="动态文案")
    cover_media_id = models.CharField(
        max_length=128, blank=True, default="", db_comment="动态封面媒体 UUID"
    )
    visibility = models.CharField(
        max_length=16,
        choices=Visibility.choices,
        default=Visibility.PUBLIC,
        db_comment="动态可见范围；当前实现公开动态",
    )
    allow_recommend = models.BooleanField(
        default=True,
        db_comment="是否允许平台推荐该动态",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        db_comment="动态状态：草稿、审核中、已发布、审核拒绝或已删除",
    )
    reject_reason = models.TextField(blank=True, default="", db_comment="动态审核拒绝原因")
    attached_service = models.ForeignKey(
        "catalog.ProviderService",
        to_field="public_id",
        db_column="attached_service_public_id",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="moments",
        db_comment="可选挂载服务；公开动态只能挂载服务者自己的 ONLINE 服务",
    )
    like_count = models.PositiveIntegerField(default=0, db_comment="点赞数，只读统计")
    comment_count = models.PositiveIntegerField(default=0, db_comment="评论数，只读统计")
    share_count = models.PositiveIntegerField(default=0, db_comment="分享数，只读统计")
    view_count = models.PositiveIntegerField(default=0, db_comment="浏览数，只读统计")
    version = models.PositiveIntegerField(default=1, db_comment="动态乐观锁版本号")
    idempotency_key = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        db_comment="创建动态请求幂等键，按服务者隔离",
    )
    request_fingerprint = models.CharField(max_length=64, db_comment="创建动态请求摘要")
    published_at = models.DateTimeField(null=True, blank=True, db_comment="动态公开发布时间")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="动态创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="动态最近更新时间")
    deleted_at = models.DateTimeField(null=True, blank=True, db_comment="动态逻辑删除时间")

    class Meta:
        db_table = "moments"
        db_table_comment = "服务者动态主表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["provider_user", "idempotency_key"],
                name="uniq_moment_user_idempotency",
            )
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["status", "published_at"]),
            models.Index(fields=["provider_user", "status", "updated_at"]),
        ]

    def __str__(self) -> str:
        return f"Moment({self.public_id})"


class MomentMedia(models.Model):
    """动态图片/视频有序关联表。"""

    class MediaType(models.TextChoices):
        IMAGE = "IMAGE", "图片"
        VIDEO = "VIDEO", "视频"

    id = models.BigAutoField(primary_key=True, db_comment="动态媒体关联自增主键")
    moment = models.ForeignKey(
        Moment,
        on_delete=models.CASCADE,
        related_name="media_links",
        db_comment="所属动态",
    )
    media_id = models.CharField(max_length=128, db_comment="动态媒体 UUID")
    media_type = models.CharField(
        max_length=16,
        choices=MediaType.choices,
        default=MediaType.IMAGE,
        db_comment="媒体类型；当前实现图片",
    )
    position = models.PositiveSmallIntegerField(default=0, db_comment="媒体展示顺序")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="媒体关联创建时间")

    class Meta:
        db_table = "moment_media"
        db_table_comment = "动态媒体有序关联表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["moment", "media_id"],
                name="uniq_moment_media",
            ),
            models.UniqueConstraint(
                fields=["moment", "position"],
                name="uniq_moment_media_position",
            ),
        ]


class MomentTagLink(models.Model):
    """动态与标签有序关联表。"""

    id = models.BigAutoField(primary_key=True, db_comment="动态标签关联自增主键")
    moment = models.ForeignKey(
        Moment,
        on_delete=models.CASCADE,
        related_name="tag_links",
        db_comment="所属动态",
    )
    tag = models.ForeignKey(
        MomentTag,
        on_delete=models.PROTECT,
        related_name="moment_links",
        db_comment="被引用的动态标签",
    )
    position = models.PositiveSmallIntegerField(default=0, db_comment="标签展示顺序")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="标签关联创建时间")

    class Meta:
        db_table = "moment_tag_links"
        db_table_comment = "动态与标签关联表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["moment", "tag"],
                name="uniq_moment_tag",
            ),
            models.UniqueConstraint(
                fields=["moment", "position"],
                name="uniq_moment_tag_position",
            ),
        ]


class MomentEvent(models.Model):
    """动态状态变更和审核事件追加表。"""

    class EventType(models.TextChoices):
        CREATED = "CREATED", "创建"
        UPDATED = "UPDATED", "修改"
        SUBMITTED = "SUBMITTED", "提交审核"
        PUBLISHED = "PUBLISHED", "发布"
        APPROVED = "APPROVED", "审核通过"
        REJECTED = "REJECTED", "审核拒绝"
        DELETED = "DELETED", "删除"

    id = models.BigAutoField(primary_key=True, db_comment="动态事件自增主键")
    moment = models.ForeignKey(
        Moment,
        on_delete=models.CASCADE,
        related_name="events",
        db_comment="事件所属动态",
    )
    event_type = models.CharField(
        max_length=16, choices=EventType.choices, db_comment="动态事件类型"
    )
    from_status = models.CharField(
        max_length=16, blank=True, default="", db_comment="事件前动态状态"
    )
    to_status = models.CharField(max_length=16, db_comment="事件后动态状态")
    actor_user_id = models.BigIntegerField(null=True, blank=True, db_comment="执行事件的用户主键")
    reason = models.TextField(blank=True, default="", db_comment="事件原因")
    trace_id = models.CharField(
        max_length=64, blank=True, default="", db_comment="事件请求追踪标识"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="动态事件创建时间")

    class Meta:
        db_table = "moment_events"
        db_table_comment = "动态状态变更和审核事件追加表"
        ordering: ClassVar[list[str]] = ["created_at", "id"]
