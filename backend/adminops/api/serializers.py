"""管理后台认证、用户、服务者、审计和角色接口模型。"""

from __future__ import annotations

from rest_framework import serializers

from backend.media.api.serializers import MediaAssetSummarySerializer
from backend.orders.api.serializers import OrderResponseSerializer
from backend.payouts.api.serializers import (
    PayoutMethodResponseSerializer,
    WithdrawalResponseSerializer,
)
from backend.reviews.api.serializers import ReviewResponseSerializer
from backend.support.api.serializers import SupportTicketResponseSerializer


class AdminAmountSerializer(serializers.Serializer):
    """管理后台人民币金额摘要。"""

    currency = serializers.CharField(help_text="币种代码，当前为 CNY")
    amount_minor = serializers.IntegerField(help_text="金额，单位为分")
    amount_display = serializers.CharField(help_text="保留两位小数的金额展示值")


class AdminLoginRequestSerializer(serializers.Serializer):
    """管理后台账号密码登录请求。"""

    phone = serializers.CharField(max_length=20, help_text="管理员登录手机号")
    password = serializers.CharField(write_only=True, help_text="管理员登录密码")
    captcha_token = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="图形验证码令牌；启用验证码时必填",
    )
    captcha_answer = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="图形验证码答案；启用验证码时必填",
    )
    remember_device = serializers.BooleanField(
        required=False,
        default=False,
        help_text="是否记住设备；当前仅作为客户端偏好，不延长令牌有效期",
    )


class AdminTokenResponseSerializer(serializers.Serializer):
    """管理后台令牌和权限响应。"""

    token_type = serializers.CharField(help_text="固定为 Bearer")
    access_token = serializers.CharField(help_text="管理后台访问令牌")
    refresh_token = serializers.CharField(help_text="管理后台刷新令牌")
    expires_in = serializers.IntegerField(help_text="访问令牌剩余秒数")
    refresh_expires_in = serializers.IntegerField(help_text="刷新令牌剩余秒数")
    admin_public_id = serializers.UUIDField(help_text="管理员对外用户 UUID")
    display_name = serializers.CharField(help_text="管理员脱敏展示名称")
    roles = serializers.ListField(child=serializers.CharField(), help_text="管理员角色")
    permissions = serializers.ListField(
        child=serializers.CharField(),
        help_text="管理员权限点",
    )
    menu_version = serializers.IntegerField(help_text="菜单权限版本")


class AdminCaptchaResponseSerializer(serializers.Serializer):
    """管理员登录图形验证码挑战。"""

    captcha_token = serializers.CharField(help_text="验证码令牌")
    question = serializers.CharField(help_text="验证码问题")
    image_url = serializers.CharField(allow_null=True, help_text="预留图片地址")
    expires_in = serializers.IntegerField(help_text="有效秒数")


class AdminPasswordForgotRequestSerializer(serializers.Serializer):
    """管理员忘记密码请求。"""

    phone = serializers.CharField(max_length=20, help_text="管理员登录手机号")


class AdminPasswordForgotResponseSerializer(serializers.Serializer):
    """管理员忘记密码结果。"""

    request_id = serializers.UUIDField(help_text="短信请求标识")
    expires_in = serializers.IntegerField(help_text="验证码剩余有效秒数")
    reused = serializers.BooleanField(help_text="是否幂等重放")
    debug_code = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="开发 Mock 验证码；生产环境不返回",
    )


class AdminPasswordResetRequestSerializer(serializers.Serializer):
    """管理员密码重置请求。"""

    phone = serializers.CharField(max_length=20, help_text="管理员登录手机号")
    code = serializers.CharField(max_length=6, min_length=6, help_text="密码重置验证码")
    new_password = serializers.CharField(write_only=True, min_length=12, help_text="新密码")


class AdminPasswordResetResponseSerializer(serializers.Serializer):
    """管理员密码重置结果。"""

    password_reset = serializers.BooleanField(help_text="密码是否已重置")


class AdminRefreshRequestSerializer(serializers.Serializer):
    """管理后台令牌刷新请求。"""

    refresh_token = serializers.CharField(help_text="管理后台刷新令牌")


class AdminLogoutResponseSerializer(serializers.Serializer):
    """管理后台退出结果。"""

    logged_out = serializers.BooleanField(help_text="是否已撤销当前管理员会话")


class AdminMeResponseSerializer(serializers.Serializer):
    """当前管理员身份和权限。"""

    admin_public_id = serializers.UUIDField(help_text="管理员对外用户 UUID")
    display_name = serializers.CharField(help_text="管理员脱敏展示名称")
    roles = serializers.ListField(child=serializers.CharField(), help_text="管理员角色")
    permissions = serializers.ListField(
        child=serializers.CharField(),
        help_text="管理员权限点",
    )
    menu_version = serializers.IntegerField(help_text="菜单权限版本")


class AdminDashboardResponseSerializer(serializers.Serializer):
    """后台经营概览。"""

    user_count = serializers.IntegerField(help_text="用户总数")
    provider_count = serializers.IntegerField(help_text="已开通服务者数")
    order_count = serializers.IntegerField(help_text="订单总数")
    pending_identity_count = serializers.IntegerField(help_text="待实名审核数量")
    pending_provider_application_count = serializers.IntegerField(help_text="待服务者申请审核数量")
    pending_refund_count = serializers.IntegerField(help_text="待退款处理数量")
    pending_withdrawal_count = serializers.IntegerField(help_text="待提现审核数量")
    total_income_minor = serializers.IntegerField(help_text="已结算服务者收入合计，单位为分")


class AdminDashboardTrendItemSerializer(serializers.Serializer):
    """管理后台按日趋势。"""

    date = serializers.CharField(help_text="统计日期 YYYY-MM-DD")
    new_user_count = serializers.IntegerField(help_text="新增用户数")
    created_order_count = serializers.IntegerField(help_text="新增订单数")
    completed_order_count = serializers.IntegerField(help_text="完成订单数")
    income_minor = serializers.IntegerField(help_text="服务者结算收入，单位为分")


class AdminDashboardTrendsResponseSerializer(serializers.Serializer):
    """管理后台趋势响应。"""

    range = serializers.DictField(help_text="统计周期和时区")
    items = AdminDashboardTrendItemSerializer(many=True, help_text="每日趋势")


class AdminFinanceOverviewResponseSerializer(serializers.Serializer):
    """平台财务总览。"""

    paid_amount_minor = serializers.IntegerField(help_text="支付成功金额，单位为分")
    refunded_amount_minor = serializers.IntegerField(help_text="退款成功金额，单位为分")
    platform_commission_amount_minor = serializers.IntegerField(help_text="平台佣金合计，单位为分")
    provider_income_amount_minor = serializers.IntegerField(help_text="服务者已结算收入，单位为分")
    withdrawn_amount_minor = serializers.IntegerField(help_text="提现成功金额，单位为分")
    currency = serializers.CharField(help_text="币种")
    as_of = serializers.DateTimeField(help_text="数据截止时间")


class AdminFinanceTransactionSerializer(serializers.Serializer):
    """钱包或收益资金流水。"""

    source_type = serializers.CharField(help_text="流水来源：WALLET 或 EARNING")
    transaction_no = serializers.UUIDField(help_text="流水业务 UUID")
    user_public_id = serializers.UUIDField(help_text="用户 UUID")
    direction = serializers.CharField(help_text="资金方向")
    direction_text = serializers.CharField(help_text="资金方向中文含义")
    transaction_type = serializers.CharField(help_text="资金业务类型")
    transaction_type_text = serializers.CharField(help_text="资金业务类型中文含义")
    business_type = serializers.CharField(help_text="关联业务类型")
    business_no = serializers.CharField(help_text="关联业务单号")
    currency = serializers.CharField(help_text="币种")
    amount_minor = serializers.IntegerField(help_text="变动金额，单位为分")
    balance_after_amount_minor = serializers.IntegerField(help_text="变动后余额，单位为分")
    created_at = serializers.DateTimeField(help_text="流水创建时间")


class AdminFinanceTransactionListResponseSerializer(serializers.Serializer):
    """财务流水分页响应。"""

    items = AdminFinanceTransactionSerializer(many=True, help_text="资金流水")
    total = serializers.IntegerField(help_text="流水总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")


class AdminCommissionOverviewResponseSerializer(serializers.Serializer):
    """平台佣金统计概览。"""

    commission_type = serializers.CharField(help_text="佣金类型")
    today_minor = serializers.IntegerField(help_text="今日佣金，单位为分")
    month_minor = serializers.IntegerField(help_text="本月佣金，单位为分")
    total_minor = serializers.IntegerField(help_text="累计佣金，单位为分")
    settled_minor = serializers.IntegerField(help_text="已结算佣金，单位为分")
    pending_minor = serializers.IntegerField(help_text="待结算佣金，单位为分")
    currency = serializers.CharField(help_text="币种")
    as_of = serializers.DateTimeField(help_text="数据截止时间")


class AdminCommissionTrendItemSerializer(serializers.Serializer):
    """佣金按日趋势。"""

    date = serializers.CharField(help_text="统计日期 YYYY-MM-DD")
    commission_minor = serializers.IntegerField(help_text="当日佣金，单位为分")


class AdminCommissionTrendsResponseSerializer(serializers.Serializer):
    """佣金趋势响应。"""

    range = serializers.DictField(help_text="统计周期和时区")
    items = AdminCommissionTrendItemSerializer(many=True, help_text="每日佣金趋势")


class AdminCommissionDetailSerializer(serializers.Serializer):
    """订单佣金明细。"""

    order_no = serializers.UUIDField(help_text="订单 UUID")
    provider_public_id = serializers.UUIDField(help_text="服务者用户 UUID")
    order_amount_minor = serializers.IntegerField(help_text="订单金额，单位为分")
    commission_rate_bps = serializers.IntegerField(
        allow_null=True,
        help_text="佣金比例万分比",
    )
    commission_amount_minor = serializers.IntegerField(help_text="佣金金额，单位为分")
    settlement_status = serializers.CharField(help_text="佣金结算状态")
    created_at = serializers.DateTimeField(help_text="订单创建时间")


class AdminCommissionDetailListResponseSerializer(serializers.Serializer):
    """佣金明细分页响应。"""

    items = AdminCommissionDetailSerializer(many=True, help_text="佣金明细")
    total = serializers.IntegerField(help_text="明细总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")


class AdminFinanceReconciliationItemSerializer(serializers.Serializer):
    """财务内部对账差异项。"""

    name = serializers.CharField(help_text="对账项目")
    left_amount_minor = serializers.IntegerField(help_text="左侧金额，单位为分")
    right_amount_minor = serializers.IntegerField(help_text="右侧金额，单位为分")
    difference_amount_minor = serializers.IntegerField(help_text="差异金额，单位为分")
    status = serializers.CharField(help_text="MATCH 或 MISMATCH")


class AdminFinanceReconciliationResponseSerializer(serializers.Serializer):
    """财务对账结果。"""

    items = AdminFinanceReconciliationItemSerializer(many=True, help_text="对账项目")
    as_of = serializers.DateTimeField(help_text="对账截止时间")


class AdminAnalyticsOverviewResponseSerializer(serializers.Serializer):
    """平台数据看板概览。"""

    user_count = serializers.IntegerField(help_text="用户总数")
    provider_count = serializers.IntegerField(help_text="服务者总数")
    service_count = serializers.IntegerField(help_text="服务总数")
    order_count = serializers.IntegerField(help_text="订单总数")
    completed_order_count = serializers.IntegerField(help_text="完成订单数")
    moment_count = serializers.IntegerField(help_text="动态总数")
    news_count = serializers.IntegerField(help_text="资讯总数")
    income_minor = serializers.IntegerField(help_text="已结算收入，单位为分")
    currency = serializers.CharField(help_text="币种")
    as_of = serializers.DateTimeField(help_text="数据截止时间")


class AdminAnalyticsTrendItemSerializer(serializers.Serializer):
    """平台数据每日趋势。"""

    date = serializers.CharField(help_text="统计日期")
    new_user_count = serializers.IntegerField(help_text="新增用户数")
    created_order_count = serializers.IntegerField(help_text="创建订单数")
    completed_order_count = serializers.IntegerField(help_text="完成订单数")
    income_minor = serializers.IntegerField(help_text="收入，单位为分")


class AdminAnalyticsTrendsResponseSerializer(serializers.Serializer):
    """平台数据趋势响应。"""

    range = serializers.DictField(help_text="统计周期")
    items = AdminAnalyticsTrendItemSerializer(many=True, help_text="每日趋势")


class AdminAnalyticsBreakdownResponseSerializer(serializers.Serializer):
    """平台数据分组响应。"""

    dimension = serializers.CharField(help_text="分析维度")
    items = serializers.ListField(help_text="分组统计")


class AdminSystemSettingResponseSerializer(serializers.Serializer):
    """基础系统配置。"""

    settings = serializers.DictField(help_text="配置项和版本")
    requires_restart = serializers.BooleanField(help_text="修改后是否需要重启服务")


class AdminSystemSettingUpdateRequestSerializer(serializers.Serializer):
    """更新基础系统配置。"""

    settings = serializers.DictField(help_text="需要更新的配置键值")
    expected_versions = serializers.DictField(help_text="各配置项当前版本")


class AdminCompanyProfileResponseSerializer(serializers.Serializer):
    """管理后台公司简介和营业执照资料。"""

    company_name = serializers.CharField(help_text="公司全称")
    introduction = serializers.CharField(help_text="公司简介正文")
    business_license_media_id = serializers.CharField(
        allow_blank=True,
        help_text="营业执照媒体 UUID；未上传时为空字符串",
    )
    business_license_media = MediaAssetSummarySerializer(
        allow_null=True,
        help_text="营业执照媒体摘要和临时展示地址",
    )
    has_business_license = serializers.BooleanField(help_text="是否已上传营业执照")
    version = serializers.IntegerField(help_text="公司资料版本号；首次创建前为 0")
    updated_by_public_id = serializers.UUIDField(
        allow_null=True,
        help_text="最后维护资料的管理员用户 UUID",
    )
    created_at = serializers.DateTimeField(
        allow_null=True,
        help_text="公司资料创建时间",
    )
    updated_at = serializers.DateTimeField(
        allow_null=True,
        help_text="公司资料最近修改时间",
    )


class AdminCompanyProfileUpdateRequestSerializer(serializers.Serializer):
    """创建或更新公司简介和营业执照资料。"""

    expected_version = serializers.IntegerField(
        min_value=0,
        help_text="当前版本号；首次创建传 0，更新时必须返回并提交最新版本",
    )
    company_name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=120,
        help_text="公司全称，长度 2 到 120 个字符",
    )
    introduction = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="公司简介，长度 1 到 2000 个字符",
    )
    business_license_media_id = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=128,
        help_text="营业执照媒体 UUID；传空字符串可移除当前引用",
    )


class AdminCompanyLicenseUploadRequestSerializer(serializers.Serializer):
    """管理后台营业执照图片上传请求。"""

    file = serializers.FileField(help_text="JPEG、PNG 或 WebP 格式营业执照图片")


class PublicCompanyLicenseMediaSerializer(serializers.Serializer):
    """普通用户可见的营业执照图片展示信息。"""

    media_id = serializers.UUIDField(help_text="营业执照媒体 UUID")
    content_type = serializers.CharField(help_text="图片 MIME 类型")
    width = serializers.IntegerField(help_text="图片宽度，单位为像素")
    height = serializers.IntegerField(help_text="图片高度，单位为像素")
    display_url = serializers.CharField(help_text="可直接加载的短期签名营业执照图片地址")
    display_url_expires_at = serializers.DateTimeField(
        help_text="展示地址过期时间，过期后重新查询获取新地址"
    )


class PublicCompanyProfileResponseSerializer(serializers.Serializer):
    """普通用户可见的公司简介和营业执照响应。"""

    company_name = serializers.CharField(help_text="公司全称")
    introduction = serializers.CharField(help_text="公司简介正文")
    business_license_media = PublicCompanyLicenseMediaSerializer(
        allow_null=True,
        help_text="营业执照图片展示信息",
    )
    has_business_license = serializers.BooleanField(help_text="是否已公开营业执照")


class AdminAnnouncementRequestSerializer(serializers.Serializer):
    """创建或修改公告。"""

    title = serializers.CharField(max_length=120, help_text="公告标题")
    content = serializers.CharField(help_text="公告正文")
    status = serializers.ChoiceField(
        choices=["DRAFT", "PUBLISHED", "DISABLED"],
        required=False,
        help_text="公告状态",
    )
    starts_at = serializers.DateTimeField(required=False, allow_null=True)
    ends_at = serializers.DateTimeField(required=False, allow_null=True)
    expected_version = serializers.IntegerField(required=False, min_value=1)


class AdminAnnouncementResponseSerializer(serializers.Serializer):
    """公告响应。"""

    announcement_no = serializers.UUIDField(help_text="公告 UUID")
    title = serializers.CharField(help_text="公告标题")
    content = serializers.CharField(help_text="公告正文")
    status = serializers.CharField(help_text="公告状态")
    status_text = serializers.CharField(help_text="公告状态中文含义")
    starts_at = serializers.DateTimeField(allow_null=True)
    ends_at = serializers.DateTimeField(allow_null=True)
    version = serializers.IntegerField(help_text="公告版本号")
    created_at = serializers.DateTimeField(help_text="创建时间")
    updated_at = serializers.DateTimeField(help_text="更新时间")


class AdminAnnouncementListResponseSerializer(serializers.Serializer):
    """公告分页响应。"""

    items = AdminAnnouncementResponseSerializer(many=True, help_text="公告列表")
    total = serializers.IntegerField(help_text="公告总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")


class AdminConfigOptionRequestSerializer(serializers.Serializer):
    """创建或修改城市、服务类目配置。"""

    code = serializers.CharField(required=False, max_length=32, help_text="稳定代码")
    name = serializers.CharField(required=False, max_length=50, help_text="展示名称")
    sort_order = serializers.IntegerField(required=False, default=0, min_value=0)
    is_active = serializers.BooleanField(required=False, default=True)
    expected_version = serializers.IntegerField(required=False, min_value=1)


class AdminConfigOptionResponseSerializer(serializers.Serializer):
    """城市或服务类目配置。"""

    code = serializers.CharField(help_text="稳定代码")
    name = serializers.CharField(help_text="展示名称")
    sort_order = serializers.IntegerField(help_text="排序值")
    is_active = serializers.BooleanField(help_text="是否启用")
    version = serializers.IntegerField(help_text="版本号")


class AdminConfigOptionListResponseSerializer(serializers.Serializer):
    """配置项列表。"""

    items = AdminConfigOptionResponseSerializer(many=True, help_text="配置项")


class AdminCommissionRuleResponseSerializer(serializers.Serializer):
    """平台佣金和奖励规则。"""

    provider_commission_rate_bps = serializers.IntegerField(
        help_text="服务者佣金比例万分比",
    )
    referral_reward_rate_bps = serializers.IntegerField(
        help_text="推广奖励默认比例万分比",
    )
    versions = serializers.DictField(help_text="各配置项版本")
    requires_restart = serializers.BooleanField(help_text="是否需要重启服务")


class AdminCommissionRuleUpdateRequestSerializer(serializers.Serializer):
    """修改佣金和奖励默认规则。"""

    provider_commission_rate_bps = serializers.IntegerField(
        required=False, min_value=0, max_value=10000
    )
    referral_reward_rate_bps = serializers.IntegerField(
        required=False, min_value=0, max_value=10000
    )
    expected_versions = serializers.DictField(help_text="各配置项版本")


class AdminDashboardTodoResponseSerializer(serializers.Serializer):
    """管理后台待处理数量和预览。"""

    pending_identity_count = serializers.IntegerField(help_text="待实名审核数量")
    pending_provider_application_count = serializers.IntegerField(help_text="待服务者申请审核数量")
    pending_refund_count = serializers.IntegerField(help_text="待退款处理数量")
    pending_withdrawal_count = serializers.IntegerField(help_text="待提现审核数量")
    pending_identity_items = serializers.ListField(help_text="待实名审核预览")
    pending_provider_application_items = serializers.ListField(help_text="待服务者申请审核预览")
    pending_refund_items = serializers.ListField(help_text="待退款处理预览")
    pending_withdrawal_items = serializers.ListField(help_text="待提现审核预览")


class AdminUserResponseSerializer(serializers.Serializer):
    """管理员用户列表安全摘要和常用经营概览。"""

    user_public_id = serializers.UUIDField(help_text="用户对外 UUID")
    nickname = serializers.CharField(allow_null=True, help_text="用户昵称")
    avatar_media = MediaAssetSummarySerializer(
        allow_null=True,
        help_text="用户头像媒体摘要和临时展示地址",
    )
    phone_masked = serializers.CharField(help_text="脱敏手机号")
    status = serializers.CharField(help_text="账号状态")
    status_text = serializers.CharField(help_text="账号状态中文含义")
    is_staff = serializers.BooleanField(help_text="是否管理员")
    primary_role = serializers.CharField(allow_null=True, help_text="用户当前主身份")
    primary_role_text = serializers.CharField(
        allow_null=True,
        help_text="用户当前主身份中文含义",
    )
    initial_role_selected = serializers.BooleanField(help_text="是否已完成首次身份选择")
    default_workspace = serializers.CharField(
        allow_null=True,
        help_text="登录后默认工作区",
    )
    default_workspace_text = serializers.CharField(
        allow_null=True,
        help_text="登录后默认工作区中文含义",
    )
    provider_status = serializers.CharField(help_text="服务者状态")
    provider_status_text = serializers.CharField(help_text="服务者状态中文含义")
    provider_enabled = serializers.BooleanField(help_text="是否启用服务者经营权限")
    last_login_at = serializers.DateTimeField(
        allow_null=True,
        help_text="最近成功登录时间",
    )
    order_count = serializers.IntegerField(help_text="用户下单总数")
    completed_order_count = serializers.IntegerField(help_text="用户已完成订单数")
    provider_order_count = serializers.IntegerField(help_text="服务者接单总数")
    provider_completed_order_count = serializers.IntegerField(help_text="服务者已完成订单数")
    total_paid_amount_minor = serializers.IntegerField(help_text="用户累计支付金额，单位为分")
    provider_sales_amount_minor = serializers.IntegerField(help_text="服务者累计成交金额，单位为分")
    version = serializers.IntegerField(help_text="账号管理版本号")
    created_at = serializers.DateTimeField(help_text="账号创建时间")
    updated_at = serializers.DateTimeField(help_text="账号最近更新时间")


class AdminUserProfileSerializer(serializers.Serializer):
    """管理员查看的用户个人资料。"""

    nickname = serializers.CharField(allow_null=True, help_text="用户昵称")
    gender = serializers.CharField(allow_null=True, help_text="性别")
    age = serializers.IntegerField(allow_null=True, help_text="用户填写年龄")
    city_code = serializers.CharField(allow_null=True, help_text="城市代码")
    signature = serializers.CharField(help_text="个性签名")
    interest_codes = serializers.ListField(
        child=serializers.CharField(),
        help_text="兴趣标签代码",
    )
    trust_level_code = serializers.CharField(help_text="安心用户等级代码")
    trust_level_name = serializers.CharField(help_text="安心用户等级名称")
    avatar_media = MediaAssetSummarySerializer(
        allow_null=True,
        help_text="个人资料头像",
    )
    profile_version = serializers.IntegerField(
        allow_null=True,
        help_text="个人资料版本号",
    )
    updated_at = serializers.DateTimeField(
        allow_null=True,
        help_text="个人资料最近更新时间",
    )


class AdminUserIdentitySerializer(serializers.Serializer):
    """管理员查看的实名认证状态，不返回姓名和证件密文。"""

    verification_type = serializers.CharField(help_text="认证类型")
    status = serializers.CharField(help_text="认证状态")
    reject_reason = serializers.CharField(help_text="人工审核拒绝原因")
    has_id_card_media = serializers.BooleanField(help_text="是否已提交身份证正反面")
    submitted_at = serializers.DateTimeField(
        allow_null=True,
        help_text="认证提交时间",
    )
    verified_at = serializers.DateTimeField(
        allow_null=True,
        help_text="认证完成时间",
    )


class AdminUserProviderSerializer(serializers.Serializer):
    """管理员查看的服务者经营资料。"""

    provider_status = serializers.CharField(help_text="服务者状态")
    provider_status_text = serializers.CharField(help_text="服务者状态中文含义")
    provider_status_text = serializers.CharField(help_text="服务者状态中文含义")
    provider_enabled = serializers.BooleanField(help_text="是否启用服务者权限")
    nickname = serializers.CharField(allow_null=True, help_text="服务者昵称")
    signature = serializers.CharField(help_text="服务者签名")
    introduction = serializers.CharField(help_text="服务者个人介绍")
    avatar_media = MediaAssetSummarySerializer(
        allow_null=True,
        help_text="服务者头像",
    )
    photo_media = MediaAssetSummarySerializer(
        many=True,
        help_text="服务者照片墙",
    )
    application_no = serializers.CharField(
        allow_null=True,
        help_text="最近入驻申请编号",
    )
    application_status = serializers.CharField(
        allow_null=True,
        help_text="最近入驻申请状态",
    )
    application_status_text = serializers.CharField(
        help_text="最近入驻申请状态中文含义",
    )
    application_submitted_at = serializers.DateTimeField(
        allow_null=True,
        help_text="最近入驻申请提交时间",
    )
    rating_average = serializers.CharField(help_text="服务者平均评分")
    review_count = serializers.IntegerField(help_text="有效评价数量")
    completed_order_count = serializers.IntegerField(help_text="已完成订单数量")
    sales_amount = AdminAmountSerializer(help_text="累计成交金额")


class AdminFinanceAccountSerializer(serializers.Serializer):
    """管理后台只读资金账户摘要。"""

    account_type = serializers.CharField(help_text="账户类型")
    currency = serializers.CharField(help_text="币种")
    available = AdminAmountSerializer(help_text="当前可用金额")
    frozen = AdminAmountSerializer(help_text="当前冻结金额")
    total_income = AdminAmountSerializer(help_text="累计收入")
    total_withdrawn = AdminAmountSerializer(help_text="累计提现成功金额")
    credited = AdminAmountSerializer(help_text="累计入账金额")
    debited = AdminAmountSerializer(help_text="累计出账金额")


class AdminUserEarningSummarySerializer(serializers.Serializer):
    """用户收益和平台佣金统计。"""

    gross = AdminAmountSerializer(help_text="收益业务原始金额")
    platform_commission = AdminAmountSerializer(help_text="平台佣金累计金额")
    net_income = AdminAmountSerializer(help_text="实际收益累计金额")
    pending_settlement = AdminAmountSerializer(help_text="待结算收益金额")
    referral_reward_total = AdminAmountSerializer(help_text="推广奖励累计金额")


class AdminUserFinanceSerializer(serializers.Serializer):
    """管理员查看的用户钱包、收益和收款方式摘要。"""

    wallet = AdminFinanceAccountSerializer(help_text="钱包账户")
    provider_earning = AdminFinanceAccountSerializer(help_text="服务者收入账户")
    referral_earning = AdminFinanceAccountSerializer(help_text="推广收益账户")
    withdrawal_pending = AdminAmountSerializer(help_text="处理中提现申请金额")
    payout_methods = PayoutMethodResponseSerializer(
        many=True,
        help_text="脱敏收款方式",
    )
    earning_summary = AdminUserEarningSummarySerializer(help_text="收益汇总")


class AdminUserOrderSummarySerializer(serializers.Serializer):
    """管理员查看的用户订单数量和金额概览。"""

    customer_total = serializers.IntegerField(help_text="作为用户的订单总数")
    customer_completed = serializers.IntegerField(help_text="作为用户的已完成订单数")
    customer_canceled = serializers.IntegerField(help_text="作为用户的已取消订单数")
    customer_refunded = serializers.IntegerField(help_text="作为用户的已退款订单数")
    customer_paid_amount = AdminAmountSerializer(help_text="作为用户的累计支付金额")
    customer_refunded_amount = AdminAmountSerializer(help_text="作为用户的累计退款金额")
    provider_total = serializers.IntegerField(help_text="作为服务者的订单总数")
    provider_completed = serializers.IntegerField(help_text="作为服务者的已完成订单数")
    provider_canceled = serializers.IntegerField(help_text="作为服务者的已取消订单数")
    provider_paid_amount = AdminAmountSerializer(help_text="作为服务者的累计成交金额")
    latest_at = serializers.DateTimeField(
        allow_null=True,
        help_text="最近一笔下单时间",
    )


class AdminUserSocialSerializer(serializers.Serializer):
    """用户评价和客服互动概览。"""

    review_given_count = serializers.IntegerField(help_text="发表评价数量")
    review_received_count = serializers.IntegerField(help_text="收到评价数量")
    support_ticket_count = serializers.IntegerField(help_text="客服工单总数")
    open_support_ticket_count = serializers.IntegerField(help_text="未完结工单数量")


class AdminUserSecuritySerializer(serializers.Serializer):
    """用户账号安全摘要，不返回令牌和认证凭据。"""

    phone_bound = serializers.BooleanField(help_text="是否绑定手机号")
    last_login_at = serializers.DateTimeField(
        allow_null=True,
        help_text="最近登录时间",
    )
    active_token_count = serializers.IntegerField(help_text="有效用户访问令牌数量")
    auth_types = serializers.ListField(
        child=serializers.CharField(),
        help_text="已启用认证方式",
    )


class AdminUserDetailResponseSerializer(serializers.Serializer):
    """管理员用户详情分区响应。"""

    basic = AdminUserResponseSerializer(help_text="账号和经营概览")
    profile = AdminUserProfileSerializer(help_text="个人资料")
    identity = AdminUserIdentitySerializer(help_text="实名认证")
    provider = AdminUserProviderSerializer(help_text="服务者资料")
    finance = AdminUserFinanceSerializer(help_text="余额、收益、佣金和收款方式")
    orders = AdminUserOrderSummarySerializer(help_text="订单概览")
    social = AdminUserSocialSerializer(help_text="评价和客服概览")
    security = AdminUserSecuritySerializer(help_text="账号安全概览")


class AdminUserOrderResponseSerializer(serializers.Serializer):
    """用户关联订单管理摘要。"""

    order_no = serializers.UUIDField(help_text="订单 UUID")
    role = serializers.CharField(help_text="目标用户参与角色：CUSTOMER 或 PROVIDER")
    status = serializers.CharField(help_text="订单状态")
    service_title = serializers.CharField(help_text="服务名称")
    cover_media = MediaAssetSummarySerializer(
        allow_null=True,
        help_text="服务封面媒体",
    )
    currency = serializers.CharField(help_text="币种")
    payable_amount_minor = serializers.IntegerField(help_text="应付金额，单位为分")
    paid_amount_minor = serializers.IntegerField(help_text="已支付金额，单位为分")
    refunded_amount_minor = serializers.IntegerField(help_text="已退款金额，单位为分")
    created_at = serializers.DateTimeField(help_text="订单创建时间")
    paid_at = serializers.DateTimeField(allow_null=True, help_text="订单支付时间")
    completed_at = serializers.DateTimeField(
        allow_null=True,
        help_text="订单完成时间",
    )


class AdminUserFinanceLedgerResponseSerializer(serializers.Serializer):
    """用户钱包、收益记录和收益流水统一明细。"""

    ledger_type = serializers.CharField(
        help_text="明细类型：WALLET、EARNING_ENTRY 或 EARNING_TRANSACTION"
    )
    transaction_no = serializers.UUIDField(help_text="明细对外 UUID")
    account_type = serializers.CharField(help_text="账户类型")
    account_type_text = serializers.CharField(help_text="账户类型中文含义")
    direction = serializers.CharField(help_text="资金方向")
    direction_text = serializers.CharField(help_text="资金方向中文含义")
    transaction_type = serializers.CharField(help_text="交易或业务类型")
    transaction_type_text = serializers.CharField(help_text="交易或业务类型中文含义")
    business_type = serializers.CharField(help_text="关联业务类型")
    business_no = serializers.CharField(help_text="关联业务单号")
    currency = serializers.CharField(help_text="币种")
    amount_minor = serializers.IntegerField(help_text="变动金额，单位为分")
    available_after_amount_minor = serializers.IntegerField(
        required=False,
        help_text="变动后可用金额，单位为分",
    )
    frozen_after_amount_minor = serializers.IntegerField(
        required=False,
        help_text="变动后冻结金额，单位为分",
    )
    gross_amount_minor = serializers.IntegerField(
        required=False,
        help_text="收益原始金额，单位为分",
    )
    platform_fee_amount_minor = serializers.IntegerField(
        required=False,
        help_text="平台佣金，单位为分",
    )
    status = serializers.CharField(required=False, help_text="收益结算状态")
    status_text = serializers.CharField(
        required=False,
        help_text="收益结算状态中文含义",
    )
    available_at = serializers.DateTimeField(
        required=False,
        help_text="最早可结算时间",
    )
    settled_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="实际结算时间",
    )
    created_at = serializers.DateTimeField(help_text="明细创建时间")


class AdminUserOrderListResponseSerializer(serializers.Serializer):
    """用户关联订单分页响应。"""

    items = AdminUserOrderResponseSerializer(many=True, help_text="订单明细")
    total = serializers.IntegerField(help_text="订单总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")


class AdminUserFinanceListResponseSerializer(serializers.Serializer):
    """用户资金明细分页响应。"""

    items = AdminUserFinanceLedgerResponseSerializer(many=True, help_text="资金明细")
    total = serializers.IntegerField(help_text="资金明细总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")


class AdminUserListResponseSerializer(serializers.Serializer):
    """管理员用户分页响应。"""

    items = AdminUserResponseSerializer(many=True, help_text="用户列表")
    total = serializers.IntegerField(help_text="用户总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")


class AdminProviderResponseSerializer(serializers.Serializer):
    """管理员服务者安全摘要。"""

    user_public_id = serializers.UUIDField(help_text="服务者用户 UUID")
    nickname = serializers.CharField(allow_null=True, help_text="服务者昵称")
    phone_masked = serializers.CharField(help_text="脱敏手机号")
    provider_status = serializers.CharField(help_text="服务者状态")
    provider_enabled = serializers.BooleanField(help_text="是否启用服务者权限")
    version = serializers.IntegerField(help_text="账号管理版本号")


class AdminProviderListResponseSerializer(serializers.Serializer):
    """管理员服务者分页响应。"""

    items = AdminProviderResponseSerializer(many=True, help_text="服务者列表")
    total = serializers.IntegerField(help_text="服务者总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")


class AdminOrderListResponseSerializer(serializers.Serializer):
    """管理员订单分页响应。"""

    items = OrderResponseSerializer(many=True, help_text="订单列表")
    total = serializers.IntegerField(help_text="订单总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")


class AdminActionRequestSerializer(serializers.Serializer):
    """管理员状态写操作请求。"""

    expected_version = serializers.IntegerField(min_value=1, help_text="对象当前版本号")
    reason = serializers.CharField(required=False, allow_blank=True, help_text="操作原因")


class AdminUserForceDeleteRequestSerializer(serializers.Serializer):
    """管理员强制注销用户请求。"""

    expected_version = serializers.IntegerField(
        min_value=1,
        help_text="用户账号当前版本号",
    )
    reason = serializers.CharField(
        min_length=2,
        max_length=500,
        help_text="强制注销原因，用于资金和审计留痕",
    )


class AdminUserBalanceClearRequestSerializer(serializers.Serializer):
    """管理员清空用户可提现余额和待结算权益请求。"""

    reason = serializers.CharField(
        min_length=2,
        max_length=500,
        help_text="资金清空原因，用于不可变流水和审计留痕",
    )


class AdminUserBalanceClearResponseSerializer(serializers.Serializer):
    """管理员资金清空结果。"""

    user_public_id = serializers.UUIDField(help_text="目标用户 UUID")
    cleared_wallet_amount_minor = serializers.IntegerField(help_text="清空的钱包余额，单位为分")
    cleared_earning_amount_minor = serializers.IntegerField(
        help_text="清空的收益账户余额，单位为分"
    )
    canceled_pending_reward_amount_minor = serializers.IntegerField(
        help_text="取消的待结算推广奖励金额，单位为分"
    )
    canceled_pending_earning_amount_minor = serializers.IntegerField(
        help_text="取消的待结算收益金额，单位为分"
    )
    canceled_withdrawal_count = serializers.IntegerField(help_text="取消的处理中提现申请数量")
    wallet_transaction_nos = serializers.ListField(
        child=serializers.UUIDField(),
        help_text="钱包调整流水 UUID 列表",
    )
    earning_transaction_nos = serializers.ListField(
        child=serializers.UUIDField(),
        help_text="收益调整流水 UUID 列表",
    )
    cleared_amount_minor = serializers.IntegerField(
        help_text="本次强制清空或取消的资金合计，单位为分"
    )


class AdminUserForceDeleteResponseSerializer(serializers.Serializer):
    """管理员强制注销用户结果。"""

    request_no = serializers.UUIDField(help_text="账号注销审计 UUID")
    phone_masked = serializers.CharField(help_text="注销前手机号脱敏快照")
    deleted_at = serializers.DateTimeField(help_text="强制注销完成时间")
    deletion_mode = serializers.CharField(help_text="注销方式")
    operator_user_id = serializers.IntegerField(help_text="执行强制注销的管理员主键")
    reason = serializers.CharField(help_text="强制注销原因")
    cleared_amount_minor = serializers.IntegerField(help_text="强制清空的资金合计，单位为分")
    cleanup_counts = serializers.DictField(help_text="个人资料和内容清理数量")
    retained_categories = serializers.ListField(
        child=serializers.CharField(),
        help_text="依法保留或匿名化的数据类别",
    )
    fund_clear = AdminUserBalanceClearResponseSerializer(help_text="资金清空明细")


class AdminAuditLogResponseSerializer(serializers.Serializer):
    """管理员操作审计记录。"""

    operation_no = serializers.UUIDField(help_text="审计业务 UUID")
    action = serializers.CharField(help_text="管理动作")
    action_text = serializers.CharField(help_text="管理动作中文含义")
    target_type = serializers.CharField(help_text="目标对象类型")
    target_type_text = serializers.CharField(help_text="目标对象类型中文含义")
    target_id = serializers.CharField(help_text="目标对象标识")
    operator_public_id = serializers.UUIDField(
        allow_null=True,
        help_text="操作者用户 UUID",
    )
    reason = serializers.CharField(help_text="操作原因")
    trace_id = serializers.CharField(help_text="请求追踪标识")
    created_at = serializers.DateTimeField(help_text="审计创建时间")


class AdminAuditLogListResponseSerializer(serializers.Serializer):
    """管理员审计分页响应。"""

    items = AdminAuditLogResponseSerializer(many=True, help_text="审计记录")
    total = serializers.IntegerField(help_text="审计总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")


class AdminUserWithdrawalListResponseSerializer(serializers.Serializer):
    """用户提现申请分页响应。"""

    items = WithdrawalResponseSerializer(many=True, help_text="提现申请")
    total = serializers.IntegerField(help_text="提现申请总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")


class AdminUserReviewListResponseSerializer(serializers.Serializer):
    """用户发表或收到的评价分页响应。"""

    items = ReviewResponseSerializer(many=True, help_text="评价明细")
    total = serializers.IntegerField(help_text="评价总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")


class AdminUserSupportTicketListResponseSerializer(serializers.Serializer):
    """用户客服工单分页响应。"""

    items = SupportTicketResponseSerializer(many=True, help_text="客服工单")
    total = serializers.IntegerField(help_text="工单总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")


class AdminUserAuditLogListResponseSerializer(serializers.Serializer):
    """用户相关管理审计分页响应。"""

    items = AdminAuditLogResponseSerializer(many=True, help_text="用户审计记录")
    total = serializers.IntegerField(help_text="审计总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")


class AdminPermissionResponseSerializer(serializers.Serializer):
    """权限点。"""

    code = serializers.CharField(help_text="权限点代码")
    name = serializers.CharField(help_text="权限点名称")
    category = serializers.CharField(help_text="权限点分组")


class AdminRoleResponseSerializer(serializers.Serializer):
    """管理员角色。"""

    role_no = serializers.UUIDField(help_text="角色 UUID")
    code = serializers.CharField(help_text="角色代码")
    name = serializers.CharField(help_text="角色名称")
    description = serializers.CharField(help_text="角色说明")
    status = serializers.CharField(help_text="角色状态")
    status_text = serializers.CharField(help_text="角色状态中文含义")
    permission_codes = serializers.ListField(
        child=serializers.CharField(),
        help_text="角色权限点",
    )
    member_count = serializers.IntegerField(help_text="角色成员数量")
    version = serializers.IntegerField(help_text="角色版本号")


class AdminRoleCreateRequestSerializer(serializers.Serializer):
    """创建管理员角色。"""

    code = serializers.CharField(max_length=64, help_text="角色稳定代码")
    name = serializers.CharField(max_length=100, help_text="角色名称")
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=255,
        help_text="角色说明",
    )
    permission_codes = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="角色权限点",
    )


class AdminRoleUpdateRequestSerializer(serializers.Serializer):
    """修改管理员角色。"""

    expected_version = serializers.IntegerField(min_value=1, help_text="角色当前版本号")
    name = serializers.CharField(required=False, max_length=100, help_text="角色名称")
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=255,
        help_text="角色说明",
    )
    status = serializers.ChoiceField(
        choices=["ACTIVE", "DISABLED"],
        required=False,
        help_text="角色状态",
    )
    permission_codes = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="角色权限点",
    )


class AdminRolePermissionRequestSerializer(serializers.Serializer):
    """整体替换角色权限点。"""

    expected_version = serializers.IntegerField(min_value=1, help_text="角色当前版本号")
    permission_codes = serializers.ListField(
        child=serializers.CharField(),
        help_text="角色权限点",
    )
