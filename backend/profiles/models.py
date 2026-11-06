from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower


class InterestTag(models.Model):
    """可配置的兴趣标签目录。"""

    id = models.BigAutoField(primary_key=True, db_comment="兴趣标签自增主键")
    code = models.CharField(
        max_length=32,
        unique=True,
        db_comment="稳定标签代码，接口保存时使用，不随展示名称变化",
    )
    name = models.CharField(max_length=50, db_comment="兴趣标签中文展示名称")
    category = models.CharField(max_length=32, db_comment="兴趣标签分类名称")
    sort_order = models.PositiveIntegerField(default=0, db_comment="标签展示排序值，数值小的优先")
    is_active = models.BooleanField(default=True, db_comment="标签是否可被用户选择")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="标签创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="标签最近更新时间")

    class Meta:
        db_table = "profile_interest_tags"
        db_table_comment = "用户兴趣标签配置表"
        ordering: ClassVar[list[str]] = ["sort_order", "id"]


class ProfileCityOption(models.Model):
    """个人资料可选城市代码配置。"""

    id = models.BigAutoField(primary_key=True, db_comment="城市选项自增主键")
    code = models.CharField(max_length=32, unique=True, db_comment="稳定城市代码")
    name = models.CharField(max_length=50, db_comment="城市中文展示名称")
    sort_order = models.PositiveIntegerField(default=0, db_comment="城市展示排序值")
    is_active = models.BooleanField(default=True, db_comment="城市是否允许选择")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="城市选项创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="城市选项最近更新时间")

    class Meta:
        db_table = "profile_city_options"
        db_table_comment = "个人资料城市代码配置表"
        ordering: ClassVar[list[str]] = ["sort_order", "id"]


class UserProfile(models.Model):
    """当前用户可编辑的个人资料主表。"""

    class Gender(models.TextChoices):
        MALE = "MALE", "男"
        FEMALE = "FEMALE", "女"

    id = models.BigAutoField(primary_key=True, db_comment="个人资料自增主键")
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
        db_comment="资料所属用户，一个用户只有一份资料",
    )
    nickname = models.CharField(
        max_length=30,
        null=True,
        blank=True,
        db_comment="个人昵称；填写后在全平台忽略大小写唯一",
    )
    avatar_media_id = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        db_comment="个人头像媒体 UUID；只允许引用本人个人头像媒体",
    )
    gender = models.CharField(
        max_length=16,
        choices=Gender.choices,
        null=True,
        blank=True,
        db_comment="性别：男或女；未填写时为空",
    )
    age = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        db_comment="用户填写年龄，允许范围为 18 到 40 岁",
    )
    city_code = models.CharField(
        max_length=32,
        default=settings.PROFILE_DEFAULT_CITY_CODE,
        db_comment="个人资料城市稳定代码",
    )
    signature = models.CharField(
        max_length=100,
        blank=True,
        default="",
        db_comment="个人个性签名，最多 100 个字符",
    )
    trust_level_code = models.CharField(
        max_length=32,
        blank=True,
        default="UNSET",
        db_comment="安心用户等级代码；当前仅预留，等级规则尚未接入",
    )
    trust_level_name = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_comment="安心用户等级展示名；当前仅预留，等级规则尚未接入",
    )
    trust_level_updated_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="安心用户等级最近维护时间；当前仅预留",
    )
    version = models.PositiveIntegerField(default=1, db_comment="个人资料乐观锁版本号")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="个人资料创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="个人资料最近更新时间")

    class Meta:
        db_table = "user_profiles"
        db_table_comment = "用户个人资料主表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                Lower("nickname"),
                name="uniq_user_profile_nickname_ci",
            ),
            models.CheckConstraint(
                condition=models.Q(age__isnull=True) | models.Q(age__gte=18, age__lte=40),
                name="check_user_profile_age_range",
            ),
            models.CheckConstraint(
                condition=models.Q(gender__isnull=True) | models.Q(gender__in=["MALE", "FEMALE"]),
                name="check_user_profile_gender",
            ),
        ]

    def __str__(self) -> str:
        return f"UserProfile({self.nickname or self.user_id})"


class UserProfileInterest(models.Model):
    """用户资料与兴趣标签的有序关联表。"""

    id = models.BigAutoField(primary_key=True, db_comment="用户兴趣关联自增主键")
    profile = models.ForeignKey(
        UserProfile,
        on_delete=models.CASCADE,
        related_name="interest_links",
        db_comment="所属个人资料；资料删除时同步删除关联",
    )
    tag = models.ForeignKey(
        InterestTag,
        on_delete=models.PROTECT,
        related_name="profile_links",
        db_comment="被选择的兴趣标签；存在用户引用时禁止直接删除",
    )
    sort_order = models.PositiveSmallIntegerField(
        default=0,
        db_comment="用户选择标签的展示顺序",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="标签选择时间")

    class Meta:
        db_table = "user_profile_interests"
        db_table_comment = "用户资料与兴趣标签关联表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["profile", "tag"],
                name="uniq_user_profile_interest_tag",
            )
        ]
        ordering: ClassVar[list[str]] = ["sort_order", "id"]
