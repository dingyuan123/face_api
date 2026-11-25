from __future__ import annotations

import uuid
from typing import ClassVar

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    """负责创建自定义用户，并强制手机号摘要必填。"""

    use_in_migrations = True

    def create_user(
        self,
        phone_hash: str | None,
        phone_masked: str = "",
        **extra_fields,
    ):
        """创建手机号用户或尚未绑定手机号的第三方登录用户。"""

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
        null=True,
        blank=True,
        db_comment=(
            "手机号 HMAC 摘要，用于唯一识别手机号，不保存明文；第三方登录且未绑定手机号时为空"
        ),
    )
    phone_masked = models.CharField(
        max_length=16,
        blank=True,
        default="",
        db_comment="脱敏手机号，仅用于界面展示；未绑定手机号时为空",
    )
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
    initial_role = models.CharField(
        max_length=16,
        choices=InitialRole.choices,
        null=True,
        blank=True,
        db_comment="用户首次选择的身份，仅用于一次性身份选择校验",
    )
    primary_role = models.CharField(
        max_length=16,
        choices=InitialRole.choices,
        null=True,
        blank=True,
        db_comment="当前主身份：普通用户或服务陪伴者，服务者审核通过后可为 PROVIDER",
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
    version = models.PositiveIntegerField(
        default=1,
        db_comment="账号管理状态乐观锁版本号；管理员封禁、解封等操作递增",
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
        db_comment=(
            "认证方式内的唯一标识；手机号登录保存手机号 HMAC，"
            "Apple 和微信登录保存服务端 HMAC，不保存第三方明文标识"
        ),
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
        PASSWORD_RESET = "PASSWORD_RESET", "密码重置"
        ACCOUNT_DELETION = "ACCOUNT_DELETION", "账号注销确认"
        PASSWORD_CHANGE = "PASSWORD_CHANGE", "设置或修改密码"
        PHONE_CHANGE_OLD = "PHONE_CHANGE_OLD", "更换手机号验证原手机号"
        PHONE_CHANGE_NEW = "PHONE_CHANGE_NEW", "更换手机号验证新手机号"

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
        db_comment="验证码用途：登录注册、密码重置或账号注销确认",
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
    phone_hash = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        db_comment="登录手机号 HMAC 摘要；第三方登录时为空",
    )
    phone_masked = models.CharField(
        max_length=16,
        blank=True,
        default="",
        db_comment="脱敏手机号，仅用于展示；第三方登录时为空",
    )
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


class PasswordLoginAttempt(models.Model):
    """账号密码登录失败次数和临时锁定状态。"""

    id = models.BigAutoField(
        primary_key=True,
        db_comment="密码登录失败记录自增主键",
    )
    phone_hash = models.CharField(
        max_length=64,
        unique=True,
        db_comment="登录手机号 HMAC 摘要，不保存明文手机号",
    )
    failed_count = models.PositiveIntegerField(
        default=0,
        db_comment="当前失败窗口内连续密码错误次数",
    )
    last_failed_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="最近一次密码错误时间",
    )
    locked_until = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="密码登录临时锁定截止时间；空值表示未锁定",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_comment="密码登录失败记录创建时间",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        db_comment="密码登录失败记录最近更新时间",
    )

    class Meta:
        db_table = "password_login_attempts"
        db_table_comment = "账号密码登录失败次数和锁定状态表"


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


class AccountDeletionRecord(models.Model):
    """账号注销结果、条件快照和清理审计记录。"""

    class Status(models.TextChoices):
        COMPLETED = "COMPLETED", "注销完成"

    id = models.BigAutoField(
        primary_key=True,
        db_comment="账号注销审计自增主键",
    )
    request_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外账号注销业务 UUID",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="deletion_records",
        db_comment="被注销用户；保留用户主键以关联依法留存的交易和安全记录",
    )
    phone_masked = models.CharField(
        max_length=16,
        blank=True,
        default="",
        db_comment="注销前脱敏手机号审计快照，不保存明文手机号",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.COMPLETED,
        db_comment="账号注销审计状态",
    )
    deletion_mode = models.CharField(
        max_length=32,
        default="USER_NORMAL",
        db_comment="注销方式：用户正常注销或管理员强制注销",
    )
    operator_user_id = models.BigIntegerField(
        null=True,
        blank=True,
        db_comment="执行强制注销或资金清空的管理员用户主键",
    )
    reason = models.CharField(
        max_length=500,
        blank=True,
        default="",
        db_comment="管理员强制注销或资金处理原因",
    )
    conditions_snapshot = models.JSONField(
        default=dict,
        db_comment="注销执行前四项条件检查结果快照",
    )
    cleanup_counts = models.JSONField(
        default=dict,
        db_comment="个人资料、登录绑定和内容清理数量快照",
    )
    cleared_amount_minor = models.BigIntegerField(
        default=0,
        db_comment="强制注销时清空的账户余额合计，单位为分",
    )
    retained_categories = models.JSONField(
        default=list,
        db_comment="依法保留或匿名化的交易、安全、聊天和审计数据类别",
    )
    verification_request_id = models.UUIDField(
        null=True,
        blank=True,
        db_comment="注销确认使用的验证码请求 UUID",
    )
    request_fingerprint = models.CharField(
        max_length=64,
        db_comment="注销请求和条件结果一致性摘要，用于重复请求去重",
    )
    trace_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_comment="注销请求追踪标识",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_comment="账号注销审计创建时间",
    )
    completed_at = models.DateTimeField(
        auto_now_add=True,
        db_comment="账号注销执行完成时间",
    )

    class Meta:
        db_table = "account_deletion_records"
        db_table_comment = "账号注销条件快照和清理审计表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["user"],
                name="uniq_account_deletion_user_completed",
            )
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["user", "created_at"]),
        ]


class AccountSecurityEvent(models.Model):
    """账号密码、手机号和会话安全操作的不可变审计事件。"""

    id = models.BigAutoField(
        primary_key=True,
        db_comment="账号安全事件自增主键",
    )
    event_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外账号安全事件 UUID",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="security_events",
        db_comment="账号安全事件所属用户",
    )
    event_type = models.CharField(
        max_length=64,
        db_comment="安全事件类型，例如密码修改或手机号更换",
    )
    status = models.CharField(
        max_length=16,
        default="SUCCESS",
        db_comment="安全事件结果：成功或失败",
    )
    old_phone_masked = models.CharField(
        max_length=16,
        blank=True,
        default="",
        db_comment="变更前手机号脱敏值，不保存明文手机号",
    )
    new_phone_masked = models.CharField(
        max_length=16,
        blank=True,
        default="",
        db_comment="变更后手机号脱敏值，不保存明文手机号",
    )
    result_code = models.CharField(
        max_length=100,
        blank=True,
        default="",
        db_comment="安全事件业务结果码；不保存密码、验证码或令牌",
    )
    request_id = models.UUIDField(
        null=True,
        blank=True,
        db_comment="验证码或换绑请求 UUID",
    )
    idempotency_key = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        db_comment="账号安全写操作幂等键",
    )
    request_fingerprint = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_comment="账号安全写操作请求一致性摘要",
    )
    trace_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_comment="账号安全请求追踪标识",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_comment="账号安全事件创建时间",
    )

    class Meta:
        db_table = "account_security_events"
        db_table_comment = "账号密码、手机号和会话安全审计表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["user", "event_type", "idempotency_key"],
                condition=models.Q(idempotency_key__isnull=False),
                name="uniq_account_security_user_event_idempotency",
            )
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["event_type", "created_at"]),
        ]


class PhoneChangeRequest(models.Model):
    """更换绑定手机号的双验证码确认请求。"""

    class Status(models.TextChoices):
        PENDING = "PENDING", "待确认"
        CONFIRMED = "CONFIRMED", "已确认"
        CANCELED = "CANCELED", "已取消"
        EXPIRED = "EXPIRED", "已过期"

    id = models.BigAutoField(
        primary_key=True,
        db_comment="手机号更换请求自增主键",
    )
    request_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外手机号更换请求 UUID",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="phone_change_requests",
        db_comment="申请更换手机号的用户",
    )
    new_phone_hash = models.CharField(
        max_length=64,
        db_comment="新手机号 HMAC 摘要，不保存明文手机号",
    )
    new_phone_masked = models.CharField(
        max_length=16,
        db_comment="新手机号脱敏展示值",
    )
    new_phone_encrypted = models.TextField(
        db_comment="新手机号 Fernet 密文；确认成功后写入用户表并清除该请求密文",
    )
    old_phone_masked = models.CharField(
        max_length=16,
        blank=True,
        default="",
        db_comment="变更前手机号脱敏审计快照",
    )
    verification_mode = models.CharField(
        max_length=32,
        default="DUAL_SMS",
        db_comment="换绑验证方式：新旧手机号双验证码或当前密码加新手机号验证码",
    )
    old_verification_request_id = models.UUIDField(
        null=True,
        blank=True,
        db_comment="原手机号验证码请求 UUID",
    )
    new_verification_request_id = models.UUIDField(
        db_comment="新手机号验证码请求 UUID",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_comment="手机号更换请求状态",
    )
    expires_at = models.DateTimeField(db_comment="双验证码确认过期时间")
    idempotency_key = models.CharField(
        max_length=128,
        db_comment="手机号更换申请幂等键",
    )
    request_fingerprint = models.CharField(
        max_length=64,
        db_comment="原手机号、新手机号和验证方式一致性摘要",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_comment="手机号更换请求创建时间",
    )
    confirmed_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="手机号更换确认完成时间",
    )

    class Meta:
        db_table = "phone_change_requests"
        db_table_comment = "更换绑定手机号双验证码确认请求表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["user", "idempotency_key"],
                name="uniq_phone_change_user_idempotency",
            ),
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(status="PENDING"),
                name="uniq_phone_change_user_pending",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["user", "status", "created_at"]),
        ]
