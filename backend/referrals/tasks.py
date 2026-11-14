"""推广奖励结算和分享访问数据到期清理的异步任务。"""

from __future__ import annotations

from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from backend.referrals.models import ReferralVisit
from backend.referrals.reward_services import settle_due_referral_rewards


@shared_task(bind=True, max_retries=2)
def settle_referral_rewards_task(self) -> dict[str, int]:
    """幂等结算到期推广奖励；失败由 Celery 重试。"""
    try:
        return settle_due_referral_rewards(limit=200)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=30) from exc


@shared_task(bind=True, max_retries=2)
def cleanup_referral_visits_task(self) -> dict[str, int]:
    """删除超过配置保留期的匿名分享访问记录。"""
    try:
        cutoff = timezone.now() - timedelta(days=settings.REFERRAL_VISIT_RETENTION_DAYS)
        deleted_count, _ = ReferralVisit.objects.filter(occurred_at__lt=cutoff).delete()
        return {"deleted": deleted_count}
    except Exception as exc:
        raise self.retry(exc=exc, countdown=30) from exc
