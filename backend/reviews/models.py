from __future__ import annotations

import uuid
from typing import ClassVar

from django.conf import settings
from django.db import models


class ReviewTag(models.Model):
    """服务评价标签配置表。"""

    id = models.BigAutoField(primary_key=True, db_comment="评价标签自增主键")
    code = models.CharField(max_length=32, unique=True, db_comment="评价标签稳定代码")
    name = models.CharField(max_length=50, db_comment="评价标签展示名称")
    category = models.CharField(max_length=32, db_comment="评价标签分类")
    sort_order = models.PositiveIntegerField(default=0, db_comment="标签展示排序值")
    is_active = models.BooleanField(default=True, db_comment="标签是否允许选择")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="标签创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="标签最近更新时间")

    class Meta:
        db_table = "review_tags"
        db_table_comment = "服务评价标签配置表"
        ordering: ClassVar[list[str]] = ["sort_order", "id"]


class Review(models.Model):
    """订单完成后的用户服务评价。"""

    class Status(models.TextChoices):
        VISIBLE = "VISIBLE", "可见"
        DELETED = "DELETED", "已删除"

    id = models.BigAutoField(primary_key=True, db_comment="评价自增主键")
    public_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外评价 UUID",
    )
    order_no = models.UUIDField(unique=True, db_comment="关联订单业务 UUID")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviews",
        db_comment="评价用户",
    )
    provider_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="received_reviews",
        db_comment="被评价服务者",
    )
    rating = models.PositiveSmallIntegerField(db_comment="评分，范围 1 到 5")
    content = models.CharField(max_length=1000, blank=True, default="", db_comment="评价文字内容")
    is_anonymous = models.BooleanField(default=False, db_comment="是否匿名展示评价")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.VISIBLE,
        db_comment="评价状态",
    )
    review_expires_at = models.DateTimeField(db_comment="评价截止时间，订单完成后 7 天")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="评价创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="评价最近更新时间")

    class Meta:
        db_table = "reviews"
        db_table_comment = "用户服务评价表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(rating__gte=1, rating__lte=5),
                name="check_review_rating_range",
            )
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["provider_user", "created_at"]),
        ]


class ReviewTagLink(models.Model):
    """评价与标签关联表。"""

    id = models.BigAutoField(primary_key=True, db_comment="评价标签关联自增主键")
    review = models.ForeignKey(
        Review,
        on_delete=models.CASCADE,
        related_name="tag_links",
        db_comment="所属评价",
    )
    tag = models.ForeignKey(
        ReviewTag,
        on_delete=models.PROTECT,
        related_name="review_links",
        db_comment="评价标签",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="评价标签关联创建时间")

    class Meta:
        db_table = "review_tag_links"
        db_table_comment = "评价与标签关联表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["review", "tag"], name="uniq_review_tag")
        ]


class ReviewReply(models.Model):
    """服务者评价回复。"""

    id = models.BigAutoField(primary_key=True, db_comment="评价回复自增主键")
    review = models.ForeignKey(
        Review,
        on_delete=models.CASCADE,
        related_name="replies",
        db_comment="所属评价",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="review_replies",
        db_comment="回复发布者",
    )
    content = models.CharField(max_length=500, db_comment="评价回复内容")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="回复创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="回复最近更新时间")

    class Meta:
        db_table = "review_replies"
        db_table_comment = "服务者评价回复表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["review"], name="uniq_review_reply_review"),
        ]


class ProviderRatingStat(models.Model):
    """服务者评分聚合表。"""

    id = models.BigAutoField(primary_key=True, db_comment="评分聚合自增主键")
    provider_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="rating_stat",
        db_comment="服务者用户",
    )
    review_count = models.PositiveIntegerField(default=0, db_comment="有效评价数量")
    rating_sum = models.PositiveIntegerField(default=0, db_comment="评分总和")
    rating_average = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=0,
        db_comment="平均评分，保留两位小数",
    )
    updated_at = models.DateTimeField(auto_now=True, db_comment="评分聚合最近更新时间")

    class Meta:
        db_table = "provider_rating_stats"
        db_table_comment = "服务者评分聚合表"
