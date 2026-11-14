"""聊天实时投递 Outbox 的幂等重试任务。"""

from __future__ import annotations

import logging

from celery import shared_task

from backend.messaging.services import retry_pending_message_deliveries

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=5, default_retry_delay=30)
def retry_message_delivery_task(self, limit: int = 100) -> dict[str, int]:
    """重试实时广播失败事件；消息事实已经持久化，不影响业务提交。"""

    try:
        return retry_pending_message_deliveries(limit=limit)
    except Exception as exc:
        logger.warning("聊天消息投递重试失败 error=%s", type(exc).__name__)
        raise self.retry(exc=exc) from exc
