"""分享推广 HTTP 接口层，仅负责认证、参数校验和业务服务调用。"""

from __future__ import annotations

from typing import ClassVar

from django.http import FileResponse
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import (
    AllowAny,
    BasePermission,
    IsAdminUser,
    IsAuthenticated,
)
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.accounts.authentication import BearerTokenAuthentication
from backend.referrals.admin_services import (
    adjust_referral_reward,
    change_referral_reward_state,
    create_referral_policy,
    retire_referral_policy,
)
from backend.referrals.api.serializers import (
    ReferralContextRequestSerializer,
    ReferralOverviewResponseSerializer,
    ReferralPolicyRequestSerializer,
    ReferralPolicyResponseSerializer,
    ReferralPolicyRetireResponseSerializer,
    ReferralVisitResponseSerializer,
    RewardAdjustRequestSerializer,
    RewardListResponseSerializer,
    RewardResponseSerializer,
    RewardStateRequestSerializer,
    ShareLinkRequestSerializer,
    ShareLinkResponseSerializer,
)
from backend.referrals.qr_services import validate_referral_qr_token
from backend.referrals.queries import (
    admin_list_attributions,
    admin_list_rewards,
    list_referral_policies,
    list_referral_rewards,
    referral_overview,
    referral_reward_summary,
)
from backend.referrals.services import (
    create_share_link,
    record_referral_visit,
)


def _integer_query(request: Request, name: str, default: int, minimum: int, maximum: int) -> int:
    """读取并限制整数查询参数。"""
    raw = request.query_params.get(name)
    if raw in {None, ""}:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


class ReferralVisitView(APIView):
    """记录匿名分享链接访问，不执行注册绑定。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = []
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        summary="记录分享链接访问",
        request=ReferralContextRequestSerializer,
        responses={201: ReferralVisitResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = ReferralContextRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            record_referral_visit(
                payload=dict(serializer.validated_data),
                request=request._request,
            ),
            status=201,
        )


class ReferralQRView(APIView):
    """通过短期签名地址读取分享主页二维码 PNG。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = []
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        summary="读取分享主页二维码",
        description="使用海报响应中的 qr_image_url，不需要 Authorization。",
        responses={200: OpenApiTypes.BINARY},
    )
    def get(self, request: Request, share_no: str) -> Response:
        path = validate_referral_qr_token(
            share_no=str(share_no),
            expires_at=request.query_params.get("expires", ""),
            key_version=request.query_params.get("key_version", ""),
            signature=request.query_params.get("signature", ""),
        )
        response = FileResponse(path.open("rb"), content_type="image/png")
        response["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response["Pragma"] = "no-cache"
        return response


class ReferralOverviewView(APIView):
    """查询当前用户分享赚钱页总览。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="获取我的分享赚钱总览",
        responses={200: ReferralOverviewResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(referral_overview(user=request.user))


class ReferralShareLinkView(APIView):
    """按渠道生成当前用户的分享链接。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="生成分享链接",
        request=ShareLinkRequestSerializer,
        responses={201: ShareLinkResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = ShareLinkRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = create_share_link(
            user=request.user,
            payload=dict(serializer.validated_data),
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        return Response(result, status=201)


class ReferralRewardSummaryView(APIView):
    """查询当前用户奖励状态汇总。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(summary="获取我的奖励汇总", responses={200: dict})
    def get(self, request: Request) -> Response:
        return Response(referral_reward_summary(user=request.user))


class ReferralRewardListView(APIView):
    """分页查询当前用户推广奖励。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="获取我的推广奖励明细",
        parameters=[
            OpenApiParameter("status", required=False, description="奖励状态筛选"),
            OpenApiParameter("page", type=int, required=False, description="页码"),
            OpenApiParameter("page_size", type=int, required=False, description="每页数量"),
        ],
        responses={200: RewardListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(
            list_referral_rewards(
                user=request.user,
                status=request.query_params.get("status"),
                page=_integer_query(request, "page", 1, 1, 10_000),
                page_size=_integer_query(request, "page_size", 20, 1, 100),
            )
        )


class AdminReferralPolicyListView(APIView):
    """管理员查询和创建奖励政策版本。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="查看奖励政策版本",
        responses={200: ReferralPolicyResponseSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        return Response(list_referral_policies())

    @extend_schema(
        summary="创建奖励政策版本",
        request=ReferralPolicyRequestSerializer,
        responses={201: ReferralPolicyResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = ReferralPolicyRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        policy = create_referral_policy(
            payload=dict(serializer.validated_data),
            operator_user_id=request.user.id,
        )
        return Response(
            next(item for item in list_referral_policies() if item["version"] == policy.version),
            status=201,
        )


class AdminReferralPolicyRetireView(APIView):
    """管理员停止奖励政策版本。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="停止奖励政策版本",
        request=None,
        responses={200: ReferralPolicyRetireResponseSerializer},
    )
    def post(self, request: Request, policy_no: str) -> Response:
        policy = retire_referral_policy(policy_no=policy_no)
        return Response({"policy_no": str(policy.policy_no), "status": policy.status})


class AdminReferralAttributionListView(APIView):
    """管理员查询邀请关系和风险状态。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="查看邀请归因",
        parameters=[
            OpenApiParameter("inviter_public_id", required=False, description="邀请人用户 UUID"),
            OpenApiParameter("risk_status", required=False, description="风险状态"),
            OpenApiParameter("page", type=int, required=False),
            OpenApiParameter("page_size", type=int, required=False),
        ],
        responses={200: dict},
    )
    def get(self, request: Request) -> Response:
        return Response(
            admin_list_attributions(
                inviter_public_id=request.query_params.get("inviter_public_id"),
                risk_status=request.query_params.get("risk_status"),
                page=_integer_query(request, "page", 1, 1, 10_000),
                page_size=_integer_query(request, "page_size", 20, 1, 100),
            )
        )


class AdminReferralRewardListView(APIView):
    """管理员查询推广奖励。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="查看推广奖励",
        parameters=[
            OpenApiParameter("status", required=False, description="奖励状态"),
            OpenApiParameter("page", type=int, required=False),
            OpenApiParameter("page_size", type=int, required=False),
        ],
        responses={200: RewardListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(
            admin_list_rewards(
                status=request.query_params.get("status"),
                page=_integer_query(request, "page", 1, 1, 10_000),
                page_size=_integer_query(request, "page_size", 20, 1, 100),
            )
        )


class AdminReferralRewardStateView(APIView):
    """管理员冻结、解冻或取消推广奖励。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="调整推广奖励状态",
        request=RewardStateRequestSerializer,
        responses={200: RewardResponseSerializer},
    )
    def post(self, request: Request, reward_no: str, action: str) -> Response:
        serializer = RewardStateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reward = change_referral_reward_state(
            reward_no=reward_no,
            action=action,
            expected_version=serializer.validated_data["expected_version"],
            reason=serializer.validated_data["reason"],
            operator_user_id=request.user.id,
        )
        from backend.referrals.queries import _reward_payload

        return Response(_reward_payload(reward))


class AdminReferralRewardAdjustView(APIView):
    """管理员对推广奖励执行不可变金额调整。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="调整推广奖励金额",
        request=RewardAdjustRequestSerializer,
        responses={200: RewardResponseSerializer},
    )
    def post(self, request: Request, reward_no: str) -> Response:
        serializer = RewardAdjustRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reward = adjust_referral_reward(
            reward_no=reward_no,
            expected_version=serializer.validated_data["expected_version"],
            amount_delta_minor=serializer.validated_data["amount_delta_minor"],
            reason=serializer.validated_data["reason"],
            idempotency_key=request.headers.get("Idempotency-Key")
            or f"auto:{reward_no}:{serializer.validated_data['expected_version']}",
            operator_user_id=request.user.id,
        )
        from backend.referrals.queries import _reward_payload

        return Response(_reward_payload(reward))
