"""将 Google News 资讯来源改为综合最新资讯订阅地址。"""

from __future__ import annotations

from django.db import migrations


GENERAL_FEED_URL = "https://news.google.com/rss?hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
LEGACY_SEARCH_FEED_URL = (
    "https://news.google.com/rss/search?q=when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
)


def use_google_general_feed(apps, schema_editor):
    """更新已有 Google News 来源，使同步默认获取综合最新资讯。"""

    NewsSource = apps.get_model("content", "NewsSource")
    NewsSource.objects.filter(code="GOOGLE_NEWS_ZH", source_type="RSS").update(
        feed_url=GENERAL_FEED_URL,
    )


def restore_legacy_search_feed(apps, schema_editor):
    """回退到历史搜索地址，仅用于迁移撤销。"""

    NewsSource = apps.get_model("content", "NewsSource")
    NewsSource.objects.filter(code="GOOGLE_NEWS_ZH", source_type="RSS").update(
        feed_url=LEGACY_SEARCH_FEED_URL,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("content", "0007_seed_news_categories_and_sources"),
    ]

    operations = [
        migrations.RunPython(use_google_general_feed, restore_legacy_search_feed),
    ]
