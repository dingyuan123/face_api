"""邀请码、分享归因、奖励政策和奖励流水的数据模型。"""

from __future__ import annotations

import uuid
from typing import ClassVar

from django.conf import settings
from django.db import models


class ReferralInviteCode(models.Model):
    """用户专属邀请码，分享链接通过该码解析邀请人。"""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "启用"
        DISABLED = "DISABLED", "停用"

    id = models.BigAutoField(primary_key=True, db_comment="邀请码自增主键")
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="referral_invite_code",
        db_comment="邀请码所属用户",
    )
    code = models.CharField(
        max_length=16,
        unique=True,
        db_comment="对外邀请码；由服务端生成，不包含用户内部主键",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_comment="邀请码状态：启用或停用",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="邀请码生成时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="邀请码最近更新时间")

    class Meta:
        db_table = "referral_invite_codes"
        db_table_comment = "用户专属分享邀请码表"


class ReferralShareLink(models.Model):
    """邀请人按渠道和活动生成的分享链接。"""

    class Channel(models.TextChoices):
        WECHAT = "WECHAT", "微信好友"
        MOMENTS = "MOMENTS", "微信朋友圈"
        POSTER = "POSTER", "分享海报"
        SYSTEM = "SYSTEM", "系统分享"
        OTHER = "OTHER", "其他渠道"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "启用"
        REVOKED = "REVOKED", "已撤销"

    id = models.BigAutoField(primary_key=True, db_comment="分享链接自增主键")
    share_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外分享链接标识，用于访问归因",
    )
    invite_code = models.ForeignKey(
        ReferralInviteCode,
        on_delete=models.PROTECT,
        related_name="share_links",
        db_comment="分享链接使用的邀请码",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="referral_share_links",
        db_comment="分享链接所属邀请人",
    )
    channel = models.CharField(
        max_length=32,
        choices=Channel.choices,
        db_comment="分享渠道：微信、朋友圈、海报、系统分享或其他",
    )
    campaign_code = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_comment="运营活动稳定代码；可为空",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_comment="分享链接状态：启用或已撤销",
    )
    idempotency_key = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_comment="分享链接创建幂等键，按邀请人隔离",
    )
    request_fingerprint = models.CharField(
        max_length=64,
        db_comment="渠道、活动和邀请码的一致性摘要",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="分享链接创建时间")
    expires_at = models.DateTimeField(null=True, blank=True, db_comment="分享链接过期时间")

    class Meta:
        db_table = "referral_share_links"
        db_table_comment = "邀请分享链接和渠道归因表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["user", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="uniq_referral_share_user_idempotency",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["invite_code", "channel", "created_at"]),
        ]


class ReferralVisit(models.Model):
    """分享链接匿名访问记录，只保存不可逆摘要。"""

    id = models.BigAutoField(primary_key=True, db_comment="分享访问自增主键")
    visit_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外分享访问标识",
    )
    share_link = models.ForeignKey(
        ReferralShareLink,
        on_delete=models.PROTECT,
        related_name="visits",
        db_comment="被访问的分享链接",
    )
    visitor_hash = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_comment="访问者稳定标识 HMAC；不保存原始设备号",
    )
    ip_hash = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_comment="访问 IP 带密钥 HMAC；不保存明文 IP",
    )
    user_agent_hash = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_comment="User-Agent 摘要；不保存完整原始字符串",
    )
    occurred_at = models.DateTimeField(auto_now_add=True, db_comment="分享链接访问时间")
    converted_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="该访问完成新用户注册归因的时间",
    )
    converted_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="referral_conversions",
        db_comment="由该访问转化的新用户",
    )

    class Meta:
        db_table = "referral_visits"
        db_table_comment = "分享链接匿名访问和转化记录表"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["share_link", "occurred_at"]),
            models.Index(fields=["visitor_hash", "occurred_at"]),
        ]


class ReferralAttribution(models.Model):
    """新用户与唯一直接邀请人的不可覆盖归因关系。"""

    class RegistrationSource(models.TextChoices):
        PHONE = "PHONE", "手机号注册"
        WECHAT = "WECHAT", "微信注册"
        APPLE = "APPLE", "Apple 注册"

    class RiskStatus(models.TextChoices):
        CLEAR = "CLEAR", "正常"
        REVIEW = "REVIEW", "待风险复核"
        FROZEN = "FROZEN", "奖励资格冻结"

    id = models.BigAutoField(primary_key=True, db_comment="邀请归因自增主键")
    invitee_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="referral_attribution",
        db_comment="被邀请用户；一个新用户最多一个直接邀请人",
    )
    inviter_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="referral_invitees",
        db_comment="直接邀请人；仅一级关系",
    )
    invite_code = models.ForeignKey(
        ReferralInviteCode,
        on_delete=models.PROTECT,
        related_name="attributions",
        db_comment="注册时使用的邀请码",
    )
    share_link = models.ForeignKey(
        ReferralShareLink,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="attributions",
        db_comment="可识别的来源分享链接",
    )
    registration_source = models.CharField(
        max_length=16,
        choices=RegistrationSource.choices,
        db_comment="新用户注册来源",
    )
    source_channel = models.CharField(
        max_length=32,
        blank=True,
        default="",
        db_comment="来源分享渠道",
    )
    campaign_code = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_comment="来源运营活动代码",
    )
    visitor_hash = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_comment="注册来源访问者摘要；不保存原始设备标识",
    )
    ip_hash = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_comment="注册来源 IP 摘要；不保存明文 IP",
    )
    risk_status = models.CharField(
        max_length=16,
        choices=RiskStatus.choices,
        default=RiskStatus.CLEAR,
        db_comment="归因风险状态：正常、待复核或奖励资格冻结",
    )
    risk_reason = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_comment="风险标记原因，不保存完整敏感请求",
    )
    bound_at = models.DateTimeField(auto_now_add=True, db_comment="直接邀请关系绑定时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="归因记录最近更新时间")

    class Meta:
        db_table = "referral_attributions"
        db_table_comment = "新用户与直接邀请人的一级归因关系表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["invitee_user"],
                name="uniq_referral_attribution_invitee",
            ),
            models.CheckConstraint(
                condition=~models.Q(invitee_user=models.F("inviter_user")),
                name="check_referral_no_self_invite",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["inviter_user", "bound_at"]),
            models.Index(fields=["risk_status", "bound_at"]),
        ]


class ReferralPolicy(models.Model):
    """不可变推广奖励政策版本。"""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "草稿"
        ACTIVE = "ACTIVE", "生效中"
        RETIRED = "RETIRED", "已停止生效"

    id = models.BigAutoField(primary_key=True, db_comment="奖励政策自增主键")
    policy_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外奖励政策版本 UUID",
    )
    version = models.PositiveIntegerField(unique=True, db_comment="奖励政策递增版本号")
    name = models.CharField(max_length=100, db_comment="奖励政策展示名称")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        db_comment="政策状态：草稿、生效中或已停止生效",
    )
    reward_rate_bps = models.PositiveIntegerField(
        db_comment="奖励比例万分比；1000 表示十分之一，订单支付时锁定",
    )
    max_reward_amount_minor = models.BigIntegerField(
        null=True,
        blank=True,
        db_comment="单笔奖励上限，单位为分；为空表示不设上限",
    )
    min_order_amount_minor = models.BigIntegerField(
        default=0,
        db_comment="参与奖励的最低有效订单金额，单位为分",
    )
    funding_cap_to_platform_fee = models.BooleanField(
        default=True,
        db_comment="奖励是否不得超过该订单平台服务费；资金来源约束",
    )
    settlement_delay_days = models.PositiveIntegerField(
        default=7,
        db_comment="订单完成后的奖励观察和结算延迟天数",
    )
    effective_from = models.DateTimeField(db_comment="政策开始生效时间")
    effective_to = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="政策停止生效时间；为空表示未设置结束时间",
    )
    created_by_user_id = models.BigIntegerField(
        null=True,
        blank=True,
        db_comment="创建政策的管理员用户主键",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="政策版本创建时间")

    class Meta:
        db_table = "referral_policies"
        db_table_comment = "推广奖励比例和结算规则版本表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(reward_rate_bps__gte=0, reward_rate_bps__lte=10000),
                name="check_referral_policy_rate_range",
            ),
            models.CheckConstraint(
                condition=models.Q(max_reward_amount_minor__isnull=True)
                | models.Q(max_reward_amount_minor__gte=0),
                name="check_referral_policy_max_reward_non_negative",
            ),
        ]


class OrderReferralSnapshot(models.Model):
    """订单支付时锁定的邀请关系、奖励比例和计算基数。"""

    id = models.BigAutoField(primary_key=True, db_comment="订单奖励快照自增主键")
    order = models.OneToOneField(
        "orders.Order",
        on_delete=models.PROTECT,
        related_name="referral_snapshot",
        db_comment="产生推广奖励快照的订单；一个订单只允许一个快照",
    )
    attribution = models.ForeignKey(
        ReferralAttribution,
        on_delete=models.PROTECT,
        related_name="order_snapshots",
        db_comment="订单支付时有效的邀请归因",
    )
    policy = models.ForeignKey(
        ReferralPolicy,
        on_delete=models.PROTECT,
        related_name="order_snapshots",
        db_comment="订单支付时锁定的奖励政策版本",
    )
    inviter_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="referral_order_snapshots",
        db_comment="奖励归属直接邀请人",
    )
    invitee_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="referral_invited_order_snapshots",
        db_comment="产生订单的被邀请用户",
    )
    currency = models.CharField(max_length=3, default="CNY", db_comment="订单和奖励币种")
    paid_amount_minor = models.BigIntegerField(db_comment="支付成功时订单实付金额，单位为分")
    refunded_amount_minor = models.BigIntegerField(
        default=0,
        db_comment="快照最近计算时累计退款金额，单位为分",
    )
    reward_base_minor = models.BigIntegerField(
        db_comment="奖励基数：实付减累计退款，单位为分",
    )
    reward_rate_bps = models.PositiveIntegerField(db_comment="订单锁定的奖励比例万分比")
    max_reward_amount_minor = models.BigIntegerField(
        null=True,
        blank=True,
        db_comment="订单锁定的单笔奖励上限，单位为分",
    )
    expected_reward_amount_minor = models.BigIntegerField(
        db_comment="按快照计算的预期奖励金额，单位为分",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="订单奖励快照创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="退款后奖励快照最近更新时间")

    class Meta:
        db_table = "order_referral_snapshots"
        db_table_comment = "订单支付时的邀请关系和奖励比例快照表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(paid_amount_minor__gte=0),
                name="check_referral_snapshot_paid_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(reward_base_minor__gte=0),
                name="check_referral_snapshot_base_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(expected_reward_amount_minor__gte=0),
                name="check_referral_snapshot_reward_non_negative",
            ),
        ]


class ReferralReward(models.Model):
    """单笔订单的推广奖励生命周期记录。"""

    class Status(models.TextChoices):
        PENDING_SETTLEMENT = "PENDING_SETTLEMENT", "待结算"
        FROZEN = "FROZEN", "已冻结"
        SETTLED = "SETTLED", "已结算"
        CANCELED = "CANCELED", "已取消"

    id = models.BigAutoField(primary_key=True, db_comment="推广奖励自增主键")
    reward_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外推广奖励业务 UUID",
    )
    snapshot = models.OneToOneField(
        OrderReferralSnapshot,
        on_delete=models.PROTECT,
        related_name="reward",
        db_comment="奖励使用的订单支付快照",
    )
    order_no = models.CharField(max_length=64, db_comment="关联订单业务单号")
    inviter_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="referral_rewards",
        db_comment="奖励归属邀请人",
    )
    currency = models.CharField(max_length=3, default="CNY", db_comment="奖励币种")
    reward_base_minor = models.BigIntegerField(db_comment="当前有效奖励基数，单位为分")
    reward_rate_bps = models.PositiveIntegerField(db_comment="锁定奖励比例万分比")
    amount_minor = models.BigIntegerField(db_comment="当前应结算奖励金额，单位为分")
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING_SETTLEMENT,
        db_comment="奖励状态：待结算、冻结、已结算或已取消",
    )
    version = models.PositiveIntegerField(default=1, db_comment="奖励乐观锁版本号")
    settle_after = models.DateTimeField(db_comment="最早结算时间")
    settled_at = models.DateTimeField(null=True, blank=True, db_comment="推广收益入账时间")
    earning_business_no = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_comment="推广收益账户业务号；结算后记录",
    )
    cancel_reason = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_comment="取消或冻结原因",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="奖励记录创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="奖励记录最近更新时间")

    class Meta:
        db_table = "referral_rewards"
        db_table_comment = "订单推广奖励状态和金额记录表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["snapshot"],
                name="uniq_referral_reward_snapshot",
            ),
            models.CheckConstraint(
                condition=models.Q(reward_base_minor__gte=0),
                name="check_referral_reward_base_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_minor__gte=0),
                name="check_referral_reward_amount_non_negative",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["status", "settle_after"]),
            models.Index(fields=["inviter_user", "created_at"]),
        ]


class ReferralRewardAdjustment(models.Model):
    """退款、人工更正和已结算奖励追回的不可变调整记录。"""

    class Type(models.TextChoices):
        REFUND_RECALC = "REFUND_RECALC", "退款重算"
        MANUAL_CORRECTION = "MANUAL_CORRECTION", "人工更正"
        SETTLED_RECOVERY = "SETTLED_RECOVERY", "已结算追回"

    id = models.BigAutoField(primary_key=True, db_comment="奖励调整自增主键")
    adjustment_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外奖励调整业务 UUID",
    )
    reward = models.ForeignKey(
        ReferralReward,
        on_delete=models.PROTECT,
        related_name="adjustments",
        db_comment="被调整的推广奖励",
    )
    adjustment_type = models.CharField(
        max_length=32,
        choices=Type.choices,
        db_comment="调整类型：退款重算、人工更正或已结算追回",
    )
    amount_delta_minor = models.BigIntegerField(
        db_comment="奖励金额变化量，单位为分；正数增加，负数冲减",
    )
    reason = models.CharField(max_length=255, db_comment="调整原因")
    operator_user_id = models.BigIntegerField(
        null=True,
        blank=True,
        db_comment="执行人工调整的管理员用户主键",
    )
    idempotency_key = models.CharField(max_length=128, db_comment="调整请求幂等键")
    request_fingerprint = models.CharField(max_length=64, db_comment="调整请求一致性摘要")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="奖励调整记录时间")

    class Meta:
        db_table = "referral_reward_adjustments"
        db_table_comment = "推广奖励退款冲减和人工调整流水表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["reward", "idempotency_key"],
                name="uniq_referral_reward_adjustment_idempotency",
            ),
        ]


class ReferralRewardStatusLog(models.Model):
    """推广奖励状态变化和人工操作审计。"""

    id = models.BigAutoField(primary_key=True, db_comment="奖励状态日志自增主键")
    reward = models.ForeignKey(
        ReferralReward,
        on_delete=models.PROTECT,
        related_name="status_logs",
        db_comment="状态变化所属奖励",
    )
    from_status = models.CharField(max_length=32, blank=True, default="", db_comment="变化前状态")
    to_status = models.CharField(max_length=32, db_comment="变化后状态")
    reason = models.CharField(max_length=255, blank=True, default="", db_comment="状态变化原因")
    operator_user_id = models.BigIntegerField(
        null=True,
        blank=True,
        db_comment="人工操作管理员用户主键",
    )
    trace_id = models.CharField(max_length=64, blank=True, default="", db_comment="请求追踪标识")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="状态变化时间")

    class Meta:
        db_table = "referral_reward_status_logs"
        db_table_comment = "推广奖励状态和人工操作审计表"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["reward", "created_at"]),
        ]
