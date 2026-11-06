from __future__ import annotations

import uuid
from typing import ClassVar

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower


class ProviderApplication(models.Model):
    """服务陪伴者入驻申请主表。"""

    class Status(models.TextChoices):
        PENDING = "PENDING", "待审核"
        APPROVED = "APPROVED", "已通过"
        REJECTED = "REJECTED", "已拒绝"
        CANCELLED = "CANCELLED", "已取消"

    id = models.BigAutoField(primary_key=True, db_comment="服务者申请自增主键")
    application_no = models.CharField(
        max_length=32,
        unique=True,
        editable=False,
        db_comment="对外服务者申请业务编号",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="provider_applications",
        db_comment="提交申请的用户；用户删除时同步删除申请记录",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_comment="申请状态：待审核、已通过、已拒绝或已取消",
    )
    introduction = models.TextField(db_comment="服务者个人简介")
    real_name_encrypted = models.TextField(db_comment="真实姓名密文；接口和日志不得返回明文")
    id_card_encrypted = models.TextField(db_comment="身份证号密文；接口和日志不得返回明文")
    id_card_hash = models.CharField(max_length=64, db_comment="身份证号带密钥 HMAC，用于受控查重")
    avatar_media_id = models.CharField(max_length=128, db_comment="申请头像媒体 UUID")
    life_photo_media_ids = models.JSONField(
        default=list,
        db_comment="申请生活照媒体 UUID 数组，顺序为用户提交顺序",
    )
    real_name_status = models.CharField(
        max_length=16,
        default="NOT_SUBMITTED",
        db_comment="实名认证状态快照，例如 Mock 已通过或真实通过",
    )
    face_status = models.CharField(
        max_length=16,
        default="NOT_SUBMITTED",
        db_comment="人脸认证状态快照，例如 Mock 已通过或真实通过",
    )
    idempotency_key = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        db_comment="创建申请请求幂等键，按用户隔离重复提交",
    )
    request_fingerprint = models.CharField(
        max_length=64,
        db_comment="申请敏感请求参数 HMAC，用于识别同幂等键不同请求",
    )
    reject_reason = models.TextField(
        blank=True, default="", db_comment="管理员拒绝原因；通过时清空"
    )
    reviewer_id = models.BigIntegerField(
        null=True, blank=True, db_comment="执行审核的管理员用户主键"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True, db_comment="申请审核完成时间")
    submitted_at = models.DateTimeField(auto_now_add=True, db_comment="申请首次提交时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="申请记录最近更新时间")
    version = models.PositiveIntegerField(
        default=1, db_comment="乐观锁版本号，每次状态或资料变更递增"
    )

    class Meta:
        db_table = "provider_applications"
        db_table_comment = "服务陪伴者入驻申请主表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(status__in=["PENDING", "APPROVED"]),
                name="uniq_provider_active_application",
            ),
            models.UniqueConstraint(
                fields=["user", "idempotency_key"],
                name="uniq_provider_application_user_idempotency",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["status", "submitted_at"]),
        ]

    @staticmethod
    def make_application_no() -> str:
        return f"PA{uuid.uuid4().hex[:20].upper()}"

    def __str__(self) -> str:
        return f"ProviderApplication({self.application_no})"


class ProviderApplicationEvent(models.Model):
    """服务者申请状态变更和审核事件追加表。"""

    class EventType(models.TextChoices):
        SUBMITTED = "SUBMITTED", "提交"
        RESUBMITTED = "RESUBMITTED", "重新提交"
        APPROVED = "APPROVED", "审核通过"
        REJECTED = "REJECTED", "审核拒绝"

    id = models.BigAutoField(primary_key=True, db_comment="申请事件自增主键")
    application = models.ForeignKey(
        ProviderApplication,
        on_delete=models.CASCADE,
        related_name="events",
        db_comment="事件所属服务者申请；申请删除时同步删除事件",
    )
    event_type = models.CharField(
        max_length=16,
        choices=EventType.choices,
        db_comment="事件类型：提交、重新提交、审核通过或审核拒绝",
    )
    from_status = models.CharField(
        max_length=16,
        blank=True,
        default="",
        db_comment="事件发生前的申请状态；首次提交时为空",
    )
    to_status = models.CharField(max_length=16, db_comment="事件发生后的申请状态")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        db_comment="执行状态变更的用户；系统操作可为空",
    )
    reason = models.TextField(blank=True, default="", db_comment="状态变更原因，例如管理员拒绝原因")
    trace_id = models.CharField(
        max_length=64, blank=True, default="", db_comment="状态变更请求追踪标识"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="申请事件创建时间")

    class Meta:
        db_table = "provider_application_events"
        db_table_comment = "服务者申请状态变更和审核事件追加表"
        ordering: ClassVar[list[str]] = ["created_at", "id"]


class ProviderProfile(models.Model):
    """已开通服务者对外展示资料主表。"""

    id = models.BigAutoField(primary_key=True, db_comment="服务者资料自增主键")
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="provider_profile",
        db_comment="服务者资料所属用户，一个用户只有一份服务者资料",
    )
    nickname = models.CharField(
        max_length=20,
        db_comment="服务者展示昵称，1 到 20 个字符且服务者之间忽略大小写唯一",
    )
    signature = models.CharField(
        max_length=100,
        blank=True,
        default="",
        db_comment="服务者个性签名，最多 100 个字符",
    )
    introduction = models.TextField(db_comment="服务者个人介绍，20 到 200 个字符")
    avatar_media_id = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        db_comment="服务者资料头像媒体 UUID；允许复用申请头像，为空时展示最近申请头像",
    )
    version = models.PositiveIntegerField(default=1, db_comment="服务者资料乐观锁版本号")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="服务者资料创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="服务者资料最近更新时间")

    class Meta:
        db_table = "provider_profiles"
        db_table_comment = "服务者对外展示资料主表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["user"],
                name="uniq_provider_profile_user",
            ),
            models.UniqueConstraint(
                Lower("nickname"),
                name="uniq_provider_profile_nickname_ci",
            ),
        ]

    def __str__(self) -> str:
        return f"ProviderProfile({self.nickname})"


class ProviderProfileCategory(models.Model):
    """服务者资料与服务类目代码的关联表。"""

    id = models.BigAutoField(primary_key=True, db_comment="服务者类目关联自增主键")
    profile = models.ForeignKey(
        ProviderProfile,
        on_delete=models.CASCADE,
        related_name="category_links",
        db_comment="所属服务者资料",
    )
    category_code = models.CharField(max_length=32, db_comment="服务类目稳定代码")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="类目关联创建时间")

    class Meta:
        db_table = "provider_profile_categories"
        db_table_comment = "服务者资料与服务类目关联表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["profile", "category_code"],
                name="uniq_provider_profile_category",
            )
        ]


class ProviderProfileTag(models.Model):
    """服务者资料与服务者标签代码的关联表。"""

    id = models.BigAutoField(primary_key=True, db_comment="服务者标签关联自增主键")
    profile = models.ForeignKey(
        ProviderProfile,
        on_delete=models.CASCADE,
        related_name="tag_links",
        db_comment="所属服务者资料",
    )
    tag_code = models.CharField(max_length=32, db_comment="服务者标签稳定代码")
    sort_order = models.PositiveSmallIntegerField(default=0, db_comment="标签展示顺序")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="标签关联创建时间")

    class Meta:
        db_table = "provider_profile_tags"
        db_table_comment = "服务者资料与服务者标签关联表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["profile", "tag_code"],
                name="uniq_provider_profile_tag",
            )
        ]


class ProviderProfileMedia(models.Model):
    """服务者资料照片墙媒体有序关联表。"""

    id = models.BigAutoField(primary_key=True, db_comment="服务者照片关联自增主键")
    profile = models.ForeignKey(
        ProviderProfile,
        on_delete=models.CASCADE,
        related_name="photo_links",
        db_comment="所属服务者资料",
    )
    media_id = models.CharField(max_length=128, db_comment="服务者照片媒体 UUID")
    position = models.PositiveSmallIntegerField(default=0, db_comment="照片展示顺序")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="照片关联创建时间")

    class Meta:
        db_table = "provider_profile_media"
        db_table_comment = "服务者资料照片墙媒体关联表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["profile", "media_id"],
                name="uniq_provider_profile_media",
            ),
            models.UniqueConstraint(
                fields=["profile", "position"],
                name="uniq_provider_profile_media_position",
            ),
        ]
