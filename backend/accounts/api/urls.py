from django.urls import path

from backend.accounts.api.views import (
    DevPasswordLoginView,
    InitialRoleView,
    LoginView,
    LogoutView,
    MeView,
    RefreshView,
    SmsCodeView,
)

urlpatterns = [
    path("auth/sms-code/", SmsCodeView.as_view(), name="auth-sms-code"),
    path("auth/login/", LoginView.as_view(), name="auth-login"),
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
