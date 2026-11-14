"""写入地点搜索快捷关键词和公共场所过滤首批规则。"""

from __future__ import annotations

from django.db import migrations


QUICK_KEYWORDS = [
    ("RESTAURANT", "餐厅", "餐厅", 10),
    ("COFFEE", "咖啡店", "咖啡", 20),
    ("PARK", "公园", "公园", 30),
    ("LIBRARY", "图书馆", "图书馆", 40),
    ("SPORTS", "运动场馆", "运动", 50),
]

RULES = [
    ("DENY_HOTEL_EN", "DENY", "ANY", "hotel", "不接受酒店类地点", 10),
    ("DENY_HOTEL", "DENY", "ANY", "酒店", "不接受酒店类地点", 20),
    ("DENY_GUESTHOUSE", "DENY", "ANY", "宾馆", "不接受住宿类地点", 30),
    ("DENY_HOMESTAY", "DENY", "ANY", "民宿", "不接受住宿类地点", 40),
    ("DENY_INN", "DENY", "ANY", "旅馆", "不接受住宿类地点", 50),
    ("DENY_APARTMENT", "DENY", "ANY", "公寓", "不接受私人居住场所", 60),
    ("DENY_RESIDENCE", "DENY", "ANY", "住宅", "不接受私人居住场所", 70),
    ("DENY_RESIDENTIAL_AREA", "DENY", "ANY", "小区", "不接受私人居住场所", 80),
    ("ALLOW_DINING", "ALLOW", "CATEGORY", "餐饮", "餐饮公共场所", 100),
    ("ALLOW_RESTAURANT", "ALLOW", "CATEGORY", "餐厅", "餐厅公共场所", 110),
    ("ALLOW_CAFE", "ALLOW", "CATEGORY", "咖啡", "咖啡店公共场所", 120),
    ("ALLOW_TEA_HOUSE", "ALLOW", "CATEGORY", "茶馆", "茶馆公共场所", 130),
    ("ALLOW_BOOKSTORE", "ALLOW", "CATEGORY", "书店", "书店公共场所", 140),
    ("ALLOW_LIBRARY", "ALLOW", "CATEGORY", "图书馆", "图书馆公共场所", 150),
    ("ALLOW_PARK", "ALLOW", "CATEGORY", "公园", "公园公共场所", 160),
    ("ALLOW_SPORTS", "ALLOW", "CATEGORY", "运动", "运动场馆公共场所", 170),
    ("ALLOW_FITNESS", "ALLOW", "CATEGORY", "健身", "健身场馆公共场所", 180),
    ("ALLOW_CULTURE", "ALLOW", "CATEGORY", "文化", "文化场馆公共场所", 190),
    ("ALLOW_MUSEUM", "ALLOW", "CATEGORY", "博物馆", "博物馆公共场所", 200),
    ("ALLOW_EXHIBITION", "ALLOW", "CATEGORY", "展览", "展览馆公共场所", 210),
    ("ALLOW_CINEMA", "ALLOW", "CATEGORY", "电影", "电影院公共场所", 220),
    ("ALLOW_ENTERTAINMENT", "ALLOW", "CATEGORY", "娱乐", "休闲娱乐公共场所", 230),
    ("ALLOW_BOARD_GAME", "ALLOW", "CATEGORY", "桌游", "桌游馆公共场所", 240),
    ("ALLOW_ESCAPE_ROOM", "ALLOW", "CATEGORY", "密室", "密室公共场所", 250),
    ("ALLOW_SHOPPING", "ALLOW", "CATEGORY", "商场", "商场公共场所", 260),
    ("ALLOW_SCENIC", "ALLOW", "CATEGORY", "景区", "景区公共场所", 270),
    ("ALLOW_SCHOOL", "ALLOW", "CATEGORY", "学校", "学校公共场所", 280),
    ("ALLOW_HOSPITAL", "ALLOW", "CATEGORY", "医院", "医院公共场所", 290),
    ("ALLOW_GOVERNMENT", "ALLOW", "CATEGORY", "政府", "政府机构公共场所", 300),
    ("ALLOW_PUBLIC", "ALLOW", "CATEGORY", "公共", "公共服务场所", 310),
]


def seed_location_search_configuration(apps, schema_editor):
    """初始化可配置快捷词和分类过滤规则，后续由管理员或配置维护。"""

    keyword_model = apps.get_model("locations", "LocationSearchKeyword")
    rule_model = apps.get_model("locations", "LocationSearchRule")
    for code, label, query_keyword, sort_order in QUICK_KEYWORDS:
        keyword_model.objects.update_or_create(
            code=code,
            defaults={
                "label": label,
                "query_keyword": query_keyword,
                "icon": "",
                "sort_order": sort_order,
                "enabled": True,
                "idempotency_key": f"seed:location:{code}",
                "request_fingerprint": "seed-location-keyword",
            },
        )
    for code, decision, match_scope, match_value, reason, priority in RULES:
        rule_model.objects.update_or_create(
            code=code,
            defaults={
                "decision": decision,
                "match_scope": match_scope,
                "match_value": match_value,
                "reason": reason,
                "priority": priority,
                "enabled": True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("locations", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_location_search_configuration, migrations.RunPython.noop),
    ]
