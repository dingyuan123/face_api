"""手动或定时执行推广奖励到期结算。"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandParser

from backend.referrals.reward_services import settle_due_referral_rewards


class Command(BaseCommand):
    """结算当前已到观察期的推广奖励。"""

    help = "结算到期推广奖励并写入推广收益账户"

    def add_arguments(self, parser: CommandParser) -> None:
        """添加单次处理数量参数。"""
        parser.add_argument("--limit", type=int, default=100, help="单次最多处理奖励数")

    def handle(self, *args: object, **options: object) -> None:
        """执行结算并输出数量摘要。"""
        result = settle_due_referral_rewards(limit=int(options["limit"]))
        self.stdout.write(json.dumps(result, ensure_ascii=False))
