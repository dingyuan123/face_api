"""优惠券用户查询领取和管理员模板、发放、撤销、核销审计接口。"""

from __future__ import annotations

from typing import ClassVar

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.accounts.authentication import BearerTokenAuthentication
from backend.accounts.models import User
from backend.adminops.auth import (
    AdminBearerTokenAuthentication,
    require_admin_permission,
    write_admin_operation,
)
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.coupons.api.serializers import (
    AdminCouponIssueRequestSerializer,
    AdminCouponIssueResponseSerializer,
    AdminCouponRevokeRequestSerializer,
    AdminCouponTemplateCreateRequestSerializer,
    AdminCouponTemplateListResponseSerializer,
    AdminCouponTemplateResponseSerializer,
    AdminCouponTemplateUpdateRequestSerializer,
    CouponClaimRequestSerializer,
    CouponClaimResponseSerializer,
    CouponListResponseSerializer,
    CouponRedemptionListResponseSerializer,
    CouponResponseSerializer,
)
from backend.coupons.models import CouponTemplate
from backend.coupons.services import (
    admin_coupon_template_payload,
    admin_issue_coupon,
    claim_coupon,
    create_coupon_template,
    get_user_coupon,
    list_admin_coupon_templates,
    list_admin_redemptions,
    list_user_coupons,
    revoke_coupon,
    update_coupon_template,
)


def _page_params(request: Request) -> tuple[int, int]:
    """解析统一管理分页参数并限制单页最大数量。"""
    try:
        page = max(1, int(request.query_params.get("page", 1)))
        page_size = min(100, max(1, int(request.query_params.get("page_size", 20))))
    except ValueError as exc:
        raise ApiError(
            ErrorCode.COUPON_INVALID,
            ERROR_MESSAGES[ErrorCode.COUPON_INVALID],
            status_code=400,
            details={"page": "分页参数必须是整数"},
        ) from exc
    return page, page_size


class CouponListView(APIView):
    """当前用户优惠券列表。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询我的优惠券",
        operation_id="listMyCoupons",
        parameters=[
            OpenApiParameter(
                "status",
                type=str,
                required=False,
                description="AVAILABLE、USED、EXPIRED 或 ALL，默认 AVAILABLE",
            ),
            OpenApiParameter("page", type=int, required=False, description="页码"),
            OpenApiParameter("page_size", type=int, required=False, description="每页数量"),
        ],
        responses={200: CouponListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        page, page_size = _page_params(request)
        return Response(
            list_user_coupons(
                user=request.user,
                status=request.query_params.get("status", "AVAILABLE"),
                page=page,
                page_size=page_size,
            )
        )


class CouponDetailView(APIView):
    """当前用户优惠券详情。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询优惠券详情",
        operation_id="getCoupon",
        responses={200: CouponResponseSerializer},
    )
    def get(self, request: Request, coupon_no: str) -> Response:
        return Response(get_user_coupon(user=request.user, coupon_no=coupon_no))


class CouponClaimView(APIView):
    """用户领取可领取优惠券。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="领取优惠券",
        operation_id="claimCoupon",
        request=CouponClaimRequestSerializer,
        responses={200: CouponClaimResponseSerializer, 201: CouponClaimResponseSerializer},
    )
    def post(self, request: Request, template_no: str) -> Response:
        serializer = CouponClaimRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        coupon, created = claim_coupon(
            user=request.user,
            template_no=template_no,
            idempotency_key=(
                serializer.validated_data.get("idempotency_key")
                or request.headers.get("Idempotency-Key")
            ),
        )
        return Response(
            {
                "coupon": get_user_coupon(user=request.user, coupon_no=str(coupon.coupon_no)),
                "created": created,
                "reused": not created,
            },
            status=201 if created else 200,
        )


class AdminCouponTemplateListCreateView(APIView):
    """管理员查询和创建优惠券模板。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询优惠券模板",
        operation_id="adminListCouponTemplates",
        parameters=[
            OpenApiParameter("status", type=str, required=False, description="模板状态筛选"),
            OpenApiParameter("page", type=int, required=False, description="页码"),
            OpenApiParameter("page_size", type=int, required=False, description="每页数量"),
        ],
        responses={200: AdminCouponTemplateListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        require_admin_permission(request.user, "admin.coupon.read")
        page, page_size = _page_params(request)
        return Response(
            list_admin_coupon_templates(
                status=request.query_params.get("status"),
                page=page,
                page_size=page_size,
            )
        )

    @extend_schema(
        summary="创建优惠券模板",
        operation_id="adminCreateCouponTemplate",
        request=AdminCouponTemplateCreateRequestSerializer,
        responses={201: AdminCouponTemplateResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        require_admin_permission(request.user, "admin.coupon.write")
        serializer = AdminCouponTemplateCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = create_coupon_template(operator=request.user, payload=serializer.validated_data)
        write_admin_operation(
            operator=request.user,
            action="COUPON_TEMPLATE_CREATE",
            target_type="COUPON_TEMPLATE",
            target_id=result["template_no"],
            after_state=result,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(result, status=201)


class AdminCouponTemplateDetailView(APIView):
    """管理员修改优惠券模板。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="修改优惠券模板",
        operation_id="adminUpdateCouponTemplate",
        request=AdminCouponTemplateUpdateRequestSerializer,
        responses={200: AdminCouponTemplateResponseSerializer},
    )
    def patch(self, request: Request, template_no: str) -> Response:
        require_admin_permission(request.user, "admin.coupon.write")
        serializer = AdminCouponTemplateUpdateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        expected_version = int(payload.pop("expected_version"))
        before_template = CouponTemplate.objects.filter(template_no=template_no).first()
        before = admin_coupon_template_payload(before_template) if before_template else None
        result = update_coupon_template(
            operator=request.user,
            template_no=template_no,
            payload=payload,
            expected_version=expected_version,
        )
        write_admin_operation(
            operator=request.user,
            action="COUPON_TEMPLATE_UPDATE",
            target_type="COUPON_TEMPLATE",
            target_id=result["template_no"],
            before_state=before,
            after_state=result,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(result)


class AdminCouponIssueView(APIView):
    """管理员向指定用户发放优惠券。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="管理员发放优惠券",
        operation_id="adminIssueCoupon",
        request=AdminCouponIssueRequestSerializer,
        responses={201: AdminCouponIssueResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        require_admin_permission(request.user, "admin.coupon.write")
        serializer = AdminCouponIssueRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        user = User.objects.filter(public_id=payload["user_public_id"]).first()
        if user is None:
            raise ApiError(
                ErrorCode.COUPON_NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.COUPON_NOT_FOUND],
                status_code=404,
            )
        result = admin_issue_coupon(operator=request.user, user=user, payload=payload)
        write_admin_operation(
            operator=request.user,
            action="COUPON_INSTANCE_ISSUE",
            target_type="COUPON_INSTANCE",
            target_id=result["coupon_no"],
            after_state=result,
            reason="管理员手动发放优惠券",
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(result, status=201 if result["created"] else 200)


class AdminCouponRevokeView(APIView):
    """管理员撤销未使用优惠券。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="撤销优惠券",
        operation_id="adminRevokeCoupon",
        request=AdminCouponRevokeRequestSerializer,
        responses={200: CouponResponseSerializer},
    )
    def post(self, request: Request, coupon_no: str) -> Response:
        require_admin_permission(request.user, "admin.coupon.write")
        serializer = AdminCouponRevokeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = revoke_coupon(
            coupon_no=coupon_no,
            reason=serializer.validated_data["reason"],
            operator_user_id=request.user.id,
            expected_version=serializer.validated_data["expected_version"],
        )
        write_admin_operation(
            operator=request.user,
            action="COUPON_INSTANCE_REVOKE",
            target_type="COUPON_INSTANCE",
            target_id=result["coupon_no"],
            after_state=result,
            reason=serializer.validated_data["reason"],
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(result)


class AdminCouponRedemptionListView(APIView):
    """管理员查询优惠券订单核销记录。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询优惠券核销记录",
        operation_id="adminListCouponRedemptions",
        parameters=[
            OpenApiParameter("status", type=str, required=False, description="核销状态筛选"),
            OpenApiParameter("page", type=int, required=False, description="页码"),
            OpenApiParameter("page_size", type=int, required=False, description="每页数量"),
        ],
        responses={200: CouponRedemptionListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        require_admin_permission(request.user, "admin.coupon.read")
        page, page_size = _page_params(request)
        return Response(
            list_admin_redemptions(
                status=request.query_params.get("status"),
                page=page,
                page_size=page_size,
            )
        )
