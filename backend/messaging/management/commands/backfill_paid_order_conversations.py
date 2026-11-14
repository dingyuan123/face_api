"""补齐已支付订单的双方聊天会话和支付成功系统提示。"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from backend.messaging.services import ensure_order_paid_conversation
from backend.orders.queries import get_paid_orders_for_chat_activation


class Command(BaseCommand):
    """幂等补齐历史已支付订单聊天初始化结果。"""

    help = "为历史已支付订单幂等创建双方会话和支付成功系统提示"

    def add_arguments(self, parser) -> None:
        """声明只读预检参数。"""

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="只统计需要补齐的历史订单，不写入数据库",
        )

    def handle(self, *args, **options) -> None:
        """逐笔调用公开聊天服务补齐，单笔失败不影响其余订单并汇总报告。"""

        dry_run = bool(options.get("dry_run"))
        processed = 0
        reused = 0
        failures: list[str] = []

        for order in get_paid_orders_for_chat_activation().iterator():
            processed += 1
            if dry_run:
                continue
            try:
                result = ensure_order_paid_conversation(order_no=str(order.order_no))
                if result["reused"]:
                    reused += 1
            except Exception as exc:
                failures.append(f"{order.order_no}: {type(exc).__name__}")

        summary = f"已支付订单 {processed} 笔；" + (
            "预检完成，未写入数据。" if dry_run else f"复用已有初始化结果 {reused} 笔。"
        )
        self.stdout.write(summary)
        if failures:
            details = "\n".join(failures)
            raise CommandError(f"以下订单补齐失败，修复后可重新执行：\n{details}")
