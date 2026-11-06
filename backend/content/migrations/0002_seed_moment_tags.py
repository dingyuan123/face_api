"""写入动态标签的首批可配置数据。"""

from __future__ import annotations

from django.db import migrations


MOMENT_TAGS = [
    ("SPORT", "运动", "生活", 10),
    ("TRAVEL", "旅行", "生活", 20),
    ("FOOD", "美食", "生活", 30),
    ("LIFESTYLE", "生活方式", "生活", 40),
    ("LEARNING", "学习", "成长", 50),
]


def seed_moment_tags(apps, schema_editor):
    """写入首批动态标签配置，后续可通过配置表继续维护。"""

    tag_model = apps.get_model("content", "MomentTag")
    for code, name, category, sort_order in MOMENT_TAGS:
        tag_model.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "category": category,
                "sort_order": sort_order,
                "is_active": True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("content", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_moment_tags, migrations.RunPython.noop),
    ]
