"""分享邀请落地页路由。"""

from django.urls import path

from backend.referrals.landing_views import invite_landing_view

urlpatterns = [
    path("invite/", invite_landing_view, name="invite-landing"),
    path("invite", invite_landing_view, name="invite-landing-no-slash"),
]
