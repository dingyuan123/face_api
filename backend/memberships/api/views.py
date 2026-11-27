"""会员套餐查询、购买支付和管理员套餐配置接口。"""

from __future__ import annotations

from typing import ClassVar

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.accounts.authentication import BearerTokenAuthentication
from backend.adminops.auth import (
    AdminBearerTokenAuthentication,
    require_admin_permission,
    write_admin_operation,
)
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.memberships.api.serializers import (
    AdminMembershipPlanCreateRequestSerializer,
    AdminMembershipPlanUpdateRequestSerializer,
    AdminMembershipPurchaseListResponseSerializer,
    MembershipPlanListResponseSerializer,
    MembershipPlanResponseSerializer,
    MembershipPurchaseCreateRequestSerializer,
    MembershipPurchaseListResponseSerializer,
    MembershipPurchaseResponseSerializer,
    MembershipPurchaseResultSerializer,
    MembershipSummaryResponseSerializer,
)
from backend.memberships.services import (
    create_membership_plan,
    create_membership_purchase,
    get_membership_purchase,
    get_membership_summary,
    list_admin_membership_purchases,
    list_membership_plans,
    list_membership_purchases,
    plan_version_payload,
    purchase_payload,
    update_membership_plan,
)


def _page_params(request: Request) -> tuple[int, int]:
    """解析会员管理分页参数并限制最大页大小。"""
    try:
        page = max(1, int(request.query_params.get("page", 1)))
        page_size = min(100, max(1, int(request.query_params.get("page_size", 20))))
    except ValueError as exc:
        raise ApiError(
            ErrorCode.MEMBERSHIP_INVALID,
            ERROR_MESSAGES[ErrorCode.MEMBERSHIP_INVALID],
            status_code=400,
            details={"page": "分页参数必须是整数"},
        ) from exc
    return page, page_size


class MembershipPlanListView(APIView):
    """普通用户查询可购买会员套餐。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询会员套餐",
        operation_id="listMembershipPlans",
        responses={200: MembershipPlanListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response({"items": list_membership_plans()})


class MembershipSummaryView(APIView):
    """普通用户查询会员中心状态和权益。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询我的会员状态",
        operation_id="getMembershipSummary",
        responses={200: MembershipSummaryResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(get_membership_summary(user=request.user))


class MembershipPurchaseListCreateView(APIView):
    """普通用户查询购买历史和发起会员购买。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询会员购买历史",
        operation_id="listMembershipPurchases",
        parameters=[
            OpenApiParameter("page", type=int, required=False, description="页码"),
            OpenApiParameter("page_size", type=int, required=False, description="每页数量"),
        ],
        responses={200: MembershipPurchaseListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        page, page_size = _page_params(request)
        return Response(
            list_membership_purchases(
                user=request.user,
                page=page,
                page_size=page_size,
            )
        )

    @extend_schema(
        summary="购买或续费会员",
        operation_id="createMembershipPurchase",
        request=MembershipPurchaseCreateRequestSerializer,
        responses={
            200: MembershipPurchaseResultSerializer,
            201: MembershipPurchaseResultSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = MembershipPurchaseCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = create_membership_purchase(
            user=request.user,
            plan_code=serializer.validated_data["plan_code"],
            payment_method=serializer.validated_data["payment_method"],
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        result.purchase.refresh_from_db()
        payment = result.payment
        if payment is not None:
            payment.refresh_from_db()
        from backend.payments.services import payment_payload

        return Response(
            {
                "purchase": purchase_payload(result.purchase, payment=payment),
                "payment": payment_payload(payment) if payment is not None else None,
                "payment_action": result.payment_action,
                "created": result.created,
                "reused": result.reused,
            },
            status=201 if result.created else 200,
        )


class MembershipPurchaseDetailView(APIView):
    """普通用户查询本人会员购买单。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询会员购买详情",
        operation_id="getMembershipPurchase",
        responses={200: MembershipPurchaseResponseSerializer},
    )
    def get(self, request: Request, purchase_no: str) -> Response:
        return Response(get_membership_purchase(user=request.user, purchase_no=purchase_no))


class AdminMembershipPlanListCreateView(APIView):
    """管理员查询和创建会员套餐。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询会员套餐配置",
        operation_id="adminListMembershipPlans",
        responses={200: MembershipPlanListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        require_admin_permission(request.user, "admin.membership.read")
        return Response({"items": list_membership_plans(include_unavailable=True)})

    @extend_schema(
        summary="创建会员套餐",
        operation_id="adminCreateMembershipPlan",
        request=AdminMembershipPlanCreateRequestSerializer,
        responses={201: MembershipPlanResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        require_admin_permission(request.user, "admin.membership.write")
        serializer = AdminMembershipPlanCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = create_membership_plan(operator=request.user, payload=serializer.validated_data)
        write_admin_operation(
            operator=request.user,
            action="MEMBERSHIP_PLAN_CREATE",
            target_type="MEMBERSHIP_PLAN",
            target_id=result["plan_no"],
            after_state=result,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(result, status=201)


class AdminMembershipPlanDetailView(APIView):
    """管理员修改会员套餐并生成新的商业版本。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="修改会员套餐",
        operation_id="adminUpdateMembershipPlan",
        request=AdminMembershipPlanUpdateRequestSerializer,
        responses={200: MembershipPlanResponseSerializer},
    )
    def patch(self, request: Request, plan_no: str) -> Response:
        require_admin_permission(request.user, "admin.membership.write")
        serializer = AdminMembershipPlanUpdateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        expected_version = int(payload.pop("expected_version"))
        from backend.memberships.models import MembershipPlan

        plan = MembershipPlan.objects.filter(plan_no=plan_no).first()
        if plan is None:
            raise ApiError(
                ErrorCode.MEMBERSHIP_NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.MEMBERSHIP_NOT_FOUND],
                status_code=404,
            )
        current = plan.versions.filter(version_no=plan.version).first()
        before = plan_version_payload(current) if current else None
        result = update_membership_plan(
            operator=request.user,
            plan_no=plan_no,
            payload=payload,
            expected_version=expected_version,
        )
        write_admin_operation(
            operator=request.user,
            action="MEMBERSHIP_PLAN_UPDATE",
            target_type="MEMBERSHIP_PLAN",
            target_id=result["plan_no"],
            before_state=before,
            after_state=result,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(result)


class AdminMembershipPurchaseListView(APIView):
    """管理员查询会员购买记录；会员购买不允许退款。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询会员购买记录",
        operation_id="adminListMembershipPurchases",
        parameters=[
            OpenApiParameter("status", type=str, required=False, description="购买状态筛选"),
            OpenApiParameter("page", type=int, required=False, description="页码"),
            OpenApiParameter("page_size", type=int, required=False, description="每页数量"),
        ],
        responses={200: AdminMembershipPurchaseListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        require_admin_permission(request.user, "admin.membership.read")
        page, page_size = _page_params(request)
        return Response(
            list_admin_membership_purchases(
                status=request.query_params.get("status"),
                page=page,
                page_size=page_size,
            )
        )
