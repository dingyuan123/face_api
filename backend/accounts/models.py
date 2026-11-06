from __future__ import annotations

import uuid
from typing import ClassVar

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    """负责创建自定义用户，并强制手机号摘要必填。"""

    use_in_migrations = True

    def create_user(self, phone_hash: str, phone_masked: str, **extra_fields):
        """创建用户；调用方必须提供手机号摘要和脱敏手机号。"""

        if not phone_hash:
            raise ValueError("phone_hash is required")
        return self.create(
            phone_hash=phone_hash,
            phone_masked=phone_masked,
            **extra_fields,
        )


class User(AbstractBaseUser):
    """平台用户主表，保存账号状态、身份选择和工作区状态。"""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "正常"
        FROZEN = "FROZEN", "冻结"
        BANNED = "BANNED", "封禁"
        LOGOFF = "LOGOFF", "注销"

    class InitialRole(models.TextChoices):
        USER = "USER", "普通用户"
        PROVIDER = "PROVIDER", "服务陪伴者"

    class Workspace(models.TextChoices):
        USER_HOME = "USER_HOME", "普通用户首页"
        PROVIDER_ONBOARDING = "PROVIDER_ONBOARDING", "服务者入驻引导"
        PROVIDER_WORKSPACE = "PROVIDER_WORKSPACE", "服务者工作台"

    class ProviderStatus(models.TextChoices):
        NOT_SUBMITTED = "NOT_SUBMITTED", "未申请"
        PENDING = "PENDING", "待审核"
        APPROVED = "APPROVED", "已通过"
        REJECTED = "REJECTED", "已拒绝"
        SUSPENDED = "SUSPENDED", "已停用"

    id = models.BigAutoField(primary_key=True, db_comment="用户表自增主键")
    public_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外公开的用户 UUID，避免接口暴露自增主键",
    )
    password = models.CharField(
        max_length=128,
        db_comment="Django 密码哈希；当前手机号登录不使用，禁止保存明文密码",
    )
    phone_hash = models.CharField(
        max_length=64,
        unique=True,
        db_comment="手机号 HMAC 摘要，用于唯一识别手机号，不保存明文",
    )
    phone_masked = models.CharField(max_length=16, db_comment="脱敏手机号，仅用于界面展示")
    phone_encrypted = models.TextField(
        null=True,
        blank=True,
        db_comment="登录手机号 Fernet 密文，仅用于授权订单联系；不保存或记录明文",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_comment="账号状态：正常、冻结、封禁或注销",
    )
    initial_role_selected = models.BooleanField(
        default=False,
        db_comment="是否已经由用户完成首次身份选择",
    )
    primary_role = models.CharField(
        max_length=16,
        choices=InitialRole.choices,
        null=True,
        blank=True,
        db_comment="用户选择的初始身份：普通用户或服务陪伴者",
    )
    default_workspace = models.CharField(
        max_length=32,
        choices=Workspace.choices,
        null=True,
        blank=True,
        db_comment="登录后默认进入的工作区，不等同于服务者经营权限",
    )
    initial_role_selected_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="首次身份选择完成时间，UTC 时间",
    )
    provider_status = models.CharField(
        max_length=16,
        choices=ProviderStatus.choices,
        default=ProviderStatus.NOT_SUBMITTED,
        db_comment="服务者状态：未申请、待审核、已通过、已拒绝或已停用",
    )
    provider_enabled = models.BooleanField(
        default=False,
        db_comment="是否允许进入服务者工作台和执行服务者业务，由审核通过后开启",
    )
    is_staff = models.BooleanField(
        default=False,
        db_comment="最小管理端审核权限标记；正式 RBAC 接入后由管理员角色替代",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="用户记录创建时间，UTC 时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="用户记录最近更新时间，UTC 时间")
    last_login_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="业务层记录的最近成功登录时间，UTC 时间",
    )
    last_login = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="Django 用户框架的最后登录时间；与业务字段 last_login_at 分离",
    )

    objects = UserManager()

    USERNAME_FIELD = "phone_hash"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    class Meta:
        db_table = "users"
        db_table_comment = "平台用户主表"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["status", "created_at"]),
        ]

    def get_username(self) -> str:
        return self.phone_hash

    @property
    def is_active(self) -> bool:
        """返回 Django Admin 和认证组件使用的账号活动状态。"""

        return self.status == self.Status.ACTIVE

    def has_perm(self, perm: str, obj: object | None = None) -> bool:
        """开发期管理后台按 is_staff 授予查看权限。"""

        return self.is_staff

    def has_module_perms(self, app_label: str) -> bool:
        """开发期管理后台按 is_staff 授予模块查看权限。"""

        return self.is_staff

    def __str__(self) -> str:
        return f"User({self.phone_masked})"


class UserAuth(models.Model):
    """用户第三方或本地认证凭据映射表。"""

    class Type(models.TextChoices):
        PHONE = "PHONE", "手机号"
        PASSWORD = "PASSWORD", "密码"
        WECHAT = "WECHAT", "微信"
        APPLE = "APPLE", "Apple ID"

    id = models.BigAutoField(primary_key=True, db_comment="用户认证凭据自增主键")
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="auths",
        db_comment="认证凭据所属用户；用户删除时同步删除凭据映射",
    )
    auth_type = models.CharField(
        max_length=16,
        choices=Type.choices,
        db_comment="认证方式：手机号、密码、微信或 Apple ID",
    )
    auth_identifier = models.CharField(
        max_length=255,
        db_comment="认证方式内的唯一标识；手机号登录保存手机号 HMAC",
    )
    credential_hash = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_comment="认证凭据哈希；不保存密码、令牌或第三方凭证明文",
    )
    status = models.CharField(max_length=16, default="ENABLED", db_comment="认证绑定状态")
    verified_at = models.DateTimeField(default=timezone.now, db_comment="认证凭据验证通过时间")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="认证凭据创建时间")

    class Meta:
        db_table = "user_auths"
        db_table_comment = "用户认证方式和第三方账号绑定关系表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["auth_type", "auth_identifier"],
                name="uniq_user_auth_type_identifier",
            )
        ]


class VerificationSendGuard(models.Model):
    """验证码发送频率保护表。"""

    id = models.BigAutoField(primary_key=True, db_comment="验证码频率控制自增主键")
    phone_hash = models.CharField(
        max_length=64,
        unique=True,
        db_comment="手机号 HMAC 摘要；同一线索只保留一条频率控制记录",
    )
    next_allowed_at = models.DateTimeField(db_comment="下一次允许发送验证码的时间，UTC 时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="频率控制记录最近更新时间")

    class Meta:
        db_table = "verification_send_guards"
        db_table_comment = "验证码发送频率保护表"


class VerificationCode(models.Model):
    """手机号验证码验证记录表。"""

    class Purpose(models.TextChoices):
        LOGIN = "LOGIN", "登录/注册"

    id = models.BigAutoField(primary_key=True, db_comment="验证码记录自增主键")
    request_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="验证码发送请求唯一标识，用于幂等和问题追踪",
    )
    phone_hash = models.CharField(max_length=64, db_comment="手机号 HMAC 摘要，不保存明文手机号")
    phone_masked = models.CharField(max_length=16, db_comment="脱敏手机号，仅用于展示")
    code_hash = models.CharField(max_length=255, db_comment="验证码密码学哈希，不保存验证码明文")
    purpose = models.CharField(
        max_length=16,
        choices=Purpose.choices,
        default=Purpose.LOGIN,
        db_comment="验证码用途，当前仅支持登录或注册",
    )
    expires_at = models.DateTimeField(db_comment="验证码过期时间，UTC 时间")
    attempts = models.PositiveSmallIntegerField(default=0, db_comment="已尝试验证次数")
    max_attempts = models.PositiveSmallIntegerField(default=5, db_comment="允许的最大验证尝试次数")
    consumed_at = models.DateTimeField(null=True, blank=True, db_comment="验证码成功消费时间")
    idempotency_key = models.CharField(
        max_length=128,
        unique=True,
        null=True,
        blank=True,
        db_comment="发送验证码请求的幂等键；同键同请求返回同一验证码记录",
    )
    request_fingerprint = models.CharField(
        max_length=64,
        db_comment="请求参数一致性摘要，用于识别同幂等键的不同请求",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="验证码记录创建时间")

    class Meta:
        db_table = "verification_codes"
        db_table_comment = "手机号验证码验证记录表"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["phone_hash", "purpose", "created_at"]),
        ]


class LoginRequest(models.Model):
    """登录请求幂等记录表。"""

    id = models.BigAutoField(primary_key=True, db_comment="登录请求自增主键")
    idempotency_key = models.CharField(
        max_length=128,
        unique=True,
        db_comment="登录请求幂等键；未指定时由服务端生成自动键",
    )
    request_fingerprint = models.CharField(
        max_length=64,
        db_comment="登录请求参数摘要，用于拒绝同键不同请求",
    )
    phone_hash = models.CharField(max_length=64, db_comment="登录手机号 HMAC 摘要")
    phone_masked = models.CharField(max_length=16, db_comment="脱敏手机号，仅用于展示")
    session_id = models.UUIDField(default=uuid.uuid4, db_comment="本次登录设备会话标识")
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="login_requests",
        null=True,
        blank=True,
        db_comment="登录成功后关联的用户；失败或未完成时可为空",
    )
    is_new_user = models.BooleanField(
        null=True,
        blank=True,
        db_comment="本次登录是否自动创建新用户；未完成时为空",
    )
    completed_at = models.DateTimeField(null=True, blank=True, db_comment="登录请求完成时间")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="登录请求创建时间")

    class Meta:
        db_table = "auth_login_requests"
        db_table_comment = "登录请求幂等和结果记录表"


class AuthToken(models.Model):
    """不透明访问和刷新令牌记录表。"""

    class TokenType(models.TextChoices):
        ACCESS = "ACCESS", "访问令牌"
        REFRESH = "REFRESH", "刷新令牌"

    id = models.BigAutoField(primary_key=True, db_comment="认证令牌自增主键")
    public_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="令牌内部唯一标识，不直接作为完整令牌返回",
    )
    login_request = models.ForeignKey(
        LoginRequest,
        on_delete=models.CASCADE,
        related_name="tokens",
        null=True,
        blank=True,
        db_comment="签发令牌的登录请求；刷新轮换后新令牌保留同一会话",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="auth_tokens",
        db_comment="令牌所属用户；用户删除时同步删除令牌记录",
    )
    session_id = models.UUIDField(
        default=uuid.uuid4, db_comment="设备会话标识，退出时撤销同会话令牌"
    )
    token_type = models.CharField(
        max_length=16,
        choices=TokenType.choices,
        db_comment="令牌类型：访问令牌或刷新令牌",
    )
    token_hash = models.CharField(
        max_length=64, unique=True, db_comment="令牌 SHA-256 哈希，不保存明文令牌"
    )
    expires_at = models.DateTimeField(db_comment="令牌过期时间，UTC 时间")
    revoked_at = models.DateTimeField(
        null=True, blank=True, db_comment="令牌撤销时间；空值表示仍有效"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="令牌创建时间")
    last_used_at = models.DateTimeField(
        null=True, blank=True, db_comment="访问令牌最近认证使用时间"
    )

    class Meta:
        db_table = "auth_tokens"
        db_table_comment = "访问和刷新令牌哈希、会话及撤销记录表"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["session_id", "token_type"]),
            models.Index(fields=["user", "expires_at"]),
        ]
