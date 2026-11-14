"""开发测试管理后台的查询和人工审核页面。"""

from __future__ import annotations

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from backend.common.exceptions import ApiError
from backend.identity.models import IdentityVerification
from backend.identity.services import (
    identity_verification_payload,
    review_real_name_verification,
)
from backend.providers.models import ProviderApplication
from backend.providers.services import application_payload, review_application


def _pagination(request: HttpRequest, total: int, page_size: int = 20) -> tuple[int, int]:
    try:
        page = max(1, int(request.GET.get("page", "1")))
    except ValueError:
        page = 1
    return page, (page - 1) * page_size


def _error_message(exc: Exception) -> str:
    if isinstance(exc, ApiError):
        return str(exc.message)
    return "操作失败，请稍后重试"


@staff_member_required
def dashboard(request: HttpRequest) -> HttpResponse:
    """展示审核工作量总览。"""
    identity_rows = (
        IdentityVerification.objects.filter(verification_type=IdentityVerification.Type.REAL_NAME)
        .values("status")
        .annotate(count=Count("id"))
    )
    provider_rows = ProviderApplication.objects.values("status").annotate(count=Count("id"))
    return render(
        request,
        "adminops/dashboard.html",
        {
            "identity_counts": {row["status"]: row["count"] for row in identity_rows},
            "provider_counts": {row["status"]: row["count"] for row in provider_rows},
            "identity_total": IdentityVerification.objects.filter(
                verification_type=IdentityVerification.Type.REAL_NAME
            ).count(),
            "provider_total": ProviderApplication.objects.count(),
        },
    )


@staff_member_required
def identity_list(request: HttpRequest) -> HttpResponse:
    """展示普通用户实名认证审核列表。"""
    queryset = IdentityVerification.objects.select_related("user").filter(
        verification_type=IdentityVerification.Type.REAL_NAME
    )
    status = request.GET.get("status", "")
    if status:
        queryset = queryset.filter(status=status)
    page, offset = _pagination(request, queryset.count())
    items = [
        identity_verification_payload(item, user=item.user, request=request)
        for item in queryset.order_by("-submitted_at", "-id")[offset : offset + 20]
    ]
    return render(
        request,
        "adminops/identity_list.html",
        {
            "items": items,
            "status": status,
            "page": page,
            "total": queryset.count(),
            "status_choices": IdentityVerification.Status.choices,
        },
    )


@staff_member_required
def identity_detail(request: HttpRequest, verification_no: str) -> HttpResponse:
    """展示实名认证资料和人工审核表单。"""
    verification = (
        IdentityVerification.objects.select_related("user")
        .filter(verification_no=verification_no)
        .first()
    )
    if verification is None:
        return render(request, "adminops/not_found.html", status=404)
    return render(
        request,
        "adminops/identity_detail.html",
        {
            "item": identity_verification_payload(
                verification,
                user=verification.user,
                request=request,
            ),
            "error": request.GET.get("error", ""),
        },
    )


@staff_member_required
@require_POST
def identity_review(
    request: HttpRequest,
    verification_no: str,
) -> HttpResponse:
    """提交实名认证人工审核结果。"""
    verification = IdentityVerification.objects.filter(verification_no=verification_no).first()
    if verification is None:
        return render(request, "adminops/not_found.html", status=404)
    try:
        review_real_name_verification(
            verification_no=str(verification_no),
            approve=request.POST.get("action") == "approve",
            reason=request.POST.get("reason", ""),
            expected_version=int(request.POST.get("expected_version", "0")),
            reviewer=request.user,
        )
    except (ApiError, ValueError) as exc:
        return redirect(
            reverse("management-identity-detail", args=[verification_no])
            + f"?error={_error_message(exc)}"
        )
    return redirect("management-identity-detail", verification_no=verification_no)


@staff_member_required
def provider_application_list(request: HttpRequest) -> HttpResponse:
    """展示服务者入驻申请审核列表。"""
    queryset = ProviderApplication.objects.select_related("user")
    status = request.GET.get("status", "")
    if status:
        queryset = queryset.filter(status=status)
    page, offset = _pagination(request, queryset.count())
    items = [
        application_payload(item, item.user, request)
        for item in queryset.order_by("-submitted_at", "-id")[offset : offset + 20]
    ]
    return render(
        request,
        "adminops/provider_list.html",
        {
            "items": items,
            "status": status,
            "page": page,
            "total": queryset.count(),
            "status_choices": ProviderApplication.Status.choices,
        },
    )


@staff_member_required
def provider_application_detail(
    request: HttpRequest,
    application_no: str,
) -> HttpResponse:
    """展示服务者申请资料和人工审核表单。"""
    application = (
        ProviderApplication.objects.select_related("user")
        .filter(application_no=application_no)
        .first()
    )
    if application is None:
        return render(request, "adminops/not_found.html", status=404)
    return render(
        request,
        "adminops/provider_detail.html",
        {
            "item": application_payload(application, application.user, request),
            "error": request.GET.get("error", ""),
        },
    )


@staff_member_required
@require_POST
def provider_application_review(
    request: HttpRequest,
    application_no: str,
) -> HttpResponse:
    """提交服务者申请审核结果。"""
    application = ProviderApplication.objects.filter(application_no=application_no).first()
    if application is None:
        return render(request, "adminops/not_found.html", status=404)
    try:
        review_application(
            application_no=application_no,
            approve=request.POST.get("action") == "approve",
            reviewer=request.user,
            reason=request.POST.get("reason", ""),
            expected_version=int(request.POST.get("expected_version", "0")),
        )
    except (ApiError, ValueError) as exc:
        return redirect(
            reverse("management-provider-detail", args=[application_no])
            + f"?error={_error_message(exc)}"
        )
    return redirect("management-provider-detail", application_no=application_no)
