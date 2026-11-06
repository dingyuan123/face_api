"""写入个人资料兴趣标签和城市选项的首批可配置数据。"""

from __future__ import annotations

from django.db import migrations


INTEREST_TAGS = [
    ("SPORTS", "运动", "运动", 10),
    ("TRAVEL", "旅行", "生活", 20),
    ("FOOD", "美食", "生活", 30),
    ("COFFEE", "咖啡", "生活", 40),
    ("MOVIE", "电影", "娱乐", 50),
    ("MUSIC", "音乐", "娱乐", 60),
    ("READING", "阅读", "学习", 70),
    ("PHOTOGRAPHY", "摄影", "兴趣", 80),
    ("GAMING", "游戏", "娱乐", 90),
    ("PETS", "宠物", "生活", 100),
]


def seed_profile_options(apps, schema_editor):
    """写入首批标签和城市配置，后续可通过配置表继续维护。"""

    interest_tag_model = apps.get_model("profiles", "InterestTag")
    city_model = apps.get_model("profiles", "ProfileCityOption")
    for code, name, category, sort_order in INTEREST_TAGS:
        interest_tag_model.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "category": category,
                "sort_order": sort_order,
                "is_active": True,
            },
        )
    city_model.objects.update_or_create(
        code="LZ",
        defaults={"name": "泸州", "sort_order": 10, "is_active": True},
    )


class Migration(migrations.Migration):
    dependencies = [
        ("profiles", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_profile_options, migrations.RunPython.noop),
    ]
