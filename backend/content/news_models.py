"""资讯分类、来源、文章、挂载卡片、审计和外部同步数据模型。"""

from __future__ import annotations

import uuid
from typing import ClassVar

from django.db import models


class NewsCategory(models.Model):
    """资讯内容类目配置表。"""

    id = models.BigAutoField(primary_key=True, db_comment="资讯类目自增主键")
    code = models.CharField(max_length=32, unique=True, db_comment="资讯类目稳定代码")
    name = models.CharField(max_length=50, db_comment="资讯类目展示名称")
    sort_order = models.PositiveIntegerField(default=0, db_comment="类目展示排序值")
    is_active = models.BooleanField(default=True, db_comment="类目是否允许关联和展示")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="类目创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="类目最近更新时间")

    class Meta:
        db_table = "news_categories"
        db_table_comment = "资讯内容类目配置表"
        ordering: ClassVar[list[str]] = ["sort_order", "id"]


class NewsSource(models.Model):
    """外部资讯来源配置和最近同步状态表。"""

    class SourceType(models.TextChoices):
        RSS = "RSS", "RSS 或 Atom"
        API = "API", "第三方接口"
        MANUAL = "MANUAL", "人工录入"

    id = models.BigAutoField(primary_key=True, db_comment="资讯来源自增主键")
    code = models.CharField(max_length=64, unique=True, db_comment="资讯来源稳定代码")
    name = models.CharField(max_length=100, db_comment="资讯来源展示名称")
    source_type = models.CharField(
        max_length=16,
        choices=SourceType.choices,
        default=SourceType.RSS,
        db_comment="来源接入类型",
    )
    feed_url = models.URLField(
        max_length=1000,
        blank=True,
        default="",
        db_comment="RSS 或 Atom 订阅地址；仅允许安全 HTTP 或 HTTPS 地址",
    )
    homepage_url = models.URLField(
        max_length=1000,
        blank=True,
        default="",
        db_comment="来源官网地址；仅用于来源署名和跳转",
    )
    country_code = models.CharField(
        max_length=8,
        blank=True,
        default="",
        db_comment="来源主要国家或地区代码，例如 CN、US",
    )
    language_code = models.CharField(
        max_length=16,
        blank=True,
        default="",
        db_comment="来源主要语言代码，例如 zh-CN、en",
    )
    enabled = models.BooleanField(default=True, db_comment="是否允许自动同步该来源")
    fetch_interval_minutes = models.PositiveIntegerField(
        default=60,
        db_comment="自动同步建议间隔，单位为分钟；实际频率仍受来源条款限制",
    )
    attribution = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_comment="来源署名文案，公开资讯必须展示",
    )
    license_note = models.TextField(
        blank=True,
        default="",
        db_comment="来源版权和使用限制说明；不代表已取得全文转载授权",
    )
    last_synced_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="该来源最近一次成功同步完成时间",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="来源创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="来源最近更新时间")

    class Meta:
        db_table = "news_sources"
        db_table_comment = "外部资讯来源配置表"
        ordering: ClassVar[list[str]] = ["name", "id"]


class NewsArticle(models.Model):
    """资讯文章主表，支持管理员发布和外部资讯摘要同步。"""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "草稿"
        PENDING = "PENDING", "待审核"
        PUBLISHED = "PUBLISHED", "已发布"
        REJECTED = "REJECTED", "审核拒绝"
        DELETED = "DELETED", "已删除"

    id = models.BigAutoField(primary_key=True, db_comment="资讯文章自增主键")
    public_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外资讯 UUID；分享链接只使用该值",
    )
    source = models.ForeignKey(
        NewsSource,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="articles",
        db_comment="外部资讯来源；管理员原创资讯可为空",
    )
    external_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_comment="来源系统中的文章标识，用于同步去重",
    )
    source_url = models.URLField(
        max_length=1000,
        blank=True,
        default="",
        db_comment="外部原文链接；仅允许安全 HTTP 或 HTTPS 地址",
    )
    canonical_url = models.URLField(
        max_length=1000,
        blank=True,
        default="",
        db_comment="规范化原文链接；用于相同文章去重",
    )
    source_unique_key = models.CharField(
        max_length=255,
        unique=True,
        db_comment="来源、外部标识或规范链接生成的唯一去重键",
    )
    title = models.CharField(max_length=200, db_comment="资讯标题")
    summary = models.TextField(db_comment="资讯摘要；外部资讯不默认保存完整正文")
    body = models.TextField(
        blank=True,
        default="",
        db_comment="资讯正文；仅在确认版权或管理员原创时保存",
    )
    cover_url = models.URLField(
        max_length=1000,
        blank=True,
        default="",
        db_comment="外部封面图片安全 URL；当前只保存地址不主动下载",
    )
    cover_media_id = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_comment="管理员上传的资讯封面媒体 UUID",
    )
    author = models.CharField(
        max_length=100,
        blank=True,
        default="",
        db_comment="文章作者署名",
    )
    source_name = models.CharField(
        max_length=100,
        blank=True,
        default="",
        db_comment="公开展示的来源名称",
    )
    country_code = models.CharField(
        max_length=8,
        blank=True,
        default="",
        db_comment="资讯主要国家或地区代码",
    )
    city_code = models.CharField(
        max_length=32,
        blank=True,
        default="",
        db_comment="资讯关联城市代码；当前预留，不作为完整地点系统",
    )
    language_code = models.CharField(
        max_length=16,
        blank=True,
        default="",
        db_comment="资讯内容语言代码",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        db_comment="资讯状态：草稿、待审核、已发布、审核拒绝或已删除",
    )
    reject_reason = models.TextField(
        blank=True,
        default="",
        db_comment="管理员审核拒绝原因",
    )
    is_featured = models.BooleanField(default=False, db_comment="是否作为重点资讯展示")
    allow_recommend = models.BooleanField(
        default=True,
        db_comment="是否允许平台推荐该资讯；当前不决定推荐算法",
    )
    view_count = models.PositiveIntegerField(default=0, db_comment="资讯浏览次数，只读统计")
    version = models.PositiveIntegerField(default=1, db_comment="资讯乐观锁版本号")
    idempotency_key = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        db_comment="管理员创建资讯幂等键；同一管理员和幂等键只允许一条记录",
    )
    request_fingerprint = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_comment="创建请求一致性摘要；幂等重放必须与首次请求相同",
    )
    source_published_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="外部来源声明的原文发布时间",
    )
    published_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="平台审核通过并对外可见的发布时间",
    )
    created_by_user_id = models.BigIntegerField(
        null=True,
        blank=True,
        db_comment="创建资讯的后台用户 ID；同步任务无操作者时为空",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="资讯创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="资讯最近更新时间")
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="资讯逻辑删除时间；审计和历史引用不物理删除",
    )

    class Meta:
        db_table = "news_articles"
        db_table_comment = "资讯文章主表"
        ordering: ClassVar[list[str]] = ["-published_at", "-id"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["status", "published_at"]),
            models.Index(fields=["country_code", "language_code", "published_at"]),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["created_by_user_id", "idempotency_key"],
                name="uniq_news_article_creator_idempotency",
            ),
        ]


class NewsArticleCategory(models.Model):
    """资讯与类目多对多有序关联表。"""

    id = models.BigAutoField(primary_key=True, db_comment="资讯类目关联自增主键")
    article = models.ForeignKey(
        NewsArticle,
        on_delete=models.CASCADE,
        related_name="category_links",
        db_comment="关联资讯文章",
    )
    category = models.ForeignKey(
        NewsCategory,
        to_field="code",
        db_column="category_code",
        on_delete=models.PROTECT,
        related_name="article_links",
        db_comment="关联资讯类目稳定代码",
    )
    position = models.PositiveIntegerField(default=0, db_comment="同一资讯内类目展示顺序")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="关联创建时间")

    class Meta:
        db_table = "news_article_categories"
        db_table_comment = "资讯与类目有序关联表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["article", "category"],
                name="uniq_news_article_category",
            ),
            models.UniqueConstraint(
                fields=["article", "position"],
                name="uniq_news_article_category_position",
            ),
        ]


class NewsArticleAttachment(models.Model):
    """资讯图片、视频或附加链接快照表。"""

    class Type(models.TextChoices):
        IMAGE = "IMAGE", "图片"
        VIDEO = "VIDEO", "视频"
        LINK = "LINK", "链接"

    id = models.BigAutoField(primary_key=True, db_comment="资讯附件自增主键")
    article = models.ForeignKey(
        NewsArticle,
        on_delete=models.CASCADE,
        related_name="attachments",
        db_comment="附件所属资讯文章",
    )
    type = models.CharField(max_length=16, choices=Type.choices, db_comment="附件类型")
    media_id = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_comment="平台媒体 UUID；外部图片或链接附件可为空",
    )
    url = models.URLField(
        max_length=1000,
        blank=True,
        default="",
        db_comment="外部附件安全 URL；禁止 javascript 等危险协议",
    )
    title = models.CharField(
        max_length=200,
        blank=True,
        default="",
        db_comment="附件展示标题",
    )
    position = models.PositiveIntegerField(default=0, db_comment="附件展示顺序")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="附件创建时间")

    class Meta:
        db_table = "news_article_attachments"
        db_table_comment = "资讯附件快照表"
        ordering: ClassVar[list[str]] = ["position", "id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["article", "position"],
                name="uniq_news_article_attachment_position",
            ),
        ]


class NewsArticleMount(models.Model):
    """资讯关联服务者、服务、商家展示卡片或外部链接快照表。"""

    class MountType(models.TextChoices):
        PROVIDER = "PROVIDER", "服务者卡片"
        SERVICE = "SERVICE", "服务卡片"
        MERCHANT = "MERCHANT", "商家展示卡片"
        LINK = "LINK", "外部链接卡片"

    id = models.BigAutoField(primary_key=True, db_comment="资讯挂载卡片自增主键")
    article = models.ForeignKey(
        NewsArticle,
        on_delete=models.CASCADE,
        related_name="mounts",
        db_comment="挂载卡片所属资讯文章",
    )
    mount_type = models.CharField(
        max_length=16,
        choices=MountType.choices,
        db_comment="挂载卡片类型",
    )
    target_public_id = models.UUIDField(
        null=True,
        blank=True,
        db_comment="服务者或服务公开 UUID；商家和纯链接卡片可为空",
    )
    title = models.CharField(max_length=200, db_comment="卡片标题")
    subtitle = models.CharField(
        max_length=300,
        blank=True,
        default="",
        db_comment="卡片副标题或摘要",
    )
    cover_media_id = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_comment="卡片平台封面媒体 UUID",
    )
    cover_url = models.URLField(
        max_length=1000,
        blank=True,
        default="",
        db_comment="卡片外部封面安全 URL",
    )
    external_url = models.URLField(
        max_length=1000,
        blank=True,
        default="",
        db_comment="卡片跳转安全 URL；不携带登录令牌",
    )
    merchant_name = models.CharField(
        max_length=100,
        blank=True,
        default="",
        db_comment="商家展示名称；本期仅保存展示快照",
    )
    merchant_address = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_comment="商家展示地址；本期不建立完整地点检索",
    )
    merchant_city_code = models.CharField(
        max_length=32,
        blank=True,
        default="",
        db_comment="商家展示城市代码，预留未来地点选择",
    )
    payload_snapshot = models.JSONField(
        default=dict,
        db_comment="卡片创建时展示数据快照；目标下架后仍可保留安全展示内容",
    )
    position = models.PositiveIntegerField(default=0, db_comment="同一资讯内卡片展示顺序")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="挂载卡片创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="挂载卡片最近更新时间")

    class Meta:
        db_table = "news_article_mounts"
        db_table_comment = "资讯关联展示卡片快照表"
        ordering: ClassVar[list[str]] = ["position", "id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["article", "position"],
                name="uniq_news_article_mount_position",
            ),
        ]


class NewsArticleEvent(models.Model):
    """资讯创建、编辑、审核、发布、下架和同步审计追加表。"""

    class EventType(models.TextChoices):
        CREATED = "CREATED", "创建"
        UPDATED = "UPDATED", "编辑"
        REJECTED = "REJECTED", "审核拒绝"
        PUBLISHED = "PUBLISHED", "发布"
        UNPUBLISHED = "UNPUBLISHED", "下架"
        DELETED = "DELETED", "删除"
        SYNCED = "SYNCED", "外部同步"

    id = models.BigAutoField(primary_key=True, db_comment="资讯审计事件自增主键")
    article = models.ForeignKey(
        NewsArticle,
        on_delete=models.CASCADE,
        related_name="events",
        db_comment="审计事件所属资讯文章",
    )
    event_type = models.CharField(
        max_length=16,
        choices=EventType.choices,
        db_comment="审计事件类型",
    )
    actor_user_id = models.BigIntegerField(
        null=True,
        blank=True,
        db_comment="执行操作的后台用户 ID；系统同步任务为空",
    )
    reason = models.TextField(blank=True, default="", db_comment="审核拒绝或下架原因")
    trace_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_comment="操作请求追踪标识",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="审计事件创建时间")

    class Meta:
        db_table = "news_article_events"
        db_table_comment = "资讯状态和编辑审计事件追加表"
        ordering: ClassVar[list[str]] = ["created_at", "id"]


class NewsSyncRun(models.Model):
    """外部资讯同步任务执行记录表。"""

    class Status(models.TextChoices):
        PENDING = "PENDING", "待执行"
        RUNNING = "RUNNING", "执行中"
        SUCCEEDED = "SUCCEEDED", "成功"
        PARTIAL = "PARTIAL", "部分成功"
        FAILED = "FAILED", "失败"

    id = models.BigAutoField(primary_key=True, db_comment="资讯同步记录自增主键")
    run_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="同步任务业务编号",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_comment="同步任务状态",
    )
    requested_by_user_id = models.BigIntegerField(
        null=True,
        blank=True,
        db_comment="发起同步的后台用户 ID；定时任务为空",
    )
    source_codes = models.JSONField(
        default=list,
        db_comment="本次同步的来源代码列表；空列表表示全部启用来源",
    )
    filters = models.JSONField(
        default=dict,
        db_comment="关键词、国家和语言等同步筛选条件快照",
    )
    fetched_count = models.PositiveIntegerField(default=0, db_comment="外部源返回条数")
    created_count = models.PositiveIntegerField(default=0, db_comment="新增资讯条数")
    updated_count = models.PositiveIntegerField(default=0, db_comment="更新资讯条数")
    skipped_count = models.PositiveIntegerField(default=0, db_comment="重复或无效跳过条数")
    failed_count = models.PositiveIntegerField(default=0, db_comment="处理失败条数")
    error_message = models.TextField(
        blank=True,
        default="",
        db_comment="同步错误摘要；不得记录密钥、令牌或完整响应凭据",
    )
    started_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="同步任务开始执行时间",
    )
    finished_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="同步任务结束时间",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="同步记录创建时间")

    class Meta:
        db_table = "news_sync_runs"
        db_table_comment = "外部资讯同步任务执行记录表"
        ordering: ClassVar[list[str]] = ["-created_at", "-id"]
