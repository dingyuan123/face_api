"""账号密码、手机号换绑和账号安全信息接口模型。"""

from __future__ import annotations

from rest_framework import serializers


class AccountSecurityResponseSerializer(serializers.Serializer):
    """当前账号密码、登录方式和安全操作能力。"""

    phone_masked = serializers.CharField(help_text="当前绑定手机号脱敏展示值")
    has_password = serializers.BooleanField(help_text="账号是否已设置登录密码")
    auth_methods = serializers.ListField(
        child=serializers.CharField(),
        help_text="已启用登录方式，例如 PHONE、PASSWORD、WECHAT 或 APPLE",
    )
    can_change_phone = serializers.BooleanField(help_text="当前账号是否可发起手机号更换")
    can_reset_password = serializers.BooleanField(help_text="当前账号是否可通过手机号找回密码")
    active_session_count = serializers.IntegerField(help_text="当前有效登录设备会话数")


class SecuritySmsResponseSerializer(serializers.Serializer):
    """账号安全短信验证码发送结果。"""

    request_id = serializers.UUIDField(help_text="验证码请求标识")
    phone_masked = serializers.CharField(help_text="验证码接收手机号脱敏展示值")
    expires_in = serializers.IntegerField(help_text="验证码剩余有效秒数")
    debug_code = serializers.CharField(
        allow_null=True,
        help_text="开发 Mock 验证码；生产环境不返回",
    )


class PasswordChangeRequestSerializer(serializers.Serializer):
    """设置首次密码或修改现有密码请求。"""

    current_password = serializers.CharField(
        required=False,
        allow_blank=True,
        write_only=True,
        help_text="当前登录密码；账号已设置密码时必填",
    )
    new_password = serializers.CharField(
        write_only=True,
        help_text="新登录密码，8 到 64 位并同时包含字母和数字",
    )
    code = serializers.CharField(
        min_length=6,
        max_length=6,
        help_text="绑定手机号收到的 6 位密码变更验证码",
    )


class PasswordChangeResponseSerializer(serializers.Serializer):
    """密码设置或修改结果。"""

    password_set = serializers.BooleanField(help_text="本次是否为首次设置密码")
    password_changed = serializers.BooleanField(help_text="本次是否修改了已有密码")
    tokens_revoked_count = serializers.IntegerField(help_text="本次撤销的其他设备令牌数量")
    current_session_preserved = serializers.BooleanField(help_text="是否保留当前设备登录会话")
    reused = serializers.BooleanField(help_text="是否复用了相同幂等请求")


class PasswordForgotSmsRequestSerializer(serializers.Serializer):
    """忘记密码验证码发送请求。"""

    phone = serializers.CharField(max_length=20, help_text="已绑定的用户手机号")


class PasswordResetRequestSerializer(serializers.Serializer):
    """忘记密码确认请求。"""

    phone = serializers.CharField(max_length=20, help_text="已绑定的用户手机号")
    code = serializers.CharField(
        min_length=6,
        max_length=6,
        help_text="手机号收到的 6 位密码重置验证码",
    )
    new_password = serializers.CharField(
        write_only=True,
        help_text="新登录密码，8 到 64 位并同时包含字母和数字",
    )


class PasswordResetResponseSerializer(serializers.Serializer):
    """忘记密码重置结果。"""

    password_reset = serializers.BooleanField(help_text="密码是否已重置")
    phone_masked = serializers.CharField(help_text="账号绑定手机号脱敏展示值")
    tokens_revoked_count = serializers.IntegerField(help_text="本次撤销的设备令牌数量")


class PhoneChangeRequestSerializer(serializers.Serializer):
    """发起手机号更换请求。"""

    new_phone = serializers.CharField(max_length=20, help_text="需要绑定的新手机号")
    current_password = serializers.CharField(
        required=False,
        allow_blank=True,
        write_only=True,
        help_text="当前密码；账号未绑定手机号时必填",
    )


class PhoneChangeResponseSerializer(serializers.Serializer):
    """手机号更换请求和验证码发送结果。"""

    request_no = serializers.UUIDField(help_text="手机号更换请求 UUID")
    old_phone_masked = serializers.CharField(help_text="变更前手机号脱敏值")
    new_phone_masked = serializers.CharField(help_text="变更后手机号脱敏值")
    verification_mode = serializers.CharField(help_text="验证方式：DUAL_SMS 或 PASSWORD_NEW_SMS")
    status = serializers.CharField(help_text="手机号更换请求状态")
    expires_in = serializers.IntegerField(help_text="双验证码剩余有效秒数")
    old_debug_code = serializers.CharField(
        allow_null=True,
        help_text="开发环境原手机号验证码；生产环境为空",
    )
    new_debug_code = serializers.CharField(
        allow_null=True,
        help_text="开发环境新手机号验证码；生产环境为空",
    )


class PhoneChangeConfirmRequestSerializer(serializers.Serializer):
    """确认手机号更换请求。"""

    request_no = serializers.UUIDField(help_text="手机号更换请求 UUID")
    old_code = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="原手机号验证码；PASSWORD_NEW_SMS 模式可不传",
    )
    new_code = serializers.CharField(
        min_length=6,
        max_length=6,
        help_text="新手机号收到的 6 位验证码",
    )


class PhoneChangeConfirmResponseSerializer(serializers.Serializer):
    """手机号更换确认结果。"""

    request_no = serializers.UUIDField(help_text="手机号更换请求 UUID")
    old_phone_masked = serializers.CharField(help_text="变更前手机号脱敏值")
    new_phone_masked = serializers.CharField(help_text="变更后手机号脱敏值")
    verification_mode = serializers.CharField(help_text="本次使用的验证方式")
    status = serializers.CharField(help_text="手机号更换请求状态")
    expires_in = serializers.IntegerField(help_text="请求剩余有效期，完成后为 0")
    already_changed = serializers.BooleanField(help_text="本次是否重复确认")
    tokens_revoked_count = serializers.IntegerField(help_text="本次撤销的其他设备令牌数量")
    current_session_preserved = serializers.BooleanField(help_text="是否保留当前设备登录会话")
