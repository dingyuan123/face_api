"""刷新已生成的分享主页二维码，使其编码当前邀请链接。"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from backend.referrals.models import ReferralShareLink
from backend.referrals.qr_services import ensure_referral_qr_image
from backend.referrals.services import build_share_url


class Command(BaseCommand):
    """按当前分享域名重新生成二维码 PNG。"""

    help = "刷新已生成的分享主页二维码图片"

    def handle(self, *args: object, **options: object) -> None:
        """遍历分享链接并输出刷新数量。"""
        refreshed = 0
        links = ReferralShareLink.objects.select_related("user", "invite_code").filter(
            status=ReferralShareLink.Status.ACTIVE
        )
        for link in links.iterator():
            ensure_referral_qr_image(
                share_no=str(link.share_no),
                profile_url=build_share_url(user=link.user, share_link=link),
            )
            refreshed += 1
        self.stdout.write(f"refreshed={refreshed}")
