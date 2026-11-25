from django.urls import path

from backend.accounts.api.deletion_views import (
    AccountDeletionCheckView,
    AccountDeletionSmsView,
    AccountDeletionView,
)
from backend.accounts.api.security_views import (
    AccountSecurityView,
    PasswordChangeSmsView,
    PasswordChangeView,
    PasswordForgotSmsView,
    PasswordResetView,
    PhoneChangeConfirmView,
    PhoneChangeRequestView,
)
from backend.accounts.api.views import (
    AppleLoginView,
    DevPasswordLoginView,
    InitialRoleView,
    LoginView,
    LogoutView,
    MeView,
    PasswordLoginView,
    PhoneBindingView,
    RefreshView,
    SmsCodeView,
    WeChatLoginView,
)

urlpatterns = [
    path(
        "users/me/security/",
        AccountSecurityView.as_view(),
        name="users-me-security",
    ),
    path(
        "users/me/password/sms-code/",
        PasswordChangeSmsView.as_view(),
        name="users-me-password-sms-code",
    ),
    path(
        "users/me/password/",
        PasswordChangeView.as_view(),
        name="users-me-password",
    ),
    path(
        "auth/password/forgot/sms-code/",
        PasswordForgotSmsView.as_view(),
        name="auth-password-forgot-sms-code",
    ),
    path(
        "auth/password/reset/",
        PasswordResetView.as_view(),
        name="auth-password-reset",
    ),
    path(
        "users/me/phone-change/",
        PhoneChangeRequestView.as_view(),
        name="users-me-phone-change",
    ),
    path(
        "users/me/phone-change/confirm/",
        PhoneChangeConfirmView.as_view(),
        name="users-me-phone-change-confirm",
    ),
    path(
        "account/deletion/check/",
        AccountDeletionCheckView.as_view(),
        name="account-deletion-check",
    ),
    path(
        "account/deletion/sms-code/",
        AccountDeletionSmsView.as_view(),
        name="account-deletion-sms-code",
    ),
    path(
        "account/deletion/",
        AccountDeletionView.as_view(),
        name="account-deletion",
    ),
    path("auth/sms-code/", SmsCodeView.as_view(), name="auth-sms-code"),
    path("auth/login/", LoginView.as_view(), name="auth-login"),
    path(
        "auth/password/login/",
        PasswordLoginView.as_view(),
        name="auth-password-login",
    ),
    path("auth/apple/login/", AppleLoginView.as_view(), name="auth-apple-login"),
    path("auth/wechat/login/", WeChatLoginView.as_view(), name="auth-wechat-login"),
    path(
        "users/me/phone-binding/",
        PhoneBindingView.as_view(),
        name="users-me-phone-binding",
    ),
    path(
        "dev/auth/password-login/",
        DevPasswordLoginView.as_view(),
        name="auth-dev-password-login",
    ),
    path("auth/refresh/", RefreshView.as_view(), name="auth-refresh"),
    path("auth/logout/", LogoutView.as_view(), name="auth-logout"),
    path("users/me/", MeView.as_view(), name="users-me"),
    path("users/me/initial-role/", InitialRoleView.as_view(), name="users-me-initial-role"),
]
