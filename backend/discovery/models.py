"""搜索聚合、搜索热度统计与热门搜索配置数据模型。"""

from __future__ import annotations

import uuid
from typing import ClassVar

from django.db import models


class SearchQueryStat(models.Model):
    """按自然日聚合的搜索关键词次数表，不保存用户原始搜索记录。"""

    id = models.BigAutoField(primary_key=True, db_comment="搜索聚合自增主键")
    search_date = models.DateField(db_comment="搜索发生自然日，按服务端统计时区归档")
    normalized_keyword = models.CharField(
        max_length=100,
        db_comment="规范化搜索词，使用兼容分解、去首尾空白、合并连续空白和忽略大小写形式",
    )
    display_keyword = models.CharField(
        max_length=100,
        db_comment="最近一次非敏感搜索词的展示原文，不保存搜索用户身份",
    )
    search_count = models.PositiveBigIntegerField(
        default=1,
        db_comment="该自然日聚合搜索次数，每次有效公开搜索累加一次",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="聚合记录创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="聚合记录最近累加时间")

    class Meta:
        db_table = "search_query_stats"
        db_table_comment = "搜索关键词按日聚合统计表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["search_date", "normalized_keyword"],
                name="uniq_search_query_stat_date_keyword",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["search_date", "search_count"],
                name="idx_search_query_stat_hot",
            ),
        ]


class SearchTrendingKeyword(models.Model):
    """热门搜索自动排名与管理员人工控制配置表。"""

    class DisplayStatus(models.TextChoices):
        ACTIVE = "ACTIVE", "展示"
        HIDDEN = "HIDDEN", "下线"
        BLOCKED = "BLOCKED", "屏蔽"

    id = models.BigAutoField(primary_key=True, db_comment="热门搜索配置自增主键")
    public_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外热门搜索配置 UUID，避免暴露自增主键",
    )
    normalized_keyword = models.CharField(
        max_length=100,
        unique=True,
        db_comment="规范化搜索词，作为自动热度与人工配置合并的唯一业务键",
    )
    display_keyword = models.CharField(max_length=100, db_comment="热门搜索展示词")
    is_manual = models.BooleanField(
        default=False,
        db_comment="是否由管理员创建或接管为人工热门搜索词",
    )
    display_status = models.CharField(
        max_length=16,
        choices=DisplayStatus.choices,
        default=DisplayStatus.ACTIVE,
        db_comment="热门搜索展示状态：展示、下线或屏蔽",
    )
    manual_priority = models.PositiveIntegerField(
        default=0,
        db_comment="人工置顶优先级，数值越小越靠前，0 表示不人工置顶",
    )
    hot_score = models.PositiveBigIntegerField(
        default=0,
        db_comment="按当前配置公式计算的自动热度分数，仅用于排序和展示",
    )
    rank = models.PositiveIntegerField(
        default=0,
        db_comment="最近一次计算得到的热榜名次，从 1 开始",
    )
    version = models.PositiveIntegerField(default=1, db_comment="人工配置乐观锁版本号")
    created_by_user_id = models.BigIntegerField(
        null=True,
        blank=True,
        db_comment="创建或接管人工配置的管理员用户主键；自动热门词为空",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="热门搜索配置创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="热门搜索配置最近更新时间")

    class Meta:
        db_table = "search_trending_keywords"
        db_table_comment = "热门搜索自动排名与人工控制配置表"
        ordering: ClassVar[list[str]] = ["rank", "manual_priority", "id"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["display_status", "manual_priority", "hot_score"],
                name="idx_search_trending_display",
            ),
        ]
