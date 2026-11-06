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


class LoginRequestSerializer(serializers.Serializer):
    """手机号验证码登录请求。"""

    phone = serializers.CharField(max_length=20, help_text="登录手机号")
    code = serializers.CharField(max_length=6, min_length=6, help_text="六位数字验证码")

    def validate_phone(self, value: str) -> str:
        return normalize_phone(value)


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


class SessionResponseSerializer(serializers.Serializer):
    """当前登录用户会话状态。"""

    user_public_id = serializers.UUIDField(help_text="对外用户标识")
    phone_masked = serializers.CharField(help_text="脱敏手机号")
    status = serializers.CharField(help_text="账号状态")
    requires_identity_selection = serializers.BooleanField(help_text="是否仍需选择首次身份")
    primary_role = serializers.CharField(allow_null=True, help_text="首次选择的身份")
    default_workspace = serializers.CharField(allow_null=True, help_text="默认工作区")
    provider_status = serializers.CharField(help_text="服务者审核状态")
    provider_application = ProviderApplicationResponseSerializer(
        allow_null=True,
        help_text="当前用户最新服务者申请摘要，包含临时图片展示地址",
    )


class LogoutResponseSerializer(serializers.Serializer):
    """退出当前设备会话结果。"""

    logged_out = serializers.BooleanField(help_text="是否已撤销当前会话令牌")


class InitialRoleRequestSerializer(serializers.Serializer):
    """首次身份选择请求。"""

    role = serializers.ChoiceField(
        choices=["USER", "PROVIDER"],
        help_text="USER 表示普通用户，PROVIDER 表示服务陪伴者",
    )


class InitialRoleResponseSerializer(serializers.Serializer):
    """首次身份选择后的路由和状态响应。"""

    primary_role = serializers.CharField(allow_null=True, help_text="已选择的初始身份")
    default_workspace = serializers.CharField(allow_null=True, help_text="默认工作区")
    next_route = serializers.CharField(allow_null=True, help_text="客户端建议进入的工作区")
    requires_identity_selection = serializers.BooleanField(help_text="是否仍需选择首次身份")
    provider_status = serializers.CharField(help_text="服务者审核状态")
