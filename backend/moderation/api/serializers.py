"""内容举报和敏感词接口模型。"""

from __future__ import annotations

from rest_framework import serializers


class ContentReportCreateRequestSerializer(serializers.Serializer):
    """用户提交内容举报。"""

    target_type = serializers.ChoiceField(
        choices=["MOMENT", "NEWS", "USER", "SERVICE"],
        help_text="举报对象类型",
    )
    target_id = serializers.CharField(max_length=128, help_text="举报对象业务标识")
    reason = serializers.CharField(min_length=2, max_length=500, help_text="举报原因")
    evidence_urls = serializers.ListField(
        child=serializers.URLField(),
        required=False,
        help_text="证据地址，最多 9 项",
    )


class ContentReportResponseSerializer(serializers.Serializer):
    """举报安全摘要。"""

    report_no = serializers.UUIDField(help_text="举报业务 UUID")
    reporter_public_id = serializers.UUIDField(help_text="举报人用户 UUID")
    target_type = serializers.CharField(help_text="举报对象类型")
    target_type_text = serializers.CharField(help_text="举报对象类型中文含义")
    target_id = serializers.CharField(help_text="举报对象标识")
    reason = serializers.CharField(help_text="举报原因")
    evidence_urls = serializers.ListField(help_text="证据地址")
    status = serializers.CharField(help_text="处理状态")
    status_text = serializers.CharField(help_text="处理状态中文含义")
    resolution = serializers.CharField(help_text="处理结论")
    handled_at = serializers.DateTimeField(allow_null=True, help_text="处理时间")
    version = serializers.IntegerField(help_text="举报版本号")
    created_at = serializers.DateTimeField(help_text="举报创建时间")
    updated_at = serializers.DateTimeField(help_text="举报更新时间")


class ContentReportListResponseSerializer(serializers.Serializer):
    """举报分页响应。"""

    items = ContentReportResponseSerializer(many=True, help_text="举报列表")
    total = serializers.IntegerField(help_text="举报总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")


class ContentReportReviewRequestSerializer(serializers.Serializer):
    """管理员处理举报。"""

    expected_version = serializers.IntegerField(min_value=1, help_text="举报版本号")
    resolution = serializers.CharField(min_length=2, max_length=500, help_text="处理结论")


class SensitiveWordRequestSerializer(serializers.Serializer):
    """创建敏感词。"""

    word = serializers.CharField(max_length=100, help_text="敏感词")
    category = serializers.CharField(required=False, default="DEFAULT", help_text="分类")
    action = serializers.ChoiceField(
        choices=["BLOCK", "REVIEW"],
        required=False,
        default="REVIEW",
        help_text="命中动作",
    )
    status = serializers.ChoiceField(
        choices=["ACTIVE", "DISABLED"],
        required=False,
        default="ACTIVE",
        help_text="启用状态",
    )


class SensitiveWordUpdateRequestSerializer(serializers.Serializer):
    """修改敏感词。"""

    expected_version = serializers.IntegerField(min_value=1, help_text="敏感词版本号")
    category = serializers.CharField(required=False, help_text="分类")
    action = serializers.ChoiceField(choices=["BLOCK", "REVIEW"], required=False)
    status = serializers.ChoiceField(choices=["ACTIVE", "DISABLED"], required=False)


class SensitiveWordResponseSerializer(serializers.Serializer):
    """敏感词安全摘要。"""

    word_id = serializers.IntegerField(help_text="敏感词 ID")
    word = serializers.CharField(help_text="敏感词")
    category = serializers.CharField(help_text="分类")
    action = serializers.CharField(help_text="命中动作")
    action_text = serializers.CharField(help_text="命中动作中文含义")
    status = serializers.CharField(help_text="状态")
    status_text = serializers.CharField(help_text="状态中文含义")
    version = serializers.IntegerField(help_text="版本号")
    created_at = serializers.DateTimeField(help_text="创建时间")
    updated_at = serializers.DateTimeField(help_text="更新时间")


class SensitiveWordListResponseSerializer(serializers.Serializer):
    """敏感词分页响应。"""

    items = SensitiveWordResponseSerializer(many=True, help_text="敏感词列表")
    total = serializers.IntegerField(help_text="敏感词总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")
