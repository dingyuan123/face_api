"""Vue 管理后台认证、总览、用户、服务者、审计和角色权限接口。"""

from __future__ import annotations

from typing import ClassVar

from django.http import HttpResponse
from django.utils.dateparse import parse_datetime
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.accounts.deletion_services import (
    clear_account_balances,
    force_delete_account,
)
from backend.adminops.api.serializers import (
    AdminActionRequestSerializer,
    AdminAuditLogListResponseSerializer,
    AdminCaptchaResponseSerializer,
    AdminCommissionDetailListResponseSerializer,
    AdminCommissionOverviewResponseSerializer,
    AdminCommissionTrendsResponseSerializer,
    AdminDashboardResponseSerializer,
    AdminDashboardTodoResponseSerializer,
    AdminDashboardTrendsResponseSerializer,
    AdminFinanceOverviewResponseSerializer,
    AdminFinanceReconciliationResponseSerializer,
    AdminFinanceTransactionListResponseSerializer,
    AdminLoginRequestSerializer,
    AdminLogoutResponseSerializer,
    AdminMeResponseSerializer,
    AdminOrderListResponseSerializer,
    AdminPasswordForgotRequestSerializer,
    AdminPasswordForgotResponseSerializer,
    AdminPasswordResetRequestSerializer,
    AdminPasswordResetResponseSerializer,
    AdminPermissionResponseSerializer,
    AdminProviderListResponseSerializer,
    AdminProviderResponseSerializer,
    AdminRefreshRequestSerializer,
    AdminRoleCreateRequestSerializer,
    AdminRolePermissionRequestSerializer,
    AdminRoleResponseSerializer,
    AdminRoleUpdateRequestSerializer,
    AdminTokenResponseSerializer,
    AdminUserAuditLogListResponseSerializer,
    AdminUserBalanceClearRequestSerializer,
    AdminUserBalanceClearResponseSerializer,
    AdminUserDetailResponseSerializer,
    AdminUserFinanceListResponseSerializer,
    AdminUserForceDeleteRequestSerializer,
    AdminUserForceDeleteResponseSerializer,
    AdminUserListResponseSerializer,
    AdminUserOrderListResponseSerializer,
    AdminUserResponseSerializer,
    AdminUserReviewListResponseSerializer,
    AdminUserSupportTicketListResponseSerializer,
    AdminUserWithdrawalListResponseSerializer,
)
from backend.adminops.auth import (
    AdminBearerTokenAuthentication,
    admin_login,
    admin_logout,
    admin_password_forgot,
    admin_password_reset,
    admin_refresh,
    create_admin_captcha,
    permission_codes_for_user,
    require_admin_permission,
    roles_for_user,
    write_admin_operation,
)
from backend.adminops.dashboard_services import (
    admin_dashboard_todos,
    admin_dashboard_trends,
)
from backend.adminops.finance_services import (
    commission_details,
    commission_overview,
    commission_trends,
    export_finance_transactions,
    finance_overview,
    finance_reconciliation,
    list_finance_transactions,
)
from backend.adminops.services import (
    add_admin_role_member,
    admin_cancel_order,
    admin_dashboard_payload,
    admin_user_detail_payload,
    admin_user_payload,
    change_provider_status,
    change_user_status,
    create_admin_role,
    delete_admin_role,
    export_admin_orders,
    get_admin_order,
    get_admin_provider,
    get_admin_user,
    list_admin_audit_logs,
    list_admin_orders,
    list_admin_permissions,
    list_admin_providers,
    list_admin_roles,
    list_admin_user_audit_logs,
    list_admin_user_finance,
    list_admin_user_orders,
    list_admin_user_reviews,
    list_admin_user_support_tickets,
    list_admin_user_withdrawals,
    list_admin_users,
    list_admin_withdrawals,
    remove_admin_role_member,
    review_admin_withdrawal,
    update_admin_role,
)
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.orders.api.serializers import OrderResponseSerializer
from backend.payouts.api.serializers import (
    WithdrawalExpectedVersionSerializer,
    WithdrawalListResponseSerializer,
    WithdrawalReviewRequestSerializer,
)


def _integer_query(request: Request, name: str, default: int, minimum: int, maximum: int) -> int:
    raw = request.query_params.get(name)
    if raw in {None, ""}:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def _datetime_query(request: Request, name: str):
    raw = request.query_params.get(name)
    if not raw:
        return None
    value = parse_datetime(raw)
    if value is None:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "时间参数必须是 ISO 8601 格式",
            status_code=400,
            details={name: "时间参数格式不正确"},
        )
    return value


def _permission(permission_code: str):
    class Permission(BasePermission):
        """按视图声明的管理员权限点鉴权。"""

        def has_permission(self, request: Request, view) -> bool:
            if not bool(request.user and request.user.is_authenticated):
                return False
            require_admin_permission(request.user, permission_code)
            return True

    return Permission


class AdminLoginView(APIView):
    """管理后台账号密码登录。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = []
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        summary="管理后台登录",
        request=AdminLoginRequestSerializer,
        responses={200: AdminTokenResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = AdminLoginRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            admin_login(
                phone=serializer.validated_data["phone"],
                password=serializer.validated_data["password"],
                captcha_token=serializer.validated_data.get("captcha_token", ""),
                captcha_answer=serializer.validated_data.get("captcha_answer", ""),
            )
        )


class AdminCaptchaView(APIView):
    """获取管理员登录图形验证码。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = []
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        summary="获取管理员登录验证码",
        request=None,
        responses={200: AdminCaptchaResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        return Response(create_admin_captcha())


class AdminPasswordForgotView(APIView):
    """管理员忘记密码发送验证码。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = []
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        summary="发送管理员密码重置验证码",
        request=AdminPasswordForgotRequestSerializer,
        responses={200: AdminPasswordForgotResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = AdminPasswordForgotRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(admin_password_forgot(phone=serializer.validated_data["phone"]))


class AdminPasswordResetView(APIView):
    """管理员重置密码。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = []
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        summary="重置管理员密码",
        request=AdminPasswordResetRequestSerializer,
        responses={200: AdminPasswordResetResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = AdminPasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            admin_password_reset(
                phone=serializer.validated_data["phone"],
                code=serializer.validated_data["code"],
                new_password=serializer.validated_data["new_password"],
            )
        )


class AdminMeView(APIView):
    """查询当前管理员权限。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.session.read"),
    ]

    @extend_schema(
        summary="当前管理员认证信息",
        responses={200: AdminMeResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(
            {
                "admin_public_id": str(request.user.public_id),
                "display_name": request.user.phone_masked,
                "roles": roles_for_user(request.user),
                "permissions": permission_codes_for_user(request.user),
                "menu_version": 1,
            }
        )


class AdminRefreshView(APIView):
    """轮换管理后台令牌。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = []
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        summary="刷新管理后台令牌",
        request=AdminRefreshRequestSerializer,
        responses={200: AdminTokenResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        refresh_token = request.data.get("refresh_token", "")
        return Response(admin_refresh(refresh_token=refresh_token))


class AdminLogoutView(APIView):
    """撤销当前管理后台会话。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.session.read"),
    ]

    @extend_schema(
        summary="管理后台退出",
        request=None,
        responses={200: AdminLogoutResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        return Response(admin_logout(access_token=request.auth))


class AdminDashboardView(APIView):
    """管理后台经营总览。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.dashboard.read"),
    ]

    @extend_schema(
        summary="管理后台总览",
        responses={200: AdminDashboardResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(admin_dashboard_payload())


class AdminDashboardTrendsView(APIView):
    """管理后台每日经营趋势。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.dashboard.read"),
    ]

    @extend_schema(
        summary="查看管理后台趋势",
        parameters=[
            OpenApiParameter("range", required=False, description="7d 或 30d"),
        ],
        responses={200: AdminDashboardTrendsResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(admin_dashboard_trends(range_name=request.query_params.get("range", "7d")))


class AdminDashboardTodosView(APIView):
    """管理后台待处理事项。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.dashboard.read"),
    ]

    @extend_schema(
        summary="查看管理后台待处理事项",
        responses={200: AdminDashboardTodoResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(admin_dashboard_todos())


class AdminUserListView(APIView):
    """管理员用户列表。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.user.read"),
    ]

    @extend_schema(
        operation_id="admin_v1_users_list",
        summary="查看用户列表",
        parameters=[
            OpenApiParameter(
                "keyword",
                required=False,
                description="手机号脱敏值、用户昵称或服务者昵称关键词",
            ),
            OpenApiParameter("status", required=False, description="账号状态"),
            OpenApiParameter("page", type=int, required=False),
            OpenApiParameter("page_size", type=int, required=False),
        ],
        responses={200: AdminUserListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(
            list_admin_users(
                keyword=request.query_params.get("keyword", ""),
                status=request.query_params.get("status", ""),
                page=_integer_query(request, "page", 1, 1, 10_000),
                page_size=_integer_query(request, "page_size", 20, 1, 100),
                request=request,
            )
        )


class AdminUserDetailView(APIView):
    """管理员查看用户详情。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.user.read"),
    ]

    @extend_schema(
        operation_id="admin_v1_user_detail",
        summary="查看用户详情",
        responses={200: AdminUserDetailResponseSerializer},
    )
    def get(self, request: Request, user_public_id: str) -> Response:
        return Response(
            admin_user_detail_payload(
                get_admin_user(user_public_id=user_public_id),
                request,
            )
        )


class AdminUserOrderListView(APIView):
    """管理员查看用户参与的订单。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.user.read"),
    ]

    @extend_schema(
        operation_id="admin_v1_user_orders",
        summary="查看用户订单",
        parameters=[
            OpenApiParameter(
                "role",
                required=False,
                description="参与角色：ALL、CUSTOMER 或 PROVIDER",
            ),
            OpenApiParameter("status", required=False, description="订单状态"),
            OpenApiParameter("page", type=int, required=False),
            OpenApiParameter("page_size", type=int, required=False),
        ],
        responses={200: AdminUserOrderListResponseSerializer},
    )
    def get(self, request: Request, user_public_id: str) -> Response:
        return Response(
            list_admin_user_orders(
                user=get_admin_user(user_public_id=user_public_id),
                role=request.query_params.get("role", "ALL").upper(),
                status=request.query_params.get("status", ""),
                page=_integer_query(request, "page", 1, 1, 10_000),
                page_size=_integer_query(request, "page_size", 20, 1, 100),
                request=request,
            )
        )


class AdminUserFinanceListView(APIView):
    """管理员查看用户钱包、收益记录和收益流水。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.user.read"),
    ]

    @extend_schema(
        operation_id="admin_v1_user_finance",
        summary="查看用户资金明细",
        parameters=[
            OpenApiParameter(
                "ledger_type",
                required=False,
                description="明细类型：ALL、WALLET 或 EARNING",
            ),
            OpenApiParameter("page", type=int, required=False),
            OpenApiParameter("page_size", type=int, required=False),
        ],
        responses={200: AdminUserFinanceListResponseSerializer},
    )
    def get(self, request: Request, user_public_id: str) -> Response:
        return Response(
            list_admin_user_finance(
                user=get_admin_user(user_public_id=user_public_id),
                ledger_type=request.query_params.get("ledger_type", "ALL").upper(),
                page=_integer_query(request, "page", 1, 1, 10_000),
                page_size=_integer_query(request, "page_size", 20, 1, 100),
            )
        )


class AdminUserWithdrawalListView(APIView):
    """管理员查看用户提现申请。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.user.read"),
    ]

    @extend_schema(
        operation_id="admin_v1_user_withdrawals",
        summary="查看用户提现申请",
        parameters=[
            OpenApiParameter("status", required=False, description="提现状态"),
            OpenApiParameter("page", type=int, required=False),
            OpenApiParameter("page_size", type=int, required=False),
        ],
        responses={200: AdminUserWithdrawalListResponseSerializer},
    )
    def get(self, request: Request, user_public_id: str) -> Response:
        return Response(
            list_admin_user_withdrawals(
                user=get_admin_user(user_public_id=user_public_id),
                status=request.query_params.get("status", ""),
                page=_integer_query(request, "page", 1, 1, 10_000),
                page_size=_integer_query(request, "page_size", 20, 1, 100),
            )
        )


class AdminUserReviewListView(APIView):
    """管理员查看用户发表或收到的评价。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.user.read"),
    ]

    @extend_schema(
        operation_id="admin_v1_user_reviews",
        summary="查看用户评价",
        parameters=[
            OpenApiParameter(
                "direction",
                required=False,
                description="评价方向：ALL、GIVEN 或 RECEIVED",
            ),
            OpenApiParameter("page", type=int, required=False),
            OpenApiParameter("page_size", type=int, required=False),
        ],
        responses={200: AdminUserReviewListResponseSerializer},
    )
    def get(self, request: Request, user_public_id: str) -> Response:
        return Response(
            list_admin_user_reviews(
                user=get_admin_user(user_public_id=user_public_id),
                direction=request.query_params.get("direction", "ALL").upper(),
                page=_integer_query(request, "page", 1, 1, 10_000),
                page_size=_integer_query(request, "page_size", 20, 1, 100),
                request=request,
            )
        )


class AdminUserSupportTicketListView(APIView):
    """管理员查看用户客服工单。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.user.read"),
    ]

    @extend_schema(
        operation_id="admin_v1_user_support_tickets",
        summary="查看用户客服工单",
        parameters=[
            OpenApiParameter("status", required=False, description="工单状态"),
            OpenApiParameter("page", type=int, required=False),
            OpenApiParameter("page_size", type=int, required=False),
        ],
        responses={200: AdminUserSupportTicketListResponseSerializer},
    )
    def get(self, request: Request, user_public_id: str) -> Response:
        return Response(
            list_admin_user_support_tickets(
                user=get_admin_user(user_public_id=user_public_id),
                status=request.query_params.get("status", ""),
                page=_integer_query(request, "page", 1, 1, 10_000),
                page_size=_integer_query(request, "page_size", 20, 1, 100),
            )
        )


class AdminUserAuditLogListView(APIView):
    """管理员查看用户相关审计记录。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.user.read"),
    ]

    @extend_schema(
        operation_id="admin_v1_user_audit_logs",
        summary="查看用户审计记录",
        parameters=[
            OpenApiParameter("page", type=int, required=False),
            OpenApiParameter("page_size", type=int, required=False),
        ],
        responses={200: AdminUserAuditLogListResponseSerializer},
    )
    def get(self, request: Request, user_public_id: str) -> Response:
        return Response(
            list_admin_user_audit_logs(
                user=get_admin_user(user_public_id=user_public_id),
                page=_integer_query(request, "page", 1, 1, 10_000),
                page_size=_integer_query(request, "page_size", 20, 1, 100),
            )
        )


class AdminUserActionView(APIView):
    """管理员封禁或解封用户。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.user.ban"),
    ]

    @extend_schema(
        summary="封禁或解封用户",
        request=AdminActionRequestSerializer,
        responses={200: AdminUserResponseSerializer},
    )
    def post(self, request: Request, user_public_id: str, action: str) -> Response:
        serializer = AdminActionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = change_user_status(
            operator=request.user,
            user_public_id=user_public_id,
            action=action,
            expected_version=serializer.validated_data["expected_version"],
            reason=serializer.validated_data.get("reason", ""),
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(admin_user_payload(user))


class AdminUserBalanceClearView(APIView):
    """管理员人工清空用户余额和待结算权益。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.finance.adjust"),
    ]

    @extend_schema(
        summary="清空用户余额和待结算权益",
        description=(
            "仅限管理员处理无法提现的测试或遗留资金；写入钱包和收益调整流水，不直接修改余额字段。"
        ),
        request=AdminUserBalanceClearRequestSerializer,
        responses={200: AdminUserBalanceClearResponseSerializer},
    )
    def post(self, request: Request, user_public_id: str) -> Response:
        serializer = AdminUserBalanceClearRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = clear_account_balances(
            operator=request.user,
            user_public_id=str(user_public_id),
            reason=serializer.validated_data["reason"],
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        write_admin_operation(
            operator=request.user,
            action="USER_BALANCE_CLEAR",
            target_type="USER",
            target_id=str(user_public_id),
            after_state=result,
            reason=serializer.validated_data["reason"],
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(result)


class AdminUserForceDeleteView(APIView):
    """管理员强制注销无法正常提现的用户。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.user.force_delete"),
    ]

    @extend_schema(
        summary="强制注销用户",
        description=(
            "跳过注销条件中的资金门槛，但会先清空余额并写入不可变资金流水，"
            "再清理个人资料、内容和登录绑定。"
        ),
        request=AdminUserForceDeleteRequestSerializer,
        responses={200: AdminUserForceDeleteResponseSerializer},
    )
    def post(self, request: Request, user_public_id: str) -> Response:
        serializer = AdminUserForceDeleteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = force_delete_account(
            operator=request.user,
            user_public_id=str(user_public_id),
            expected_version=serializer.validated_data["expected_version"],
            reason=serializer.validated_data["reason"],
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        write_admin_operation(
            operator=request.user,
            action="USER_FORCE_DELETE",
            target_type="USER",
            target_id=str(user_public_id),
            after_state={
                "request_no": result["request_no"],
                "deletion_mode": result["deletion_mode"],
                "cleared_amount_minor": result["cleared_amount_minor"],
            },
            reason=serializer.validated_data["reason"],
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(result)


class AdminProviderListView(APIView):
    """管理员服务者列表。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.provider.read"),
    ]

    @extend_schema(
        operation_id="admin_v1_providers_list",
        summary="查看服务者列表",
        parameters=[
            OpenApiParameter("keyword", required=False),
            OpenApiParameter("status", required=False),
            OpenApiParameter("page", type=int, required=False),
            OpenApiParameter("page_size", type=int, required=False),
        ],
        responses={200: AdminProviderListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(
            list_admin_providers(
                keyword=request.query_params.get("keyword", ""),
                status=request.query_params.get("status", ""),
                page=_integer_query(request, "page", 1, 1, 10_000),
                page_size=_integer_query(request, "page_size", 20, 1, 100),
            )
        )


class AdminProviderDetailView(APIView):
    """管理员查看服务者详情。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.provider.read"),
    ]

    @extend_schema(
        operation_id="admin_v1_provider_detail",
        summary="查看服务者详情",
        responses={200: AdminProviderResponseSerializer},
    )
    def get(self, request: Request, user_public_id: str) -> Response:
        user = get_admin_provider(user_public_id=user_public_id)
        return Response(
            {
                "user_public_id": str(user.public_id),
                "nickname": getattr(user, "provider_profile", None).nickname
                if getattr(user, "provider_profile", None)
                else None,
                "phone_masked": user.phone_masked,
                "provider_status": user.provider_status,
                "provider_enabled": user.provider_enabled,
                "version": user.version,
            }
        )


class AdminProviderActionView(APIView):
    """管理员停用或恢复服务者。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.provider.status"),
    ]

    @extend_schema(
        summary="停用或恢复服务者",
        request=AdminActionRequestSerializer,
        responses={200: AdminProviderResponseSerializer},
    )
    def post(self, request: Request, user_public_id: str, action: str) -> Response:
        serializer = AdminActionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = change_provider_status(
            operator=request.user,
            user_public_id=user_public_id,
            action=action,
            expected_version=serializer.validated_data["expected_version"],
            reason=serializer.validated_data.get("reason", ""),
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return Response(
            {
                "user_public_id": str(user.public_id),
                "nickname": getattr(user, "provider_profile", None).nickname
                if getattr(user, "provider_profile", None)
                else None,
                "phone_masked": user.phone_masked,
                "provider_status": user.provider_status,
                "provider_enabled": user.provider_enabled,
                "version": user.version,
            }
        )


class AdminOrderListView(APIView):
    """管理员订单列表。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.order.read"),
    ]

    @extend_schema(
        operation_id="admin_v1_orders_list",
        summary="查看管理员订单列表",
        parameters=[
            OpenApiParameter("keyword", required=False, description="订单号关键词"),
            OpenApiParameter("status", required=False, description="订单状态"),
            OpenApiParameter("page", type=int, required=False),
            OpenApiParameter("page_size", type=int, required=False),
        ],
        responses={200: AdminOrderListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(
            list_admin_orders(
                keyword=request.query_params.get("keyword", ""),
                status=request.query_params.get("status", ""),
                page=_integer_query(request, "page", 1, 1, 10_000),
                page_size=_integer_query(request, "page_size", 20, 1, 100),
                request=request._request,
            )
        )


class AdminOrderDetailView(APIView):
    """管理员订单详情。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.order.read"),
    ]

    @extend_schema(
        operation_id="admin_v1_order_detail",
        summary="查看管理员订单详情",
        responses={200: OrderResponseSerializer},
    )
    def get(self, request: Request, order_no: str) -> Response:
        return Response(get_admin_order(order_no=order_no, request=request._request))


class AdminOrderExportView(APIView):
    """导出管理员订单 CSV。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.order.read"),
    ]

    @extend_schema(
        summary="导出管理员订单 CSV",
        responses={200: OpenApiTypes.BINARY},
    )
    def get(self, request: Request) -> HttpResponse:
        content = export_admin_orders(
            keyword=request.query_params.get("keyword", ""),
            status=request.query_params.get("status", ""),
        )
        response = HttpResponse(content, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = "attachment; filename=admin-orders.csv"
        return response


class AdminOrderCancelView(APIView):
    """管理员取消订单。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.order.cancel"),
    ]

    @extend_schema(
        summary="管理员取消订单",
        request=AdminActionRequestSerializer,
        responses={200: OrderResponseSerializer},
    )
    def post(self, request: Request, order_no: str) -> Response:
        serializer = AdminActionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            admin_cancel_order(
                operator=request.user,
                order_no=order_no,
                expected_version=serializer.validated_data["expected_version"],
                reason=serializer.validated_data.get("reason", ""),
                idempotency_key=request.headers.get("Idempotency-Key", ""),
            )
        )


class AdminAuditLogView(APIView):
    """管理员操作审计列表。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.audit.read"),
    ]

    @extend_schema(
        summary="查看管理操作审计",
        responses={200: AdminAuditLogListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(
            list_admin_audit_logs(
                page=_integer_query(request, "page", 1, 1, 10_000),
                page_size=_integer_query(request, "page_size", 20, 1, 100),
            )
        )


class AdminPermissionView(APIView):
    """查看管理员权限点。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.rbac.read"),
    ]

    @extend_schema(
        summary="查看管理员权限点",
        responses={200: AdminPermissionResponseSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        return Response(list_admin_permissions())


class AdminRoleView(APIView):
    """查看管理员角色。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.rbac.read"),
    ]

    @extend_schema(
        summary="查看管理员角色",
        responses={200: AdminRoleResponseSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        return Response(list_admin_roles())

    @extend_schema(
        operation_id="admin_v1_role_create",
        summary="创建管理员角色",
        request=AdminRoleCreateRequestSerializer,
        responses={201: AdminRoleResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = AdminRoleCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            create_admin_role(
                operator=request.user,
                payload=dict(serializer.validated_data),
            ),
            status=201,
        )


class AdminRoleDetailView(APIView):
    """查看、修改或删除管理员角色。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.rbac.read"),
    ]

    @extend_schema(summary="查看管理员角色", responses={200: AdminRoleResponseSerializer})
    def get(self, request: Request, role_no: str) -> Response:
        for role in list_admin_roles():
            if role["role_no"] == role_no:
                return Response(role)
        raise ApiError(
            ErrorCode.NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.NOT_FOUND],
            status_code=404,
        )

    @extend_schema(
        summary="修改管理员角色",
        request=AdminRoleUpdateRequestSerializer,
        responses={200: AdminRoleResponseSerializer},
    )
    def patch(self, request: Request, role_no: str) -> Response:
        serializer = AdminRoleUpdateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            update_admin_role(
                operator=request.user,
                role_no=role_no,
                payload=dict(serializer.validated_data),
            )
        )

    @extend_schema(summary="删除管理员角色", responses={200: dict})
    def delete(self, request: Request, role_no: str) -> Response:
        return Response(delete_admin_role(operator=request.user, role_no=role_no))


class AdminRolePermissionView(APIView):
    """整体替换管理员角色权限点。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.rbac.write"),
    ]

    @extend_schema(
        summary="替换管理员角色权限点",
        request=AdminRolePermissionRequestSerializer,
        responses={200: AdminRoleResponseSerializer},
    )
    def put(self, request: Request, role_no: str) -> Response:
        serializer = AdminRolePermissionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        payload.pop("expected_version")
        return Response(
            update_admin_role(
                operator=request.user,
                role_no=role_no,
                payload={
                    **payload,
                    "expected_version": serializer.validated_data["expected_version"],
                },
            )
        )


class AdminRoleMemberView(APIView):
    """增加或移除管理员角色成员。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.rbac.write"),
    ]

    @extend_schema(
        operation_id="admin_v1_role_members_create",
        summary="增加管理员角色成员",
        request={"user_public_id": {"type": "string"}},
        responses={200: dict},
    )
    def post(self, request: Request, role_no: str) -> Response:
        user_public_id = request.data.get("user_public_id", "")
        return Response(
            add_admin_role_member(
                operator=request.user,
                role_no=role_no,
                user_public_id=user_public_id,
            )
        )

    @extend_schema(
        operation_id="admin_v1_role_member_delete",
        summary="移除管理员角色成员",
        responses={200: dict},
    )
    def delete(self, request: Request, role_no: str, user_public_id: str) -> Response:
        return Response(
            remove_admin_role_member(
                operator=request.user,
                role_no=role_no,
                user_public_id=user_public_id,
            )
        )


class AdminRoleMemberRemoveView(APIView):
    """移除管理员角色成员。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.rbac.write"),
    ]

    @extend_schema(
        operation_id="admin_v1_role_member_remove",
        summary="移除管理员角色成员",
        responses={200: dict},
    )
    def delete(self, request: Request, role_no: str, user_public_id: str) -> Response:
        return Response(
            remove_admin_role_member(
                operator=request.user,
                role_no=role_no,
                user_public_id=user_public_id,
            )
        )


class AdminFinanceOverviewView(APIView):
    """平台财务总览。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.finance.read"),
    ]

    @extend_schema(
        summary="查看平台财务总览",
        responses={200: AdminFinanceOverviewResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(finance_overview())


class AdminFinanceTransactionView(APIView):
    """平台财务流水列表。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.finance.read"),
    ]

    @extend_schema(
        summary="查看平台财务流水",
        parameters=[
            OpenApiParameter("source_type", required=False, description="WALLET 或 EARNING"),
            OpenApiParameter("user_public_id", required=False),
            OpenApiParameter("start_at", required=False, description="ISO 8601 开始时间"),
            OpenApiParameter("end_at", required=False, description="ISO 8601 结束时间"),
            OpenApiParameter("page", type=int, required=False),
            OpenApiParameter("page_size", type=int, required=False),
        ],
        responses={200: AdminFinanceTransactionListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(
            list_finance_transactions(
                source_type=request.query_params.get("source_type", ""),
                user_public_id=request.query_params.get("user_public_id", ""),
                start_at=_datetime_query(request, "start_at"),
                end_at=_datetime_query(request, "end_at"),
                page=_integer_query(request, "page", 1, 1, 10_000),
                page_size=_integer_query(request, "page_size", 20, 1, 100),
            )
        )


class AdminFinanceTransactionExportView(APIView):
    """导出平台财务流水 CSV。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.finance.read"),
    ]

    @extend_schema(
        summary="导出平台财务流水 CSV",
        responses={200: OpenApiTypes.BINARY},
    )
    def get(self, request: Request) -> HttpResponse:
        content = export_finance_transactions(
            source_type=request.query_params.get("source_type", ""),
            user_public_id=request.query_params.get("user_public_id", ""),
            start_at=_datetime_query(request, "start_at"),
            end_at=_datetime_query(request, "end_at"),
        )
        response = HttpResponse(content, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = "attachment; filename=finance-transactions.csv"
        return response


class AdminCommissionOverviewView(APIView):
    """平台服务者佣金概览。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.commission.read"),
    ]

    @extend_schema(
        summary="查看平台佣金概览",
        responses={200: AdminCommissionOverviewResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(commission_overview())


class AdminCommissionTrendView(APIView):
    """平台服务者佣金趋势。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.commission.read"),
    ]

    @extend_schema(
        summary="查看平台佣金趋势",
        parameters=[
            OpenApiParameter("range", required=False, description="7d 或 30d"),
        ],
        responses={200: AdminCommissionTrendsResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(commission_trends(range_name=request.query_params.get("range", "7d")))


class AdminCommissionDetailView(APIView):
    """平台服务者佣金明细。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.commission.read"),
    ]

    @extend_schema(
        summary="查看平台佣金明细",
        parameters=[
            OpenApiParameter("provider_public_id", required=False),
            OpenApiParameter("start_at", required=False),
            OpenApiParameter("end_at", required=False),
            OpenApiParameter("page", type=int, required=False),
            OpenApiParameter("page_size", type=int, required=False),
        ],
        responses={200: AdminCommissionDetailListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(
            commission_details(
                provider_public_id=request.query_params.get("provider_public_id", ""),
                start_at=_datetime_query(request, "start_at"),
                end_at=_datetime_query(request, "end_at"),
                page=_integer_query(request, "page", 1, 1, 10_000),
                page_size=_integer_query(request, "page_size", 20, 1, 100),
            )
        )


class AdminFinanceReconciliationView(APIView):
    """查看平台财务内部对账结果。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.finance.read"),
    ]

    @extend_schema(
        summary="查看平台财务对账",
        responses={200: AdminFinanceReconciliationResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(finance_reconciliation())


class AdminWithdrawalListView(APIView):
    """管理员提现单列表。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.withdrawal.read"),
    ]

    @extend_schema(
        summary="查看提现单",
        parameters=[
            OpenApiParameter("status", required=False),
            OpenApiParameter("page", type=int, required=False),
            OpenApiParameter("page_size", type=int, required=False),
        ],
        responses={200: WithdrawalListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(
            list_admin_withdrawals(
                status=request.query_params.get("status", ""),
                page=_integer_query(request, "page", 1, 1, 10_000),
                page_size=_integer_query(request, "page_size", 20, 1, 100),
            )
        )


class AdminWithdrawalActionView(APIView):
    """管理员审核、拒绝或重试提现。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [
        IsAuthenticated,
        _permission("admin.withdrawal.write"),
    ]

    @extend_schema(
        summary="审核提现单",
        request=WithdrawalReviewRequestSerializer,
        responses={200: dict},
    )
    def post(self, request: Request, request_no: str, action: str) -> Response:
        if action == "approve":
            serializer = WithdrawalExpectedVersionSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            result = review_admin_withdrawal(
                operator=request.user,
                request_no=request_no,
                action=action,
                expected_version=serializer.validated_data["expected_version"],
                idempotency_key=request.headers.get("Idempotency-Key", ""),
            )
        else:
            serializer = WithdrawalReviewRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            result = review_admin_withdrawal(
                operator=request.user,
                request_no=request_no,
                action=action,
                expected_version=serializer.validated_data["expected_version"],
                review_note=serializer.validated_data.get("review_note", ""),
                idempotency_key=request.headers.get("Idempotency-Key", ""),
            )
        return Response(result)
