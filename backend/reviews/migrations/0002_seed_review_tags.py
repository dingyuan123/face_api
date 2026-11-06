"""写入服务评价标签的首批可配置数据。"""

from __future__ import annotations

from django.db import migrations


REVIEW_TAGS = [
    ("PATIENT", "很耐心", "服务体验", 10),
    ("BEGINNER", "新手友好", "服务体验", 20),
    ("PROFESSIONAL", "专业细致", "服务体验", 30),
    ("FRIENDLY", "轻松自然", "服务体验", 40),
    ("PUNCTUAL", "准时可靠", "服务体验", 50),
]


def seed_review_tags(apps, schema_editor):
    """写入首批评价标签配置，后续可通过配置表继续维护。"""

    tag_model = apps.get_model("reviews", "ReviewTag")
    for code, name, category, sort_order in REVIEW_TAGS:
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
        ("reviews", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_review_tags, migrations.RunPython.noop),
    ]
