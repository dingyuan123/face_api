"""地点快捷搜索词和公共场所过滤规则数据模型。"""

from __future__ import annotations

import uuid
from typing import ClassVar

from django.db import models


class ProviderLocationState(models.Model):
    """服务者当前定位状态表，只服务附近推荐，不保存普通用户当前位置。"""

    id = models.BigAutoField(primary_key=True, db_comment="服务者位置状态自增主键")
    user = models.OneToOneField(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="provider_location_state",
        db_comment="位置所属服务者用户，一个服务者只保留一份当前位置",
    )
    latitude_encrypted = models.TextField(
        db_comment="服务者纬度位置专用密文；保存前已按策略模糊，不保存明文",
    )
    longitude_encrypted = models.TextField(
        db_comment="服务者经度位置专用密文；保存前已按策略模糊，不保存明文",
    )
    coordinate_system = models.CharField(
        max_length=16,
        default="GCJ02",
        db_comment="服务端规范化后的坐标系，当前固定为腾讯地图 GCJ02",
    )
    accuracy_m = models.PositiveIntegerField(
        default=0,
        db_comment="客户端报告的定位精度，单位为米；仅用于新鲜度判断",
    )
    source = models.CharField(
        max_length=32,
        default="LOGIN",
        db_comment="定位更新来源，例如 LOGIN 或 PERIODIC",
    )
    privacy_version = models.CharField(
        max_length=32,
        blank=True,
        default="",
        db_comment="用户确认的定位隐私授权版本，不保存授权文本",
    )
    expires_at = models.DateTimeField(
        db_comment="当前位置有效期；过期后不得用于附近推荐",
    )
    revoked_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="用户撤销位置共享时间；非空表示当前状态不可用",
    )
    version = models.PositiveIntegerField(
        default=1,
        db_comment="位置状态乐观锁版本号，每次有效更新递增",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="位置状态首次创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="位置状态最近更新时间")

    class Meta:
        db_table = "provider_location_states"
        db_table_comment = "服务者当前定位加密状态表，不保存普通用户位置"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["expires_at", "revoked_at"], name="idx_provider_location_active"),
        ]


class LocationSearchKeyword(models.Model):
    """管理员维护的地点快捷搜索关键词配置表。"""

    id = models.BigAutoField(primary_key=True, db_comment="地点快捷关键词自增主键")
    public_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外快捷关键词 UUID，避免接口暴露自增主键",
    )
    code = models.CharField(
        max_length=64,
        unique=True,
        db_comment="快捷关键词稳定代码，前端使用该值请求对应搜索词",
    )
    label = models.CharField(max_length=50, db_comment="前端快捷入口展示名称")
    query_keyword = models.CharField(
        max_length=100,
        db_comment="提交给地图服务的实际搜索关键词",
    )
    icon = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_comment="前端图标标识或静态资源名称，不保存外部任意地址",
    )
    sort_order = models.PositiveIntegerField(
        default=0,
        db_comment="前端展示排序值，数值越小越靠前",
    )
    enabled = models.BooleanField(
        default=True,
        db_comment="是否允许前端查询和使用该快捷关键词",
    )
    version = models.PositiveIntegerField(
        default=1,
        db_comment="配置乐观锁版本号，更新时必须匹配当前值",
    )
    idempotency_key = models.CharField(
        max_length=128,
        unique=True,
        db_comment="创建请求幂等键；未提供时由服务端生成自动键",
    )
    request_fingerprint = models.CharField(
        max_length=64,
        db_comment="创建请求参数摘要，用于拒绝同键不同请求",
    )
    created_by_user_id = models.BigIntegerField(
        null=True,
        blank=True,
        db_comment="创建该配置的管理员用户主键",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="快捷关键词创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="快捷关键词最近更新时间")

    class Meta:
        db_table = "location_search_keywords"
        db_table_comment = "地点搜索快捷关键词管理员配置表"
        ordering: ClassVar[list[str]] = ["sort_order", "id"]


class LocationSearchRule(models.Model):
    """地点搜索请求词和第三方 POI 允许或拒绝规则表。"""

    class Decision(models.TextChoices):
        ALLOW = "ALLOW", "允许"
        DENY = "DENY", "拒绝"

    class MatchScope(models.TextChoices):
        ANY = "ANY", "名称、分类和地址"
        NAME = "NAME", "地点名称"
        CATEGORY = "CATEGORY", "地点分类"
        ADDRESS = "ADDRESS", "地址"

    id = models.BigAutoField(primary_key=True, db_comment="地点搜索规则自增主键")
    code = models.CharField(
        max_length=64,
        unique=True,
        db_comment="地点过滤规则稳定代码，便于迁移、审计和问题追踪",
    )
    decision = models.CharField(
        max_length=16,
        choices=Decision.choices,
        db_comment="规则命中后的处理结果：允许或拒绝",
    )
    match_scope = models.CharField(
        max_length=16,
        choices=MatchScope.choices,
        default=MatchScope.ANY,
        db_comment="规则匹配范围：地点名称、分类、地址或全部文本",
    )
    match_value = models.CharField(
        max_length=50,
        db_comment="用于包含匹配的分类或风险关键词，不保存用户搜索记录",
    )
    reason = models.CharField(
        max_length=200,
        blank=True,
        default="",
        db_comment="规则命中后的业务说明或拒绝原因",
    )
    priority = models.PositiveIntegerField(
        default=100,
        db_comment="规则优先级，数值越小越先评估",
    )
    enabled = models.BooleanField(default=True, db_comment="是否启用该过滤规则")
    version = models.PositiveIntegerField(
        default=1,
        db_comment="规则配置乐观锁版本号",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="过滤规则创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="过滤规则最近更新时间")

    class Meta:
        db_table = "location_search_rules"
        db_table_comment = "地点搜索关键词和 POI 分类允许拒绝规则表"
        ordering: ClassVar[list[str]] = ["priority", "id"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["enabled", "decision", "priority"],
                name="idx_location_rule_decision",
            ),
        ]
