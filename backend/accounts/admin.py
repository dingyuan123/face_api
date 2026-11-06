from __future__ import annotations

from typing import ClassVar

from django import forms
from django.contrib import admin
from django.contrib.auth.forms import AuthenticationForm

from backend.accounts.models import AuthToken, User, UserAuth, VerificationCode
from backend.accounts.services import hash_phone, normalize_phone
from backend.catalog.models import (
    ProviderService,
    ProviderTag,
    ServiceCategory,
    ServiceTag,
)
from backend.content.models import Moment, MomentTag
from backend.media.models import MediaAsset
from backend.profiles.models import InterestTag, ProfileCityOption
from backend.providers.models import ProviderApplication, ProviderProfile


class PhoneAuthenticationForm(AuthenticationForm):
    """使用手机号登录 Django Admin，内部转换为手机号 HMAC。"""

    username = forms.CharField(label="手机号", max_length=20)

    def clean_username(self) -> str:
        return hash_phone(normalize_phone(self.cleaned_data["username"]))


admin.site.login_form = PhoneAuthenticationForm
admin.site.site_header = "见面聊运营管理"
admin.site.site_title = "见面聊后台"
admin.site.index_title = "业务数据概览"


class ReadOnlyModelAdmin(admin.ModelAdmin):
    """开发期只读模型后台，业务状态修改继续调用 API 服务。"""

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(User)
class UserAdmin(ReadOnlyModelAdmin):
    list_display: ClassVar[tuple[str, ...]] = (
        "phone_masked",
        "status",
        "primary_role",
        "provider_status",
        "is_staff",
        "created_at",
    )
    search_fields: ClassVar[tuple[str, ...]] = ("phone_masked", "phone_hash", "public_id")
    list_filter: ClassVar[tuple[str, ...]] = ("status", "provider_status", "is_staff")
    readonly_fields: ClassVar[tuple[str, ...]] = (
        "public_id",
        "password",
        "phone_hash",
        "phone_masked",
        "status",
        "initial_role_selected",
        "primary_role",
        "default_workspace",
        "initial_role_selected_at",
        "provider_status",
        "provider_enabled",
        "is_staff",
        "created_at",
        "updated_at",
        "last_login_at",
        "last_login",
    )


@admin.register(UserAuth)
class UserAuthAdmin(ReadOnlyModelAdmin):
    list_display: ClassVar[tuple[str, ...]] = ("user", "auth_type", "status", "verified_at")
    search_fields: ClassVar[tuple[str, ...]] = ("user__phone_masked", "auth_identifier")


@admin.register(AuthToken)
class AuthTokenAdmin(ReadOnlyModelAdmin):
    list_display: ClassVar[tuple[str, ...]] = ("user", "token_type", "expires_at", "revoked_at")
    search_fields: ClassVar[tuple[str, ...]] = ("user__phone_masked", "public_id")


@admin.register(VerificationCode)
class VerificationCodeAdmin(ReadOnlyModelAdmin):
    list_display: ClassVar[tuple[str, ...]] = (
        "phone_masked",
        "purpose",
        "expires_at",
        "consumed_at",
    )
    search_fields: ClassVar[tuple[str, ...]] = ("phone_masked",)


@admin.register(ProviderApplication)
class ProviderApplicationAdmin(ReadOnlyModelAdmin):
    list_display: ClassVar[tuple[str, ...]] = (
        "application_no",
        "user",
        "status",
        "submitted_at",
        "reviewed_at",
    )
    search_fields: ClassVar[tuple[str, ...]] = ("application_no", "user__phone_masked")
    list_filter: ClassVar[tuple[str, ...]] = ("status",)


@admin.register(ProviderProfile)
class ProviderProfileAdmin(ReadOnlyModelAdmin):
    list_display: ClassVar[tuple[str, ...]] = ("user", "nickname", "updated_at")
    search_fields: ClassVar[tuple[str, ...]] = ("nickname", "user__phone_masked")


@admin.register(ProviderService)
class ProviderServiceAdmin(ReadOnlyModelAdmin):
    list_display: ClassVar[tuple[str, ...]] = (
        "public_id",
        "provider_user",
        "title",
        "status",
        "price_amount_minor",
        "updated_at",
    )
    search_fields: ClassVar[tuple[str, ...]] = ("title", "public_id", "provider_user__phone_masked")
    list_filter: ClassVar[tuple[str, ...]] = ("status", "category")


@admin.register(Moment)
class MomentAdmin(ReadOnlyModelAdmin):
    list_display: ClassVar[tuple[str, ...]] = (
        "public_id",
        "provider_user",
        "status",
        "visibility",
        "published_at",
    )
    search_fields: ClassVar[tuple[str, ...]] = (
        "content",
        "public_id",
        "provider_user__phone_masked",
    )
    list_filter: ClassVar[tuple[str, ...]] = ("status", "visibility")


@admin.register(MediaAsset)
class MediaAssetAdmin(ReadOnlyModelAdmin):
    list_display: ClassVar[tuple[str, ...]] = (
        "public_id",
        "owner",
        "purpose",
        "status",
        "created_at",
    )
    search_fields: ClassVar[tuple[str, ...]] = ("public_id", "owner__phone_masked")
    list_filter: ClassVar[tuple[str, ...]] = ("purpose", "status")


@admin.register(ServiceCategory, ServiceTag, ProviderTag, MomentTag, InterestTag, ProfileCityOption)
class ConfigReadOnlyAdmin(ReadOnlyModelAdmin):
    list_display: ClassVar[tuple[str, ...]] = ("__str__",)
