"""初始化资讯类目和公开 RSS 来源配置，不写入任何资讯正文或用户数据。"""

from __future__ import annotations

from django.db import migrations


CATEGORIES = [
    ("GENERAL", "综合", 10),
    ("WORLD", "国际", 20),
    ("TECH", "科技", 30),
    ("HEALTH", "健康", 40),
    ("LIFESTYLE", "生活", 50),
    ("SPORT", "体育", 60),
]

SOURCES = [
    {
        "code": "GOOGLE_NEWS_ZH",
        "name": "Google News 中文资讯",
        "source_type": "RSS",
        "feed_url": ("https://news.google.com/rss/search?q=when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"),
        "homepage_url": "https://news.google.com/",
        "country_code": "CN",
        "language_code": "zh-CN",
        "attribution": "来源：Google News 聚合，具体版权归原文媒体",
        "license_note": "默认仅保存摘要、图片地址和原文链接；发布前需核对来源条款与版权。",
    },
    {
        "code": "BBC_WORLD",
        "name": "BBC World",
        "source_type": "RSS",
        "feed_url": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "homepage_url": "https://www.bbc.com/news/world",
        "country_code": "GB",
        "language_code": "en",
        "attribution": "来源：BBC News",
        "license_note": "默认仅保存摘要、图片地址和原文链接；发布前需核对来源条款与版权。",
    },
    {
        "code": "AL_JAZEERA",
        "name": "Al Jazeera English",
        "source_type": "RSS",
        "feed_url": "https://www.aljazeera.com/xml/rss/all.xml",
        "homepage_url": "https://www.aljazeera.com/",
        "country_code": "QA",
        "language_code": "en",
        "attribution": "来源：Al Jazeera English",
        "license_note": "默认仅保存摘要、图片地址和原文链接；发布前需核对来源条款与版权。",
    },
    {
        "code": "GUARDIAN_WORLD",
        "name": "The Guardian World",
        "source_type": "RSS",
        "feed_url": "https://www.theguardian.com/world/rss",
        "homepage_url": "https://www.theguardian.com/world",
        "country_code": "GB",
        "language_code": "en",
        "attribution": "来源：The Guardian",
        "license_note": "默认仅保存摘要、图片地址和原文链接；发布前需核对来源条款与版权。",
    },
]


def seed_news_configuration(apps, schema_editor):
    """写入幂等的资讯类目和 RSS 来源基础配置。"""

    NewsCategory = apps.get_model("content", "NewsCategory")
    NewsSource = apps.get_model("content", "NewsSource")
    for code, name, sort_order in CATEGORIES:
        NewsCategory.objects.update_or_create(
            code=code,
            defaults={"name": name, "sort_order": sort_order, "is_active": True},
        )
    for source in SOURCES:
        NewsSource.objects.update_or_create(
            code=source["code"],
            defaults={**source, "enabled": True, "fetch_interval_minutes": 60},
        )


def remove_news_configuration(apps, schema_editor):
    """仅撤销本迁移创建的初始配置，不删除管理员新增或同步资讯。"""

    NewsCategory = apps.get_model("content", "NewsCategory")
    NewsSource = apps.get_model("content", "NewsSource")
    NewsCategory.objects.filter(code__in=[item[0] for item in CATEGORIES]).delete()
    NewsSource.objects.filter(code__in=[item["code"] for item in SOURCES]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("content", "0006_newsarticle_newscategory_newssource_newssyncrun_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_news_configuration, remove_news_configuration),
    ]
