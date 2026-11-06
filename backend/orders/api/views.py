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
from backend.orders.api.serializers import (
    OrderActionRequestSerializer,
    OrderCreateRequestSerializer,
    OrderPayRequestSerializer,
    OrderQuoteRequestSerializer,
    OrderQuoteResponseSerializer,
    OrderRefundRequestCreateSerializer,
    OrderRefundRequestListResponseSerializer,
    OrderRefundRequestSerializer,
    OrderRefundRetryRequestSerializer,
    OrderRefundReviewRequestSerializer,
    OrderResponseSerializer,
    OrderSummaryResponseSerializer,
    OrderVersionRequestSerializer,
)
from backend.orders.services import (
    approve_order_refund_request,
    cancel_order,
    cancel_order_refund_request,
    create_order,
    create_order_refund_request,
    list_admin_refund_requests,
    list_order_refund_requests,
    list_orders,
    order_payload,
    order_summary,
    pay_order,
    quote_order,
    reject_order,
    reject_order_refund_request,
    retry_order_refund_request,
    transition_order,
)


class OrderQuoteView(APIView):
    """下单前按小时价格计算预约金额。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="计算下单前金额",
        request=OrderQuoteRequestSerializer,
        responses={200: OrderQuoteResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = OrderQuoteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            quote_order(
                user=request.user,
                service_id=str(serializer.validated_data["service_id"]),
                slot_id=str(serializer.validated_data["slot_id"]),
            )
        )


class OrderSummaryView(APIView):
    """普通用户和服务者订单管理数量汇总。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="获取订单状态数量汇总",
        operation_id="summarizeOrders",
        parameters=[
            OpenApiParameter(
                "role",
                type=str,
                required=False,
                description="USER 用户订单或 PROVIDER 服务者订单，默认 USER",
            )
        ],
        responses={200: OrderSummaryResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(
            order_summary(
                user=request.user,
                role=request.query_params.get("role", "USER"),
            )
        )


class OrderRefundRequestView(APIView):
    """用户查询和提交订单退款申请。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询订单退款申请历史",
        operation_id="listOrderRefundRequests",
        responses={200: OrderRefundRequestSerializer(many=True)},
    )
    def get(self, request: Request, order_no: str) -> Response:
        return Response(
            list_order_refund_requests(
                user=request.user,
                order_no=order_no,
            )
        )

    @extend_schema(
        summary="提交订单退款申请",
        operation_id="createOrderRefundRequest",
        request=OrderRefundRequestCreateSerializer,
        responses={200: OrderRefundRequestSerializer, 201: OrderRefundRequestSerializer},
    )
    def post(self, request: Request, order_no: str) -> Response:
        serializer = OrderRefundRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        refund_request, created = create_order_refund_request(
            user=request.user,
            order_no=order_no,
            reason=serializer.validated_data["reason"],
            expected_order_version=serializer.validated_data["expected_order_version"],
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        return Response(
            {
                "request_no": str(refund_request.request_no),
                "order_no": str(refund_request.order.order_no),
                "status": refund_request.status,
                "status_text": "待审核",
                "reason": refund_request.reason,
                "currency": refund_request.currency,
                "refund_amount_minor": refund_request.refund_amount_minor,
                "review_note": refund_request.review_note,
                "reviewed_at": refund_request.reviewed_at,
                "failure_reason": refund_request.failure_reason,
                "version": refund_request.version,
                "created_at": refund_request.created_at,
                "updated_at": refund_request.updated_at,
            },
            status=201 if created else 200,
        )


class OrderRefundRequestCancelView(APIView):
    """用户撤销待审核退款申请。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="撤销退款申请",
        operation_id="cancelOrderRefundRequest",
        request=OrderVersionRequestSerializer,
        responses={200: OrderRefundRequestSerializer},
    )
    def post(self, request: Request, request_no: str) -> Response:
        serializer = OrderVersionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            cancel_order_refund_request(
                user=request.user,
                request_no=request_no,
                expected_version=serializer.validated_data["expected_version"],
            )
        )


class AdminOrderRefundRequestListView(APIView):
    """后台退款申请列表查询。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="查询退款申请列表",
        operation_id="listAdminOrderRefundRequests",
        parameters=[
            OpenApiParameter("status", type=str, required=False, description="退款申请状态"),
            OpenApiParameter("page", type=int, required=False, description="页码"),
            OpenApiParameter("page_size", type=int, required=False, description="每页数量"),
        ],
        responses={200: OrderRefundRequestListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        try:
            page = max(1, int(request.query_params.get("page", 1)))
            page_size = min(100, max(1, int(request.query_params.get("page_size", 20))))
        except ValueError as exc:
            raise ApiError(
                ErrorCode.REFUND_REQUEST_INVALID,
                ERROR_MESSAGES[ErrorCode.REFUND_REQUEST_INVALID],
                status_code=400,
                details={"page": "分页参数必须是整数"},
            ) from exc
        return Response(
            list_admin_refund_requests(
                status=request.query_params.get("status"),
                page=page,
                page_size=page_size,
            )
        )


class AdminOrderRefundRequestApproveView(APIView):
    """后台同意退款申请并执行全额退款。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="同意退款申请",
        operation_id="approveOrderRefundRequest",
        request=OrderRefundReviewRequestSerializer,
        responses={200: OrderRefundRequestSerializer},
    )
    def post(self, request: Request, request_no: str) -> Response:
        serializer = OrderRefundReviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            approve_order_refund_request(
                admin_user=request.user,
                request_no=request_no,
                expected_version=serializer.validated_data["expected_version"],
                review_note=serializer.validated_data["review_note"],
            )
        )


class AdminOrderRefundRequestRejectView(APIView):
    """后台拒绝退款申请。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="拒绝退款申请",
        operation_id="rejectOrderRefundRequest",
        request=OrderRefundReviewRequestSerializer,
        responses={200: OrderRefundRequestSerializer},
    )
    def post(self, request: Request, request_no: str) -> Response:
        serializer = OrderRefundReviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            reject_order_refund_request(
                admin_user=request.user,
                request_no=request_no,
                expected_version=serializer.validated_data["expected_version"],
                review_note=serializer.validated_data["review_note"],
            )
        )


class AdminOrderRefundRequestRetryView(APIView):
    """后台重新处理退款失败的申请。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="重新处理退款申请",
        operation_id="retryOrderRefundRequest",
        request=OrderRefundRetryRequestSerializer,
        responses={200: OrderRefundRequestSerializer},
    )
    def post(self, request: Request, request_no: str) -> Response:
        serializer = OrderRefundRetryRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            retry_order_refund_request(
                admin_user=request.user,
                request_no=request_no,
                expected_version=serializer.validated_data["expected_version"],
            )
        )


class OrderListCreateView(APIView):
    """用户订单列表和预约下单接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询我的预约订单",
        operation_id="listOrders",
        parameters=[
            OpenApiParameter(
                "role",
                type=str,
                required=False,
                description="USER 用户订单或 PROVIDER 服务者订单，默认 USER",
            ),
            OpenApiParameter(
                "status",
                type=str,
                required=False,
                description="订单状态筛选",
            ),
        ],
        responses={200: OrderResponseSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        role = request.query_params.get("role", "USER")
        return Response(
            list_orders(
                user=request.user,
                role=role,
                status=request.query_params.get("status"),
                request=request,
            )
        )

    @extend_schema(
        summary="创建预约订单",
        request=OrderCreateRequestSerializer,
        responses={201: OrderResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = OrderCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = create_order(
            user=request.user,
            service_id=str(serializer.validated_data["service_id"]),
            slot_id=str(serializer.validated_data["slot_id"]),
            note=serializer.validated_data.get("note", ""),
            expected_service_version=serializer.validated_data["expected_service_version"],
            expected_slot_version=serializer.validated_data["expected_slot_version"],
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        return Response(
            order_payload(result.order, request),
            status=200 if result.reused else 201,
        )


class OrderDetailView(APIView):
    """当前用户订单详情。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(summary="查询订单详情", responses={200: OrderResponseSerializer})
    def get(self, request: Request, order_no: str) -> Response:
        from backend.orders.services import _get_owned_order

        return Response(
            order_payload(_get_owned_order(user=request.user, order_no=order_no), request)
        )


class OrderPayView(APIView):
    """钱包余额支付预约订单。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="使用钱包余额支付订单",
        request=OrderPayRequestSerializer,
        responses={200: dict},
    )
    def post(self, request: Request, order_no: str) -> Response:
        serializer = OrderPayRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data["payment_method"] != "BALANCE":
            raise ApiError(
                ErrorCode.ORDER_INVALID,
                ERROR_MESSAGES[ErrorCode.ORDER_INVALID],
                status_code=400,
                details={"payment_method": "当前仅支持 BALANCE"},
            )
        return Response(
            pay_order(
                user=request.user,
                order_no=order_no,
                expected_version=serializer.validated_data["expected_version"],
                idempotency_key=request.headers.get("Idempotency-Key"),
            )
        )


class OrderCancelView(APIView):
    """用户取消预约订单。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="取消预约订单",
        request=OrderActionRequestSerializer,
        responses={200: OrderResponseSerializer},
    )
    def post(self, request: Request, order_no: str) -> Response:
        serializer = OrderActionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            order_payload(
                cancel_order(
                    user=request.user,
                    order_no=order_no,
                    expected_version=serializer.validated_data["expected_version"],
                    reason=serializer.validated_data.get("reason", ""),
                ),
                request,
            )
        )


class OrderActionView(APIView):
    """订单接单、开始、服务者完成和用户确认。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="执行订单状态操作",
        request=OrderActionRequestSerializer,
        responses={200: OrderResponseSerializer},
    )
    def post(self, request: Request, order_no: str, action: str) -> Response:
        serializer = OrderActionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            order_payload(
                transition_order(
                    user=request.user,
                    order_no=order_no,
                    expected_version=serializer.validated_data["expected_version"],
                    action=action,
                    reason=serializer.validated_data.get("reason", ""),
                ),
                request,
            )
        )


class OrderRejectView(APIView):
    """服务者拒绝预约订单。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="服务者拒绝订单",
        request=OrderActionRequestSerializer,
        responses={200: OrderResponseSerializer},
    )
    def post(self, request: Request, order_no: str) -> Response:
        serializer = OrderActionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            order_payload(
                reject_order(
                    provider_user=request.user,
                    order_no=order_no,
                    expected_version=serializer.validated_data["expected_version"],
                    reason=serializer.validated_data.get("reason", ""),
                ),
                request,
            )
        )
