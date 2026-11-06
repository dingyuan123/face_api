"""资讯公开查询、管理员维护、来源同步和分享接口的 OpenAPI 数据模型。"""

from __future__ import annotations

from rest_framework import serializers

from backend.media.api.serializers import MediaAssetSummarySerializer


class NewsCategoryResponseSerializer(serializers.Serializer):
    """资讯类目配置响应。"""

    code = serializers.CharField(help_text="资讯类目稳定代码")
    name = serializers.CharField(help_text="资讯类目展示名称")
    sort_order = serializers.IntegerField(help_text="资讯类目展示排序值")


class NewsAttachmentResponseSerializer(serializers.Serializer):
    """资讯图片、视频或链接附件响应。"""

    type = serializers.ChoiceField(
        choices=["IMAGE", "VIDEO", "LINK"],
        help_text="附件类型",
    )
    media = MediaAssetSummarySerializer(
        allow_null=True,
        help_text="平台图片媒体摘要；外部附件为空",
    )
    url = serializers.CharField(help_text="外部附件安全 URL")
    title = serializers.CharField(help_text="附件展示标题")
    position = serializers.IntegerField(help_text="附件展示顺序")


class NewsMerchantSummarySerializer(serializers.Serializer):
    """商家展示卡片快照，本期不提供商家检索和地点选择。"""

    name = serializers.CharField(help_text="商家展示名称")
    address = serializers.CharField(help_text="商家展示地址")
    city_code = serializers.CharField(help_text="商家城市代码")


class NewsMountResponseSerializer(serializers.Serializer):
    """资讯服务者、服务、商家或链接卡片响应。"""

    mount_type = serializers.ChoiceField(
        choices=["PROVIDER", "SERVICE", "MERCHANT", "LINK"],
        help_text="挂载卡片类型",
    )
    target_public_id = serializers.UUIDField(
        allow_null=True,
        help_text="服务者或服务公开 UUID；商家和纯链接为空",
    )
    title = serializers.CharField(help_text="卡片标题")
    subtitle = serializers.CharField(help_text="卡片副标题或摘要")
    cover_media = MediaAssetSummarySerializer(
        allow_null=True,
        help_text="卡片平台封面媒体摘要",
    )
    cover_url = serializers.CharField(help_text="卡片外部封面 URL")
    external_url = serializers.CharField(help_text="卡片跳转 URL")
    merchant = NewsMerchantSummarySerializer(
        allow_null=True,
        help_text="商家展示快照；非商家卡片为空",
    )
    position = serializers.IntegerField(help_text="卡片展示顺序")


class NewsArticleResponseSerializer(serializers.Serializer):
    """资讯文章安全响应。"""

    news_id = serializers.UUIDField(help_text="资讯公开 UUID")
    title = serializers.CharField(help_text="资讯标题")
    summary = serializers.CharField(help_text="资讯摘要")
    body = serializers.CharField(help_text="资讯正文；外部摘要资讯通常为空")
    cover_media = MediaAssetSummarySerializer(
        allow_null=True,
        help_text="资讯平台封面媒体摘要",
    )
    cover_url = serializers.CharField(help_text="资讯外部封面 URL")
    author = serializers.CharField(help_text="文章作者署名")
    source_name = serializers.CharField(help_text="来源展示名称")
    source_url = serializers.CharField(help_text="外部原文链接")
    country_code = serializers.CharField(help_text="国家或地区代码")
    city_code = serializers.CharField(help_text="城市代码")
    language_code = serializers.CharField(help_text="内容语言代码")
    category_codes = serializers.ListField(
        child=serializers.CharField(),
        help_text="资讯类目代码列表",
    )
    attachments = NewsAttachmentResponseSerializer(
        many=True,
        help_text="资讯附件列表",
    )
    mounts = NewsMountResponseSerializer(many=True, help_text="资讯关联展示卡片")
    status = serializers.CharField(help_text="资讯状态")
    is_featured = serializers.BooleanField(help_text="是否重点展示")
    allow_recommend = serializers.BooleanField(help_text="是否允许推荐")
    view_count = serializers.IntegerField(help_text="浏览次数")
    version = serializers.IntegerField(help_text="资讯乐观锁版本号")
    source_published_at = serializers.DateTimeField(
        allow_null=True,
        help_text="外部来源声明的原文发布时间",
    )
    published_at = serializers.DateTimeField(
        allow_null=True,
        help_text="平台对外发布时间",
    )
    created_at = serializers.DateTimeField(help_text="资讯创建时间")
    updated_at = serializers.DateTimeField(help_text="资讯最近更新时间")


class NewsListResponseSerializer(serializers.Serializer):
    """资讯分页列表响应。"""

    items = NewsArticleResponseSerializer(many=True, help_text="资讯列表")
    total = serializers.IntegerField(help_text="筛选后资讯总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")


class NewsAttachmentInputSerializer(serializers.Serializer):
    """资讯附件输入。"""

    type = serializers.ChoiceField(
        choices=["IMAGE", "VIDEO", "LINK"],
        default="IMAGE",
        help_text="附件类型",
    )
    media_id = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="平台资讯图片媒体 ID",
    )
    url = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="外部图片、视频或链接的 HTTP 或 HTTPS 地址",
    )
    title = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="附件展示标题",
    )


class NewsMountInputSerializer(serializers.Serializer):
    """资讯关联卡片输入。"""

    mount_type = serializers.ChoiceField(
        choices=["PROVIDER", "SERVICE", "MERCHANT", "LINK"],
        help_text="挂载卡片类型",
    )
    target_public_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="服务者或服务公开 UUID",
    )
    title = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="卡片标题；服务者和服务卡片可由后端补全",
    )
    subtitle = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="卡片副标题或摘要",
    )
    cover_media_id = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="卡片平台封面媒体 ID",
    )
    cover_url = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="卡片外部封面 URL",
    )
    external_url = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="卡片跳转 HTTP 或 HTTPS URL",
    )
    merchant_name = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="商家展示名称；本期只保存展示卡片",
    )
    merchant_address = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="商家展示地址",
    )
    merchant_city_code = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="商家城市代码，预留地点选择",
    )


class NewsArticleInputSerializer(serializers.Serializer):
    """管理员创建或编辑资讯输入。"""

    title = serializers.CharField(help_text="资讯标题，1 到 200 个字符")
    summary = serializers.CharField(help_text="资讯摘要，1 到 2000 个字符")
    body = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="资讯正文；仅原创或确认版权内容填写",
    )
    source_url = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="外部原文 HTTP 或 HTTPS 链接",
    )
    canonical_url = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="规范化原文链接；用于去重",
    )
    cover_url = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="外部封面图片 HTTP 或 HTTPS URL",
    )
    cover_media_id = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="管理员上传的资讯封面媒体 ID",
    )
    author = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="文章作者署名",
    )
    source_name = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="来源展示名称",
    )
    country_code = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="国家或地区代码",
    )
    city_code = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="城市代码",
    )
    language_code = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="内容语言代码",
    )
    category_codes = serializers.ListField(
        child=serializers.CharField(),
        help_text="资讯类目代码，至少 1 个",
    )
    attachments = NewsAttachmentInputSerializer(
        many=True,
        required=False,
        help_text="资讯附件列表，最多 20 个",
    )
    mounts = NewsMountInputSerializer(
        many=True,
        required=False,
        help_text="资讯服务者、服务、商家或链接卡片，最多 10 个",
    )
    is_featured = serializers.BooleanField(
        required=False,
        default=False,
        help_text="是否重点展示",
    )
    allow_recommend = serializers.BooleanField(
        required=False,
        default=True,
        help_text="是否允许推荐",
    )


class NewsVersionRequestSerializer(serializers.Serializer):
    """资讯编辑、审核和删除版本请求。"""

    expected_version = serializers.IntegerField(
        min_value=1,
        help_text="查询时返回的资讯版本号",
    )


class NewsUpdateRequestSerializer(NewsArticleInputSerializer, NewsVersionRequestSerializer):
    """管理员编辑资讯请求。"""


class NewsReviewRequestSerializer(NewsVersionRequestSerializer):
    """管理员审核发布或拒绝资讯请求。"""

    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="拒绝原因；拒绝时必填，发布时可省略",
    )


class NewsDeleteRequestSerializer(NewsVersionRequestSerializer):
    """管理员逻辑删除资讯请求。"""

    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="删除或下架原因",
    )


class NewsShareResponseSerializer(serializers.Serializer):
    """资讯分享链接响应。"""

    share_url = serializers.CharField(help_text="可公开访问的资讯分享链接")
    share_title = serializers.CharField(help_text="分享标题")
    share_summary = serializers.CharField(help_text="分享摘要")
    share_image_url = serializers.CharField(help_text="分享封面地址")


class NewsSourceResponseSerializer(serializers.Serializer):
    """外部资讯来源配置响应。"""

    code = serializers.CharField(help_text="来源稳定代码")
    name = serializers.CharField(help_text="来源展示名称")
    source_type = serializers.CharField(help_text="来源类型")
    feed_url = serializers.CharField(help_text="RSS 或 Atom 订阅地址")
    homepage_url = serializers.CharField(help_text="来源官网地址")
    country_code = serializers.CharField(help_text="来源国家或地区代码")
    language_code = serializers.CharField(help_text="来源语言代码")
    enabled = serializers.BooleanField(help_text="是否启用自动同步")
    fetch_interval_minutes = serializers.IntegerField(help_text="建议同步间隔，单位为分钟")
    attribution = serializers.CharField(help_text="来源署名")
    license_note = serializers.CharField(help_text="来源版权和使用限制")
    last_synced_at = serializers.DateTimeField(
        allow_null=True,
        help_text="最近成功同步时间",
    )


class NewsSourceInputSerializer(serializers.Serializer):
    """管理员创建或编辑外部资讯来源。"""

    code = serializers.CharField(help_text="来源稳定代码")
    name = serializers.CharField(help_text="来源展示名称")
    source_type = serializers.ChoiceField(
        choices=["RSS", "API", "MANUAL"],
        default="RSS",
        help_text="来源类型；当前自动同步支持 RSS 或 Atom",
    )
    feed_url = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="RSS 或 Atom HTTP 或 HTTPS 订阅地址",
    )
    homepage_url = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="来源官网地址",
    )
    country_code = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="来源国家或地区代码",
    )
    language_code = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="来源语言代码",
    )
    enabled = serializers.BooleanField(
        required=False,
        default=True,
        help_text="是否启用",
    )
    fetch_interval_minutes = serializers.IntegerField(
        required=False,
        default=60,
        help_text="建议同步间隔，5 到 1440 分钟",
    )
    attribution = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="来源署名",
    )
    license_note = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="版权和使用限制说明",
    )


class NewsSyncRequestSerializer(serializers.Serializer):
    """一键获取最新资讯请求。"""

    source_codes = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="来源代码列表；为空表示全部启用来源",
    )
    keyword = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="资讯关键词；来源地址支持 {keyword} 占位符时生效",
    )
    country_code = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="按来源国家或地区筛选",
    )
    language_code = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="按来源语言筛选",
    )
    limit = serializers.IntegerField(
        required=False,
        default=20,
        min_value=1,
        max_value=100,
        help_text="每个来源最多获取条数",
    )


class NewsSyncRunResponseSerializer(serializers.Serializer):
    """资讯同步任务执行结果。"""

    run_no = serializers.UUIDField(help_text="同步任务业务编号")
    status = serializers.CharField(help_text="同步任务状态")
    source_codes = serializers.ListField(
        child=serializers.CharField(),
        help_text="本次同步来源代码",
    )
    filters = serializers.DictField(help_text="同步筛选条件快照")
    fetched_count = serializers.IntegerField(help_text="外部源返回条数")
    created_count = serializers.IntegerField(help_text="新增资讯条数")
    updated_count = serializers.IntegerField(help_text="更新资讯条数")
    skipped_count = serializers.IntegerField(help_text="重复或无效跳过条数")
    failed_count = serializers.IntegerField(help_text="来源失败数")
    error_message = serializers.CharField(help_text="脱敏错误摘要")
    started_at = serializers.DateTimeField(allow_null=True, help_text="开始执行时间")
    finished_at = serializers.DateTimeField(allow_null=True, help_text="执行结束时间")
    created_at = serializers.DateTimeField(help_text="同步记录创建时间")
