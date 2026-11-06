"""写入动态内容类目的首批可配置数据。"""

from __future__ import annotations

from django.db import migrations


CATEGORIES = [
    ("SPORT", "运动", 10),
    ("ENTERTAINMENT", "娱乐", 20),
    ("FOOD", "美食", 30),
    ("TRAVEL", "旅行", 40),
    ("LIFESTYLE", "生活方式", 50),
    ("LEARNING", "学习", 60),
    ("OTHER", "其他", 99),
]


def seed_moment_categories(apps, schema_editor):
    """写入首批动态类目配置，后续可通过配置表继续维护。"""

    category_model = apps.get_model("content", "MomentCategory")
    for code, name, sort_order in CATEGORIES:
        category_model.objects.update_or_create(
            code=code,
            defaults={"name": name, "sort_order": sort_order, "is_active": True},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("content", "0004_momentcategory_moment_category"),
    ]

    operations = [
        migrations.RunPython(seed_moment_categories, migrations.RunPython.noop),
    ]
