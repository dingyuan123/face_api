"""写入服务类目、服务标签和服务者标签的首批可配置数据。"""

from __future__ import annotations

from django.db import migrations


SERVICE_CATEGORIES = [
    ("SPORT", "运动", 10),
    ("ENTERTAINMENT", "娱乐", 20),
    ("LEISURE", "休闲", 30),
    ("TRAVEL", "旅游", 40),
    ("STUDY", "学习", 50),
    ("OTHER", "其他", 60),
]
SERVICE_TAGS = [
    ("BEGINNER", "新手友好", "教学特点", 10),
    ("PATIENT", "耐心教学", "教学特点", 20),
    ("FRIENDLY", "轻松陪伴", "服务风格", 30),
    ("PHOTOGENIC", "拍照好看", "服务风格", 40),
    ("ATMOSPHERE", "气氛组", "服务风格", 50),
]
PROVIDER_TAGS = [
    ("PENDING_TEACHING", "耐心教学", "服务特点", 10),
    ("FRIENDLY", "友好亲和", "服务特点", 20),
    ("PHOTOGENIC", "拍照好看", "展示特点", 30),
    ("ATMOSPHERE", "气氛组", "服务特点", 40),
]


def seed_catalog_options(apps, schema_editor):
    """写入首批服务配置，后续通过配置表启用、停用或排序。"""

    category_model = apps.get_model("catalog", "ServiceCategory")
    service_tag_model = apps.get_model("catalog", "ServiceTag")
    provider_tag_model = apps.get_model("catalog", "ProviderTag")
    for code, name, sort_order in SERVICE_CATEGORIES:
        category_model.objects.update_or_create(
            code=code,
            defaults={"name": name, "sort_order": sort_order, "is_active": True},
        )
    for code, name, category, sort_order in SERVICE_TAGS:
        service_tag_model.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "category": category,
                "sort_order": sort_order,
                "is_active": True,
            },
        )
    for code, name, category, sort_order in PROVIDER_TAGS:
        provider_tag_model.objects.update_or_create(
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
        ("catalog", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_catalog_options, migrations.RunPython.noop),
    ]
