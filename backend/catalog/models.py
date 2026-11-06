from __future__ import annotations

import uuid
from typing import ClassVar

from django.conf import settings
from django.db import models


class ServiceCategory(models.Model):
    """服务类目配置表。"""

    id = models.BigAutoField(primary_key=True, db_comment="服务类目自增主键")
    code = models.CharField(max_length=32, unique=True, db_comment="服务类目稳定代码")
    name = models.CharField(max_length=50, db_comment="服务类目展示名称")
    sort_order = models.PositiveIntegerField(default=0, db_comment="类目展示排序值")
    is_active = models.BooleanField(default=True, db_comment="类目是否允许选择")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="类目创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="类目最近更新时间")

    class Meta:
        db_table = "service_categories"
        db_table_comment = "服务类目配置表"
        ordering: ClassVar[list[str]] = ["sort_order", "id"]


class ServiceTag(models.Model):
    """服务标签配置表。"""

    id = models.BigAutoField(primary_key=True, db_comment="服务标签自增主键")
    code = models.CharField(max_length=32, unique=True, db_comment="服务标签稳定代码")
    name = models.CharField(max_length=50, db_comment="服务标签展示名称")
    category = models.CharField(max_length=32, db_comment="服务标签分类名称")
    sort_order = models.PositiveIntegerField(default=0, db_comment="服务标签展示排序值")
    is_active = models.BooleanField(default=True, db_comment="服务标签是否允许选择")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="服务标签创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="服务标签最近更新时间")

    class Meta:
        db_table = "service_tags"
        db_table_comment = "服务标签配置表"
        ordering: ClassVar[list[str]] = ["sort_order", "id"]


class ProviderTag(models.Model):
    """服务者资料标签配置表。"""

    id = models.BigAutoField(primary_key=True, db_comment="服务者标签自增主键")
    code = models.CharField(max_length=32, unique=True, db_comment="服务者标签稳定代码")
    name = models.CharField(max_length=50, db_comment="服务者标签展示名称")
    category = models.CharField(max_length=32, db_comment="服务者标签分类名称")
    sort_order = models.PositiveIntegerField(default=0, db_comment="服务者标签展示排序值")
    is_active = models.BooleanField(default=True, db_comment="服务者标签是否允许选择")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="服务者标签创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="服务者标签最近更新时间")

    class Meta:
        db_table = "provider_tags"
        db_table_comment = "服务者资料标签配置表"
        ordering: ClassVar[list[str]] = ["sort_order", "id"]


class ProviderService(models.Model):
    """服务者创建的可售服务主表。"""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "草稿"
        PENDING = "PENDING", "审核中"
        APPROVED = "APPROVED", "审核通过"
        REJECTED = "REJECTED", "审核拒绝"
        ONLINE = "ONLINE", "已上架"
        OFFLINE = "OFFLINE", "已下架"

    id = models.BigAutoField(primary_key=True, db_comment="服务自增主键")
    public_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外服务 UUID，避免暴露自增主键",
    )
    provider_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="provider_services",
        db_comment="服务所属服务者用户；用户删除时同步删除服务",
    )
    category = models.ForeignKey(
        ServiceCategory,
        to_field="code",
        db_column="category_code",
        on_delete=models.PROTECT,
        related_name="services",
        db_comment="服务类目配置；类目被引用时禁止直接删除",
    )
    title = models.CharField(max_length=30, db_comment="服务名称，最多 30 个字符")
    currency = models.CharField(max_length=3, default="CNY", db_comment="服务价格币种代码")
    price_amount_minor = models.PositiveBigIntegerField(
        db_comment="服务每小时价格，单位为币种最小单位，CNY 为分"
    )
    duration_minutes = models.PositiveIntegerField(db_comment="服务时长，单位为分钟")
    introduction = models.TextField(db_comment="服务介绍，不能为空")
    cover_media_id = models.CharField(max_length=128, db_comment="服务封面媒体 UUID")
    location_type = models.CharField(
        max_length=32,
        default="PUBLIC_PLACE",
        db_comment="服务地点类型；当前仅支持公共场所",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        db_comment="服务状态：草稿、审核中、审核通过、审核拒绝、已上架或已下架",
    )
    reject_reason = models.TextField(blank=True, default="", db_comment="审核拒绝原因")
    reviewer_id = models.BigIntegerField(null=True, blank=True, db_comment="审核管理员用户主键")
    reviewed_at = models.DateTimeField(null=True, blank=True, db_comment="服务审核完成时间")
    sold_count = models.PositiveIntegerField(
        default=0,
        db_comment="累计已售数量；由订单完成事件维护，前端只读",
    )
    version = models.PositiveIntegerField(default=1, db_comment="服务乐观锁版本号")
    idempotency_key = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        db_comment="创建服务请求幂等键，按服务者隔离",
    )
    request_fingerprint = models.CharField(
        max_length=64,
        db_comment="创建服务请求参数摘要，用于识别同幂等键不同请求",
    )
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="服务逻辑删除时间；草稿或拒绝服务删除后保留事件记录",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="服务创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="服务最近更新时间")

    class Meta:
        db_table = "provider_services"
        db_table_comment = "服务者可售服务主表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["provider_user", "idempotency_key"],
                name="uniq_provider_service_user_idempotency",
            ),
            models.CheckConstraint(
                condition=models.Q(price_amount_minor__gt=0),
                name="check_provider_service_price_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(duration_minutes__gt=0),
                name="check_provider_service_duration_positive",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["provider_user", "status", "updated_at"]),
            models.Index(fields=["status", "updated_at"]),
        ]

    def __str__(self) -> str:
        return f"ProviderService({self.public_id})"


class ProviderServiceGalleryMedia(models.Model):
    """服务图集媒体有序关联表。"""

    id = models.BigAutoField(primary_key=True, db_comment="服务图集关联自增主键")
    service = models.ForeignKey(
        ProviderService,
        on_delete=models.CASCADE,
        related_name="gallery_links",
        db_comment="所属服务；服务删除时同步删除图集关联",
    )
    media_id = models.CharField(max_length=128, db_comment="服务图集媒体 UUID")
    position = models.PositiveSmallIntegerField(default=0, db_comment="图集展示顺序")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="图集关联创建时间")

    class Meta:
        db_table = "provider_service_media"
        db_table_comment = "服务图集媒体关联表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["service", "media_id"],
                name="uniq_provider_service_media",
            ),
            models.UniqueConstraint(
                fields=["service", "position"],
                name="uniq_provider_service_media_position",
            ),
        ]


class ProviderServiceTag(models.Model):
    """服务与服务标签有序关联表。"""

    id = models.BigAutoField(primary_key=True, db_comment="服务标签关联自增主键")
    service = models.ForeignKey(
        ProviderService,
        on_delete=models.CASCADE,
        related_name="tag_links",
        db_comment="所属服务；服务删除时同步删除标签关联",
    )
    tag = models.ForeignKey(
        ServiceTag,
        to_field="code",
        db_column="tag_code",
        on_delete=models.PROTECT,
        related_name="service_links",
        db_comment="被引用的服务标签；标签被引用时禁止直接删除",
    )
    position = models.PositiveSmallIntegerField(default=0, db_comment="服务标签展示顺序")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="服务标签关联创建时间")

    class Meta:
        db_table = "provider_service_tags"
        db_table_comment = "服务与服务标签关联表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["service", "tag"],
                name="uniq_provider_service_tag",
            ),
            models.UniqueConstraint(
                fields=["service", "position"],
                name="uniq_provider_service_tag_position",
            ),
        ]


class ProviderServiceEvent(models.Model):
    """服务状态变更和审核事件追加表。"""

    class EventType(models.TextChoices):
        CREATED = "CREATED", "创建"
        UPDATED = "UPDATED", "修改"
        SUBMITTED = "SUBMITTED", "提交审核"
        APPROVED = "APPROVED", "审核通过"
        REJECTED = "REJECTED", "审核拒绝"
        ONLINE = "ONLINE", "上架"
        OFFLINE = "OFFLINE", "下架"
        DELETED = "DELETED", "删除"

    id = models.BigAutoField(primary_key=True, db_comment="服务事件自增主键")
    service = models.ForeignKey(
        ProviderService,
        on_delete=models.CASCADE,
        related_name="events",
        db_comment="事件所属服务",
    )
    event_type = models.CharField(
        max_length=16, choices=EventType.choices, db_comment="服务事件类型"
    )
    from_status = models.CharField(
        max_length=16, blank=True, default="", db_comment="事件前服务状态"
    )
    to_status = models.CharField(max_length=16, db_comment="事件后服务状态")
    actor_user_id = models.BigIntegerField(null=True, blank=True, db_comment="执行事件的用户主键")
    reason = models.TextField(blank=True, default="", db_comment="事件原因，例如审核拒绝原因")
    trace_id = models.CharField(
        max_length=64, blank=True, default="", db_comment="事件请求追踪标识"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="服务事件创建时间")

    class Meta:
        db_table = "provider_service_events"
        db_table_comment = "服务状态变更和审核事件追加表"
        ordering: ClassVar[list[str]] = ["created_at", "id"]
