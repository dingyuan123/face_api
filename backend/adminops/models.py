"""管理员认证、角色权限、审计日志和后台令牌数据模型。"""

from __future__ import annotations

import uuid
from typing import ClassVar

from django.conf import settings
from django.db import models


class AdminPermission(models.Model):
    """管理后台权限点配置。"""

    id = models.BigAutoField(primary_key=True, db_comment="管理员权限自增主键")
    code = models.CharField(max_length=100, unique=True, db_comment="稳定权限点代码")
    name = models.CharField(max_length=100, db_comment="权限点中文名称")
    category = models.CharField(max_length=50, db_comment="权限点分组")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="权限点创建时间")

    class Meta:
        db_table = "admin_permissions"
        db_table_comment = "管理后台权限点配置表"


class AdminRole(models.Model):
    """管理后台角色。"""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "启用"
        DISABLED = "DISABLED", "停用"

    id = models.BigAutoField(primary_key=True, db_comment="管理员角色自增主键")
    role_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外角色 UUID",
    )
    code = models.CharField(max_length=64, unique=True, db_comment="角色稳定代码")
    name = models.CharField(max_length=100, db_comment="角色名称")
    description = models.CharField(max_length=255, blank=True, default="", db_comment="角色说明")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_comment="角色状态",
    )
    version = models.PositiveIntegerField(default=1, db_comment="角色乐观锁版本号")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="角色创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="角色最近更新时间")

    class Meta:
        db_table = "admin_roles"
        db_table_comment = "管理后台角色表"


class AdminRolePermission(models.Model):
    """角色权限点关联。"""

    id = models.BigAutoField(primary_key=True, db_comment="角色权限关联自增主键")
    role = models.ForeignKey(
        AdminRole,
        on_delete=models.CASCADE,
        related_name="permission_links",
        db_comment="所属角色",
    )
    permission = models.ForeignKey(
        AdminPermission,
        on_delete=models.PROTECT,
        related_name="role_links",
        db_comment="权限点",
    )

    class Meta:
        db_table = "admin_role_permissions"
        db_table_comment = "管理后台角色权限关联表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["role", "permission"],
                name="uniq_admin_role_permission",
            )
        ]


class AdminRoleMember(models.Model):
    """管理员角色成员关系。"""

    id = models.BigAutoField(primary_key=True, db_comment="角色成员自增主键")
    role = models.ForeignKey(
        AdminRole,
        on_delete=models.CASCADE,
        related_name="members",
        db_comment="所属角色",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="admin_role_memberships",
        db_comment="管理员用户",
    )
    assigned_by = models.BigIntegerField(
        null=True, blank=True, db_comment="分配角色的管理员用户主键"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="角色分配时间")

    class Meta:
        db_table = "admin_role_members"
        db_table_comment = "管理后台角色成员表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["role", "user"],
                name="uniq_admin_role_member",
            )
        ]


class AdminAuthToken(models.Model):
    """独立管理后台访问和刷新令牌。"""

    class TokenType(models.TextChoices):
        ACCESS = "ACCESS", "访问令牌"
        REFRESH = "REFRESH", "刷新令牌"

    id = models.BigAutoField(primary_key=True, db_comment="管理员令牌自增主键")
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, db_comment="令牌业务 UUID")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="admin_tokens",
        db_comment="管理员用户",
    )
    session_id = models.UUIDField(db_comment="管理员设备会话标识")
    token_type = models.CharField(
        max_length=16,
        choices=TokenType.choices,
        db_comment="管理员令牌类型",
    )
    token_hash = models.CharField(max_length=64, unique=True, db_comment="令牌哈希，不保存明文")
    expires_at = models.DateTimeField(db_comment="管理员令牌过期时间")
    revoked_at = models.DateTimeField(null=True, blank=True, db_comment="管理员令牌撤销时间")
    last_used_at = models.DateTimeField(null=True, blank=True, db_comment="管理员令牌最近使用时间")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="管理员令牌创建时间")

    class Meta:
        db_table = "admin_auth_tokens"
        db_table_comment = "管理后台访问和刷新令牌表"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["user", "token_type", "expires_at"]),
        ]


class AdminOperationLog(models.Model):
    """管理后台写操作统一审计记录。"""

    id = models.BigAutoField(primary_key=True, db_comment="管理员审计自增主键")
    operation_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外审计业务 UUID",
    )
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="admin_operation_logs",
        db_comment="执行管理操作的管理员用户",
    )
    operator_role = models.CharField(
        max_length=100, blank=True, default="", db_comment="操作时管理员角色摘要"
    )
    action = models.CharField(max_length=100, db_comment="管理动作代码")
    target_type = models.CharField(max_length=100, db_comment="目标对象类型")
    target_id = models.CharField(max_length=128, db_comment="目标对象业务标识")
    before_state = models.JSONField(default=dict, db_comment="操作前状态摘要")
    after_state = models.JSONField(default=dict, db_comment="操作后状态摘要")
    reason = models.CharField(max_length=500, blank=True, default="", db_comment="操作原因")
    idempotency_key = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_comment="写操作幂等键",
    )
    trace_id = models.CharField(max_length=64, blank=True, default="", db_comment="请求追踪标识")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="审计记录创建时间")

    class Meta:
        db_table = "admin_operation_logs"
        db_table_comment = "管理后台写操作统一审计表"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["operator", "created_at"]),
            models.Index(fields=["target_type", "target_id", "created_at"]),
        ]


class SystemSetting(models.Model):
    """管理后台可维护的系统配置项。"""

    id = models.BigAutoField(primary_key=True, db_comment="系统配置自增主键")
    key = models.CharField(max_length=100, unique=True, db_comment="系统配置键")
    value = models.JSONField(db_comment="系统配置值")
    description = models.CharField(max_length=255, blank=True, default="", db_comment="配置说明")
    version = models.PositiveIntegerField(default=1, db_comment="配置乐观锁版本号")
    updated_by = models.BigIntegerField(null=True, blank=True, db_comment="最后修改管理员主键")
    updated_at = models.DateTimeField(auto_now=True, db_comment="配置最近修改时间")

    class Meta:
        db_table = "admin_system_settings"
        db_table_comment = "管理后台系统配置表"


class CompanyProfile(models.Model):
    """管理后台维护的平台公司简介和营业执照资料。"""

    id = models.BigAutoField(
        primary_key=True,
        db_comment="公司资料自增主键",
    )
    singleton_key = models.CharField(
        max_length=32,
        unique=True,
        default="DEFAULT",
        db_comment="公司资料单例标识；当前固定为 DEFAULT，防止误建多份平台资料",
    )
    company_name = models.CharField(
        max_length=120,
        db_comment="公司全称，用于管理后台展示和后续公开资料引用",
    )
    introduction = models.TextField(
        db_comment="公司简介正文；仅由管理后台维护，当前不自动写入法律文本",
    )
    business_license_media_id = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_comment="营业执照图片媒体 UUID；只允许引用管理端上传的营业执照媒体",
    )
    version = models.PositiveIntegerField(
        default=1,
        db_comment="公司资料乐观锁版本号；每次有效修改递增",
    )
    updated_by = models.BigIntegerField(
        null=True,
        blank=True,
        db_comment="最后维护公司资料的管理员用户主键",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_comment="公司资料创建时间",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        db_comment="公司资料最近修改时间",
    )

    class Meta:
        db_table = "admin_company_profiles"
        db_table_comment = "管理后台公司简介和营业执照资料表"

    def __str__(self) -> str:
        return f"CompanyProfile({self.company_name})"


class Announcement(models.Model):
    """平台公告配置。"""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "草稿"
        PUBLISHED = "PUBLISHED", "已发布"
        DISABLED = "DISABLED", "已停用"

    id = models.BigAutoField(primary_key=True, db_comment="公告自增主键")
    announcement_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="公告业务 UUID",
    )
    title = models.CharField(max_length=120, db_comment="公告标题")
    content = models.TextField(db_comment="公告正文")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        db_comment="公告状态",
    )
    starts_at = models.DateTimeField(null=True, blank=True, db_comment="公告开始展示时间")
    ends_at = models.DateTimeField(null=True, blank=True, db_comment="公告结束展示时间")
    version = models.PositiveIntegerField(default=1, db_comment="公告乐观锁版本号")
    created_by = models.BigIntegerField(null=True, blank=True, db_comment="创建管理员主键")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="公告创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="公告最近更新时间")

    class Meta:
        db_table = "admin_announcements"
        db_table_comment = "平台公告配置表"
