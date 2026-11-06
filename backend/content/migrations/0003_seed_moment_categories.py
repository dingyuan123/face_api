"""历史迁移占位；动态类目在模型迁移后写入。"""

from __future__ import annotations

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("content", "0002_seed_moment_tags"),
    ]

    operations = [
        migrations.RunPython(migrations.RunPython.noop, migrations.RunPython.noop),
    ]
