"""收款绑定、收益查询和提现审核 HTTP 视图。"""

from __future__ import annotations

from typing import ClassVar

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission, IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.accounts.authentication import BearerTokenAuthentication
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.payouts.api.serializers import (
    EarningAccountResponseSerializer,
    EarningEntryListResponseSerializer,
    EarningTransactionListResponseSerializer,
    PayoutMethodCreateRequestSerializer,
    PayoutMethodExpectedVersionSerializer,
    PayoutMethodListResponseSerializer,
    PayoutMethodResponseSerializer,
    WithdrawalCreateRequestSerializer,
    WithdrawalExpectedVersionSerializer,
    WithdrawalListResponseSerializer,
    WithdrawalResponseSerializer,
    WithdrawalReviewRequestSerializer,
)
from backend.payouts.services import (
    approve_withdrawal,
    cancel_withdrawal,
    create_payout_method,
    create_withdrawal,
    deactivate_payout_method,
    earning_account_payload,
    list_earning_entries,
    list_earning_transactions,
    list_payout_methods,
    list_withdrawals,
    reject_withdrawal,
    retry_withdrawal,
    set_default_payout_method,
)


def _page_params(request: Request) -> tuple[int, int]:
    """解析统一的页码和每页数量参数。"""

    try:
        page = max(1, int(request.query_params.get("page", 1)))
        page_size = min(100, max(1, int(request.query_params.get("page_size", 20))))
    except ValueError as exc:
        raise ApiError(
            ErrorCode.WITHDRAWAL_INVALID,
            ERROR_MESSAGES[ErrorCode.WITHDRAWAL_INVALID],
            status_code=400,
            details={"page": "分页参数必须是整数"},
        ) from exc
    return page, page_size


class PayoutMethodListCreateView(APIView):
    """当前用户收款方式查询和创建。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询我的收款方式",
        responses={200: PayoutMethodListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(list_payout_methods(user=request.user))

    @extend_schema(
        summary="绑定收款方式",
        request=PayoutMethodCreateRequestSerializer,
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                location=OpenApiParameter.HEADER,
                required=False,
                description="重复绑定请求幂等键",
            )
        ],
        responses={200: PayoutMethodResponseSerializer, 201: PayoutMethodResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = PayoutMethodCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = create_payout_method(
            user=request.user,
            payload=serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        return Response(result, status=200 if result["reused"] else 201)


class PayoutMethodDefaultView(APIView):
    """设置当前用户默认收款方式。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="设置默认收款方式",
        request=PayoutMethodExpectedVersionSerializer,
        responses={200: PayoutMethodResponseSerializer},
    )
    def post(self, request: Request, payout_method_id: str) -> Response:
        serializer = PayoutMethodExpectedVersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            set_default_payout_method(
                user=request.user,
                payout_method_id=payout_method_id,
                expected_version=serializer.validated_data["expected_version"],
            )
        )


class PayoutMethodDeactivateView(APIView):
    """停用当前用户收款方式并保留提现历史。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="停用收款方式",
        request=PayoutMethodExpectedVersionSerializer,
        responses={200: PayoutMethodResponseSerializer},
    )
    def post(self, request: Request, payout_method_id: str) -> Response:
        serializer = PayoutMethodExpectedVersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            deactivate_payout_method(
                user=request.user,
                payout_method_id=payout_method_id,
                expected_version=serializer.validated_data["expected_version"],
            )
        )


class EarningAccountView(APIView):
    """查询当前用户服务者收入或推广收益账户。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询收益账户汇总",
        parameters=[
            OpenApiParameter(
                "account_type",
                type=str,
                required=True,
                description="PROVIDER_INCOME 或 REFERRAL_REWARD",
            )
        ],
        responses={200: EarningAccountResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(
            earning_account_payload(
                user=request.user,
                account_type=request.query_params.get("account_type", ""),
            )
        )


class EarningEntryListView(APIView):
    """查询当前用户收益业务明细。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询收入明细",
        parameters=[
            OpenApiParameter(
                "account_type",
                type=str,
                required=True,
                description="PROVIDER_INCOME 或 REFERRAL_REWARD",
            ),
            OpenApiParameter("page", type=int, required=False, description="页码"),
            OpenApiParameter("page_size", type=int, required=False, description="每页数量"),
        ],
        responses={200: EarningEntryListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        page, page_size = _page_params(request)
        return Response(
            list_earning_entries(
                user=request.user,
                account_type=request.query_params.get("account_type", ""),
                page=page,
                page_size=page_size,
            )
        )


class EarningTransactionListView(APIView):
    """查询当前用户收益账户资金流水。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询收益流水",
        parameters=[
            OpenApiParameter(
                "account_type",
                type=str,
                required=True,
                description="PROVIDER_INCOME 或 REFERRAL_REWARD",
            ),
            OpenApiParameter("page", type=int, required=False, description="页码"),
            OpenApiParameter("page_size", type=int, required=False, description="每页数量"),
        ],
        responses={200: EarningTransactionListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        page, page_size = _page_params(request)
        return Response(
            list_earning_transactions(
                user=request.user,
                account_type=request.query_params.get("account_type", ""),
                page=page,
                page_size=page_size,
            )
        )


class WithdrawalListCreateView(APIView):
    """当前用户提现申请查询和创建。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询我的提现记录",
        parameters=[
            OpenApiParameter("status", type=str, required=False, description="提现状态筛选"),
            OpenApiParameter("page", type=int, required=False, description="页码"),
            OpenApiParameter("page_size", type=int, required=False, description="每页数量"),
        ],
        responses={200: WithdrawalListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        page, page_size = _page_params(request)
        return Response(
            list_withdrawals(
                user=request.user,
                status=request.query_params.get("status"),
                page=page,
                page_size=page_size,
            )
        )

    @extend_schema(
        summary="申请提现",
        request=WithdrawalCreateRequestSerializer,
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                location=OpenApiParameter.HEADER,
                required=False,
                description="重复提现申请幂等键",
            )
        ],
        responses={200: WithdrawalResponseSerializer, 201: WithdrawalResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = WithdrawalCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = create_withdrawal(
            user=request.user,
            account_type=serializer.validated_data["account_type"],
            amount_minor=serializer.validated_data["amount_minor"],
            payout_method_id=str(serializer.validated_data["payout_method_id"]),
            expected_version=serializer.validated_data["expected_version"],
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        return Response(result, status=200 if result["reused"] else 201)


class WithdrawalCancelView(APIView):
    """用户撤销待审核提现申请。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="撤销提现申请",
        request=WithdrawalExpectedVersionSerializer,
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                location=OpenApiParameter.HEADER,
                required=False,
                description="重复撤销请求幂等键",
            )
        ],
        responses={200: WithdrawalResponseSerializer},
    )
    def post(self, request: Request, withdrawal_no: str) -> Response:
        serializer = WithdrawalExpectedVersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            cancel_withdrawal(
                user=request.user,
                request_no=withdrawal_no,
                expected_version=serializer.validated_data["expected_version"],
                idempotency_key=request.headers.get("Idempotency-Key"),
            )
        )


class AdminWithdrawalListView(APIView):
    """管理员查询提现审核列表。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="查询提现申请列表",
        parameters=[
            OpenApiParameter("status", type=str, required=False, description="提现状态筛选"),
            OpenApiParameter("page", type=int, required=False, description="页码"),
            OpenApiParameter("page_size", type=int, required=False, description="每页数量"),
        ],
        responses={200: WithdrawalListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        page, page_size = _page_params(request)
        return Response(
            list_withdrawals(
                status=request.query_params.get("status"),
                page=page,
                page_size=page_size,
            )
        )


class AdminWithdrawalApproveView(APIView):
    """管理员审核通过提现并执行测试打款。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="同意提现并打款",
        request=WithdrawalReviewRequestSerializer,
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                location=OpenApiParameter.HEADER,
                required=False,
                description="重复审核请求幂等键",
            )
        ],
        responses={200: WithdrawalResponseSerializer},
    )
    def post(self, request: Request, withdrawal_no: str) -> Response:
        serializer = WithdrawalReviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            approve_withdrawal(
                admin_user=request.user,
                request_no=withdrawal_no,
                expected_version=serializer.validated_data["expected_version"],
                idempotency_key=request.headers.get("Idempotency-Key"),
            )
        )


class AdminWithdrawalRejectView(APIView):
    """管理员拒绝提现申请并解冻余额。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="拒绝提现申请",
        request=WithdrawalReviewRequestSerializer,
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                location=OpenApiParameter.HEADER,
                required=False,
                description="重复拒绝请求幂等键",
            )
        ],
        responses={200: WithdrawalResponseSerializer},
    )
    def post(self, request: Request, withdrawal_no: str) -> Response:
        serializer = WithdrawalReviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            reject_withdrawal(
                admin_user=request.user,
                request_no=withdrawal_no,
                expected_version=serializer.validated_data["expected_version"],
                review_note=serializer.validated_data.get("review_note", ""),
                idempotency_key=request.headers.get("Idempotency-Key"),
            )
        )


class AdminWithdrawalRetryView(APIView):
    """管理员重新发起失败提现打款。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="重试提现打款",
        request=WithdrawalExpectedVersionSerializer,
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                location=OpenApiParameter.HEADER,
                required=False,
                description="重复重试请求幂等键",
            )
        ],
        responses={200: WithdrawalResponseSerializer},
    )
    def post(self, request: Request, withdrawal_no: str) -> Response:
        serializer = WithdrawalExpectedVersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            retry_withdrawal(
                admin_user=request.user,
                request_no=withdrawal_no,
                expected_version=serializer.validated_data["expected_version"],
                idempotency_key=request.headers.get("Idempotency-Key"),
            )
        )
