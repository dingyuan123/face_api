"""配置默认启用可提供标题和封面的公开 RSS 资讯来源。"""

from __future__ import annotations

from django.db import migrations


DEFAULT_SOURCE_STATES = {
    "GOOGLE_NEWS_ZH": False,
    "BBC_WORLD": True,
    "AL_JAZEERA": False,
    "GUARDIAN_WORLD": True,
}


def configure_default_sources(apps, schema_editor):
    """默认启用封面完整的来源，停用当前无封面或无结果的来源。"""

    NewsSource = apps.get_model("content", "NewsSource")
    for code, enabled in DEFAULT_SOURCE_STATES.items():
        NewsSource.objects.filter(code=code).update(enabled=enabled)


def restore_previous_source_states(apps, schema_editor):
    """迁移撤销时恢复初始来源均为启用状态。"""

    NewsSource = apps.get_model("content", "NewsSource")
    NewsSource.objects.filter(code__in=DEFAULT_SOURCE_STATES).update(enabled=True)


class Migration(migrations.Migration):
    dependencies = [
        ("content", "0008_update_google_news_general_feed"),
    ]

    operations = [
        migrations.RunPython(configure_default_sources, restore_previous_source_states),
    ]
