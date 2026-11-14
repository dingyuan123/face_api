"""地点搜索配置的 Django Admin 只读辅助注册。"""

from django.contrib import admin

from backend.locations.models import LocationSearchKeyword, LocationSearchRule


@admin.register(LocationSearchKeyword)
class LocationSearchKeywordAdmin(admin.ModelAdmin):
    """展示地点快捷关键词配置，正式修改仍通过管理 API 记录版本。"""

    list_display = ("code", "label", "query_keyword", "sort_order", "enabled", "version")
    list_filter = ("enabled",)
    search_fields = ("code", "label", "query_keyword")


@admin.register(LocationSearchRule)
class LocationSearchRuleAdmin(admin.ModelAdmin):
    """展示公共场所允许和拒绝规则，便于运营核对过滤范围。"""

    list_display = ("code", "decision", "match_scope", "match_value", "priority", "enabled")
    list_filter = ("decision", "match_scope", "enabled")
    search_fields = ("code", "match_value", "reason")
