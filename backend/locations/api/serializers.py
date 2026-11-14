"""地点搜索接口请求和响应参数说明。"""

from __future__ import annotations

from rest_framework import serializers


class LocationSearchQuerySerializer(serializers.Serializer):
    """地点周边搜索查询参数。"""

    keyword = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=100,
        help_text="自由搜索关键词，与 quick_keyword_code 二选一",
    )
    quick_keyword_code = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        help_text="后台维护的快捷关键词代码，与 keyword 二选一",
    )
    latitude = serializers.FloatField(help_text="前端地图中心纬度")
    longitude = serializers.FloatField(help_text="前端地图中心经度")
    coordinate_system = serializers.ChoiceField(
        choices=["GCJ02", "WGS84"],
        default="GCJ02",
        help_text="前端坐标系，支持 GCJ02 或 WGS84",
    )
    radius_m = serializers.IntegerField(
        required=False,
        min_value=100,
        max_value=5000,
        help_text="周边搜索半径，单位为米",
    )
    limit = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=20,
        help_text="返回地点数量，最多 20 条",
    )


class LocationSearchItemSerializer(serializers.Serializer):
    """符合公共场所规则的地点搜索结果。"""

    provider_poi_id = serializers.CharField(help_text="腾讯地图 POI 标识")
    name = serializers.CharField(help_text="地点名称")
    address = serializers.CharField(help_text="地点完整地址")
    province = serializers.CharField(help_text="省份名称")
    city = serializers.CharField(help_text="城市名称")
    district = serializers.CharField(help_text="区县名称")
    category_code = serializers.CharField(help_text="地图服务分类代码")
    category_name = serializers.CharField(help_text="地图服务分类名称")
    latitude = serializers.FloatField(help_text="地点纬度，坐标系与请求一致")
    longitude = serializers.FloatField(help_text="地点经度，坐标系与请求一致")
    phone = serializers.CharField(help_text="地图服务公开联系电话；无号码时为空字符串")
    distance_m = serializers.IntegerField(help_text="当前位置到地点的直线距离，单位为米")
    distance_text = serializers.CharField(help_text="前端可直接展示的距离文案")
    selection_token = serializers.CharField(help_text="用于下单确认的短期地点选择凭证")
    selection_expires_at = serializers.DateTimeField(help_text="地点选择凭证过期时间")


class LocationSearchResponseSerializer(serializers.Serializer):
    """地点周边搜索统一响应。"""

    query_keyword = serializers.CharField(help_text="本次实际提交给地图服务的搜索词")
    quick_keyword_code = serializers.CharField(help_text="快捷关键词代码；自由搜索时为空")
    center = serializers.DictField(help_text="搜索中心纬度和经度")
    coordinate_system = serializers.CharField(help_text="响应坐标系")
    radius_m = serializers.IntegerField(help_text="搜索半径，单位为米")
    provider = serializers.CharField(help_text="地图服务提供商标识")
    provider_total = serializers.IntegerField(help_text="地图服务返回的原始结果数量")
    items = LocationSearchItemSerializer(many=True, help_text="通过公共场所规则过滤后的地点")
    filtered_count = serializers.IntegerField(help_text="因分类或地址规则被过滤的结果数量")


class LocationQuickKeywordResponseSerializer(serializers.Serializer):
    """前端地点快捷搜索关键词。"""

    keyword_id = serializers.CharField(help_text="快捷关键词对外标识")
    code = serializers.CharField(help_text="快捷关键词稳定代码")
    label = serializers.CharField(help_text="前端展示名称")
    query_keyword = serializers.CharField(help_text="提交给地图服务的搜索关键词")
    icon = serializers.CharField(help_text="前端图标标识或静态资源名称")
    sort_order = serializers.IntegerField(help_text="展示排序值")


class LocationQuickKeywordAdminResponseSerializer(LocationQuickKeywordResponseSerializer):
    """管理员地点快捷关键词配置。"""

    enabled = serializers.BooleanField(help_text="是否允许前端使用")
    version = serializers.IntegerField(help_text="配置乐观锁版本号")
    created_at = serializers.DateTimeField(help_text="配置创建时间")
    updated_at = serializers.DateTimeField(help_text="配置最近更新时间")


class LocationQuickKeywordListResponseSerializer(serializers.Serializer):
    """地点快捷关键词列表响应。"""

    items = LocationQuickKeywordResponseSerializer(
        many=True,
        help_text="启用中的快捷关键词列表",
    )
    total = serializers.IntegerField(help_text="返回的快捷关键词数量")


class LocationQuickKeywordAdminListResponseSerializer(serializers.Serializer):
    """管理员地点快捷关键词列表响应。"""

    items = LocationQuickKeywordAdminResponseSerializer(
        many=True,
        help_text="快捷关键词配置列表",
    )
    total = serializers.IntegerField(help_text="快捷关键词配置总数")


class LocationQuickKeywordCreateSerializer(serializers.Serializer):
    """管理员创建地点快捷关键词请求。"""

    code = serializers.CharField(max_length=64, help_text="快捷关键词稳定代码")
    label = serializers.CharField(max_length=50, help_text="前端展示名称")
    query_keyword = serializers.CharField(max_length=100, help_text="提交给地图服务的搜索关键词")
    icon = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=255,
        help_text="前端图标标识或静态资源名称",
    )
    sort_order = serializers.IntegerField(
        required=False,
        min_value=0,
        default=0,
        help_text="展示排序值，数值越小越靠前",
    )
    enabled = serializers.BooleanField(
        required=False,
        default=True,
        help_text="是否允许前端使用该快捷关键词",
    )


class LocationQuickKeywordUpdateSerializer(serializers.Serializer):
    """管理员更新地点快捷关键词请求。"""

    expected_version = serializers.IntegerField(min_value=1, help_text="当前配置版本号")
    label = serializers.CharField(required=False, max_length=50, help_text="前端展示名称")
    query_keyword = serializers.CharField(
        required=False,
        max_length=100,
        help_text="提交给地图服务的搜索关键词",
    )
    icon = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=255,
        help_text="前端图标标识或静态资源名称",
    )
    sort_order = serializers.IntegerField(
        required=False,
        min_value=0,
        help_text="展示排序值，数值越小越靠前",
    )
    enabled = serializers.BooleanField(required=False, help_text="是否允许前端使用")


class LocationQuickKeywordDeactivateSerializer(serializers.Serializer):
    """管理员停用地点快捷关键词请求。"""

    expected_version = serializers.IntegerField(min_value=1, help_text="当前配置版本号")


class ProviderLocationUpdateSerializer(serializers.Serializer):
    """服务者登录后更新当前模糊位置的请求。"""

    latitude = serializers.FloatField(help_text="服务者当前位置纬度")
    longitude = serializers.FloatField(help_text="服务者当前位置经度")
    coordinate_system = serializers.ChoiceField(
        choices=["GCJ02", "WGS84"],
        default="GCJ02",
        help_text="客户端坐标系，支持 GCJ02 或 WGS84",
    )
    accuracy_m = serializers.IntegerField(
        required=False,
        min_value=0,
        max_value=10000,
        default=0,
        help_text="客户端定位精度，单位为米",
    )
    source = serializers.ChoiceField(
        choices=["LOGIN", "PERIODIC", "MANUAL"],
        default="LOGIN",
        help_text="定位更新来源，登录更新默认 LOGIN",
    )
    privacy_version = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=32,
        help_text="用户确认的位置隐私授权版本",
    )


class ProviderLocationStatusResponseSerializer(serializers.Serializer):
    """服务者位置状态响应，不返回经纬度。"""

    location_status = serializers.CharField(help_text="位置状态：ACTIVE 或 REVOKED")
    location_freshness = serializers.CharField(help_text="位置新鲜度：CURRENT 或 UNKNOWN")
    expires_at = serializers.DateTimeField(allow_null=True, help_text="位置有效期")
    version = serializers.IntegerField(help_text="位置状态版本号")
