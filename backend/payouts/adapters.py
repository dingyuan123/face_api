"""收款账户验证和打款渠道适配接口。"""

from __future__ import annotations

import uuid
from typing import Protocol

from django.conf import settings

from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError


class PayoutVerifier(Protocol):
    """收款账户验证渠道最小接口。"""

    def verify(self, *, method_type: str, account_number: str) -> str:
        """验证收款账户并返回渠道验证引用。"""


class PayoutChannel(Protocol):
    """提现打款渠道最小接口。"""

    def payout(self, *, withdrawal_no: str, amount_minor: int, account_snapshot: dict) -> str:
        """向收款账户发起打款并返回渠道流水号。"""


class MockPayoutVerifier:
    """当前测试阶段使用的模拟收款账户验证器。"""

    def verify(self, *, method_type: str, account_number: str) -> str:
        """直接返回模拟验证引用，不访问真实银行或支付渠道。"""

        if settings.PAYOUT_VERIFICATION_MODE != "MOCK":
            raise ApiError(
                ErrorCode.PAYOUT_EXECUTION_FAILED,
                ERROR_MESSAGES[ErrorCode.PAYOUT_EXECUTION_FAILED],
                status_code=503,
            )
        return f"MOCK-VERIFY-{uuid.uuid4().hex.upper()}"


class MockPayoutChannel:
    """当前测试阶段使用的模拟打款渠道。"""

    def payout(self, *, withdrawal_no: str, amount_minor: int, account_snapshot: dict) -> str:
        """模拟打款成功并返回渠道流水号，不产生真实资金转移。"""

        if settings.PAYOUT_MODE != "MOCK_MANUAL_REVIEW":
            raise ApiError(
                ErrorCode.PAYOUT_EXECUTION_FAILED,
                ERROR_MESSAGES[ErrorCode.PAYOUT_EXECUTION_FAILED],
                status_code=503,
            )
        return f"MOCK-PAYOUT-{uuid.uuid4().hex.upper()}"


def get_payout_verifier() -> PayoutVerifier:
    """返回当前配置的收款账户验证适配器。"""

    return MockPayoutVerifier()


def get_payout_channel() -> PayoutChannel:
    """返回当前配置的提现打款适配器。"""

    return MockPayoutChannel()
