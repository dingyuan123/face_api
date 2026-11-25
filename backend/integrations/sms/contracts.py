"""短信服务商适配器统一契约和安全异常。"""

from __future__ import annotations

from dataclasses import dataclass


class SmsProviderError(Exception):
    """短信服务商拒绝请求或返回业务错误。"""

    def __init__(
        self,
        message: str,
        *,
        provider_code: str = "",
    ) -> None:
        super().__init__(message)
        self.provider_code = provider_code


class SmsProviderUnavailable(Exception):
    """短信服务商网络、配置或服务能力暂时不可用。"""

    def __init__(
        self,
        message: str,
        *,
        provider_status: str = "UNAVAILABLE",
        missing_config: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.provider_status = provider_status
        self.missing_config = missing_config or []


@dataclass(frozen=True)
class SmsSendResult:
    """短信服务商发送结果安全摘要。"""

    provider_request_id: str = ""
    provider_message_id: str = ""
    status: str = "SENT"
