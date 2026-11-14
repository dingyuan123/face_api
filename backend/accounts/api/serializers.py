from __future__ import annotations

from rest_framework import serializers

from backend.accounts.services import normalize_phone
from backend.providers.api.serializers import ProviderApplicationResponseSerializer


class SmsCodeRequestSerializer(serializers.Serializer):
    """发送手机号验证码请求。"""

    phone = serializers.CharField(max_length=20, help_text="中国大陆手机号，例如 13800138000")

    def validate_phone(self, value: str) -> str:
        return normalize_phone(value)


class SmsCodeResponseSerializer(serializers.Serializer):
    """发送验证码响应。"""

    request_id = serializers.UUIDField(help_text="验证码发送请求唯一标识")
    expires_in = serializers.IntegerField(help_text="验证码剩余有效期，单位为秒")
    debug_code = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="开发 Mock 六位验证码；生产模式不返回",
    )
    reused = serializers.BooleanField(help_text="是否为同幂等键重放结果")


class ReferralContextSerializer(serializers.Serializer):
    """分享入口携带的邀请归因上下文。"""

    invite_code = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=16,
        help_text="分享邀请码；仅在新用户注册时用于绑定直接邀请人",
    )
    share_no = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        help_text="分享链接标识，用于来源转化统计",
    )
    share_id = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        help_text="share_no 的兼容别名",
    )
    channel = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=32,
        help_text="分享渠道，例如 WECHAT、POSTER",
    )
    campaign_code = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        help_text="运营活动代码，可为空",
    )
    visitor_id = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=128,
        help_text="客户端匿名访问标识，服务端只保存摘要",
    )


class LoginRequestSerializer(serializers.Serializer):
    """手机号验证码登录请求。"""

    phone = serializers.CharField(max_length=20, help_text="登录手机号")
    code = serializers.CharField(max_length=6, min_length=6, help_text="六位数字验证码")
    referral_context = ReferralContextSerializer(
        required=False,
        help_text="分享入口归因信息；仅新用户注册时生效",
    )

    def validate_phone(self, value: str) -> str:
        return normalize_phone(value)


class AppleLoginRequestSerializer(serializers.Serializer):
    """iOS App Sign in with Apple 登录请求。"""

    identity_token = serializers.CharField(help_text="Apple SDK 返回的 identity_token")
    nonce = serializers.CharField(help_text="iOS 登录前生成并传给 Apple 的一次性 nonce")
    authorization_code = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Apple SDK 返回的 authorization_code，可选，仅用于审计",
    )
    referral_context = ReferralContextSerializer(
        required=False,
        help_text="分享入口归因信息；第三方账号绑定手机号时完成归因",
    )


class WeChatLoginRequestSerializer(serializers.Serializer):
    """微信开放平台 App 登录请求。"""

    code = serializers.CharField(help_text="微信 App SDK 返回的临时授权 code")
    state = serializers.CharField(help_text="微信 App SDK 返回的 state，必须与发起登录时一致")
    platform = serializers.ChoiceField(
        choices=["IOS", "ANDROID"],
        help_text="客户端平台，仅用于审计，不参与身份信任判断",
    )
    referral_context = ReferralContextSerializer(
        required=False,
        help_text="分享入口归因信息；第三方账号绑定手机号时完成归因",
    )


class PhoneBindingRequestSerializer(serializers.Serializer):
    """第三方账号手动绑定手机号请求。"""

    phone = serializers.CharField(max_length=20, help_text="需要绑定的中国大陆手机号")
    code = serializers.CharField(max_length=6, min_length=6, help_text="六位数字验证码")

    def validate_phone(self, value: str) -> str:
        return normalize_phone(value)

    referral_context = ReferralContextSerializer(
        required=False,
        help_text="分享入口归因信息；第三方账号完成手机号绑定时生效",
    )


class DevPasswordLoginRequestSerializer(serializers.Serializer):
    """开发测试账号密码登录请求；生产环境接口不可用。"""

    phone = serializers.CharField(max_length=20, help_text="已设置密码的登录手机号")
    password = serializers.CharField(
        write_only=True,
        help_text="账号密码；仅用于开发测试，接口不会返回或记录明文密码",
    )

    def validate_phone(self, value: str) -> str:
        return normalize_phone(value)


class RefreshRequestSerializer(serializers.Serializer):
    """访问令牌刷新请求。"""

    refresh_token = serializers.CharField(help_text="当前设备会话的有效刷新令牌")


class TokenPairResponseSerializer(serializers.Serializer):
    """登录或刷新后的令牌对响应。"""

    token_type = serializers.CharField(help_text="令牌类型，当前固定为 Bearer")
    access_token = serializers.CharField(help_text="短期访问令牌")
    refresh_token = serializers.CharField(help_text="当前设备会话刷新令牌")
    expires_in = serializers.IntegerField(help_text="访问令牌剩余有效期，单位为秒")
    refresh_expires_in = serializers.IntegerField(help_text="刷新令牌剩余有效期，单位为秒")
    user_public_id = serializers.UUIDField(help_text="对外用户标识")
    is_new_user = serializers.BooleanField(help_text="本次登录是否自动创建新用户")
    requires_identity_selection = serializers.BooleanField(help_text="是否仍需选择首次身份")
    requires_phone_binding = serializers.BooleanField(help_text="是否仍需手动绑定手机号")


class SessionResponseSerializer(serializers.Serializer):
    """当前登录用户会话状态。"""

    user_public_id = serializers.UUIDField(help_text="对外用户标识")
    phone_masked = serializers.CharField(help_text="脱敏手机号")
    status = serializers.CharField(help_text="账号状态")
    requires_identity_selection = serializers.BooleanField(help_text="是否仍需选择首次身份")
    requires_phone_binding = serializers.BooleanField(help_text="是否仍需手动绑定手机号")
    auth_methods = serializers.ListField(
        child=serializers.CharField(),
        help_text="已启用登录方式，例如 PHONE、WECHAT、APPLE",
    )
    primary_role = serializers.CharField(allow_null=True, help_text="当前主身份")
    current_role = serializers.CharField(help_text="客户端当前应使用的身份")
    roles = serializers.ListField(
        child=serializers.CharField(),
        help_text="当前可用身份列表，服务者审核通过后包含 USER 和 PROVIDER",
    )
    default_workspace = serializers.CharField(allow_null=True, help_text="默认工作区")
    provider_status = serializers.CharField(help_text="服务者审核状态")
    provider_application = ProviderApplicationResponseSerializer(
        allow_null=True,
        help_text="当前用户最新服务者申请摘要，包含临时图片展示地址",
    )


class LogoutResponseSerializer(serializers.Serializer):
    """退出当前设备会话结果。"""

    logged_out = serializers.BooleanField(help_text="是否已撤销当前会话令牌")


class PhoneBindingResponseSerializer(TokenPairResponseSerializer):
    """手机号绑定完成响应，合并账号后返回新会话令牌。"""

    already_bound = serializers.BooleanField(help_text="本次请求是否为重复绑定")
    merged = serializers.BooleanField(help_text="是否合并到已经注册且未绑定第三方账号的手机号账号")


class InitialRoleRequestSerializer(serializers.Serializer):
    """首次身份选择请求。"""

    role = serializers.ChoiceField(
        choices=["USER", "PROVIDER"],
        help_text="USER 表示普通用户，PROVIDER 表示服务陪伴者",
    )


class InitialRoleResponseSerializer(serializers.Serializer):
    """首次身份选择后的路由和状态响应。"""

    primary_role = serializers.CharField(allow_null=True, help_text="当前主身份")
    current_role = serializers.CharField(help_text="客户端当前应使用的身份")
    roles = serializers.ListField(
        child=serializers.CharField(),
        help_text="当前可用身份列表，服务者审核通过后包含 USER 和 PROVIDER",
    )
    default_workspace = serializers.CharField(allow_null=True, help_text="默认工作区")
    next_route = serializers.CharField(allow_null=True, help_text="客户端建议进入的工作区")
    requires_identity_selection = serializers.BooleanField(help_text="是否仍需选择首次身份")
    provider_status = serializers.CharField(help_text="服务者审核状态")
