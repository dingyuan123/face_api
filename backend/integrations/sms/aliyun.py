"""阿里云短信 SendSms 发送适配器，不记录 AccessKey、手机号或验证码。"""

from __future__ import annotations

import json
import logging

from django.conf import settings

from backend.common.crypto import sensitive_fingerprint
from backend.integrations.sms.contracts import (
    SmsProviderError,
    SmsProviderUnavailable,
    SmsSendResult,
)

logger = logging.getLogger("jianmianliao.sms.aliyun")


class AliyunSmsGateway:
    """使用阿里云短信服务发送验证码短信。"""

    def __init__(self) -> None:
        self._validate_config()
        try:
            from alibabacloud_dysmsapi20170525 import models as sms_models
            from alibabacloud_dysmsapi20170525.client import Client
            from alibabacloud_tea_openapi import models as open_api_models
        except ImportError as exc:
            raise SmsProviderUnavailable(
                "阿里云短信 SDK 未安装",
                provider_status="SDK_NOT_INSTALLED",
            ) from exc
        config = open_api_models.Config(
            access_key_id=settings.ALIYUN_SMS_ACCESS_KEY_ID,
            access_key_secret=settings.ALIYUN_SMS_ACCESS_KEY_SECRET,
            region_id=settings.ALIYUN_SMS_REGION_ID,
            endpoint=settings.ALIYUN_SMS_ENDPOINT,
        )
        self.client = Client(config)
        self.models = sms_models

    def _validate_config(self) -> None:
        required = {
            "ALIYUN_SMS_ACCESS_KEY_ID": settings.ALIYUN_SMS_ACCESS_KEY_ID,
            "ALIYUN_SMS_ACCESS_KEY_SECRET": settings.ALIYUN_SMS_ACCESS_KEY_SECRET,
            "ALIYUN_SMS_SIGN_NAME": settings.ALIYUN_SMS_SIGN_NAME,
            "ALIYUN_SMS_TEMPLATE_CODE": settings.ALIYUN_SMS_TEMPLATE_CODE,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise SmsProviderUnavailable(
                "阿里云短信配置不完整",
                provider_status="CONFIG_INCOMPLETE",
                missing_config=missing,
            )

    def send_sms(self, *, phone: str, code: str) -> SmsSendResult:
        """调用阿里云 SendSms 发送验证码并返回脱敏结果。"""
        request = self.models.SendSmsRequest(
            phone_numbers=phone,
            sign_name=settings.ALIYUN_SMS_SIGN_NAME,
            template_code=settings.ALIYUN_SMS_TEMPLATE_CODE,
            template_param=json.dumps(
                {settings.ALIYUN_SMS_TEMPLATE_PARAM_KEY: code},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
        try:
            response = self.client.send_sms(request)
        except Exception as exc:
            logger.warning(
                "阿里云短信请求网络失败",
                extra={
                    "sms_provider": "ALIYUN",
                    "error_type": type(exc).__name__,
                },
            )
            raise SmsProviderUnavailable(
                "阿里云短信服务暂不可用",
                provider_status="NETWORK_ERROR",
            ) from exc
        body = getattr(response, "body", None)
        code_value = str(getattr(body, "code", "") or "")
        message = str(getattr(body, "message", "") or "")
        request_id = str(getattr(body, "request_id", "") or "")
        biz_id = str(getattr(body, "biz_id", "") or "")
        message_fingerprint = sensitive_fingerprint({"message": message})[:16]
        if code_value != "OK":
            logger.warning(
                "阿里云短信发送被拒绝",
                extra={
                    "sms_provider": "ALIYUN",
                    "provider_code": code_value,
                    "provider_message_fingerprint": message_fingerprint,
                    "provider_request_id": request_id,
                },
            )
            raise SmsProviderError(
                message or "阿里云短信发送失败",
                provider_code=code_value,
            )
        logger.info(
            "阿里云短信发送成功",
            extra={
                "sms_provider": "ALIYUN",
                "provider_code": code_value,
                "provider_request_id": request_id,
                "provider_message_id": biz_id,
            },
        )
        return SmsSendResult(
            provider_request_id=request_id,
            provider_message_id=biz_id,
            status="SENT",
        )
