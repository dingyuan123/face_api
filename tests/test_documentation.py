from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from backend.accounts.api.deletion_serializers import (
    AccountDeletionCheckItemSerializer,
    AccountDeletionCheckResponseSerializer,
    AccountDeletionConfirmRequestSerializer,
    AccountDeletionResponseSerializer,
    AccountDeletionSmsResponseSerializer,
)
from backend.accounts.api.security_serializers import (
    AccountSecurityResponseSerializer,
    PasswordChangeRequestSerializer,
    PasswordChangeResponseSerializer,
    PasswordForgotSmsRequestSerializer,
    PasswordResetRequestSerializer,
    PasswordResetResponseSerializer,
    PhoneChangeConfirmRequestSerializer,
    PhoneChangeConfirmResponseSerializer,
    PhoneChangeRequestSerializer,
    PhoneChangeResponseSerializer,
    SecuritySmsResponseSerializer,
)
from backend.accounts.api.serializers import (
    DevPasswordLoginRequestSerializer,
    InitialRoleRequestSerializer,
    InitialRoleResponseSerializer,
    LoginRequestSerializer,
    LogoutResponseSerializer,
    PasswordLoginRequestSerializer,
    RefreshRequestSerializer,
    SessionResponseSerializer,
    SmsCodeRequestSerializer,
    SmsCodeResponseSerializer,
    TokenPairResponseSerializer,
)
from backend.accounts.models import (
    AccountDeletionRecord,
    AccountSecurityEvent,
    AuthToken,
    LoginRequest,
    PhoneChangeRequest,
    User,
    UserAuth,
    VerificationCode,
    VerificationSendGuard,
)
from backend.adminops.api.serializers import (
    AdminCompanyLicenseUploadRequestSerializer,
    AdminCompanyProfileResponseSerializer,
    AdminCompanyProfileUpdateRequestSerializer,
    PublicCompanyLicenseMediaSerializer,
    PublicCompanyProfileResponseSerializer,
)
from backend.adminops.models import CompanyProfile
from backend.catalog.api.serializers import (
    AdminServiceListResponseSerializer,
    AdminServiceProviderSerializer,
    AdminServiceResponseSerializer,
    AdminServiceSummarySerializer,
    ExpectedVersionSerializer,
    MoneySerializer,
    ProviderTagResponseSerializer,
    ServiceCategoryResponseSerializer,
    ServiceCreateRequestSerializer,
    ServiceListResponseSerializer,
    ServiceResponseSerializer,
    ServiceReviewRequestSerializer,
    ServiceSummarySerializer,
    ServiceTagResponseSerializer,
    ServiceUpdateRequestSerializer,
)
from backend.catalog.models import (
    ProviderService,
    ProviderServiceEvent,
    ProviderServiceGalleryMedia,
    ProviderServiceTag,
    ProviderTag,
    ServiceCategory,
    ServiceTag,
)
from backend.content.api.news_serializers import (
    NewsArticleInputSerializer,
    NewsArticleResponseSerializer,
    NewsAttachmentInputSerializer,
    NewsAttachmentResponseSerializer,
    NewsCategoryResponseSerializer,
    NewsDeleteRequestSerializer,
    NewsListResponseSerializer,
    NewsMerchantSummarySerializer,
    NewsMountInputSerializer,
    NewsMountResponseSerializer,
    NewsReviewRequestSerializer,
    NewsShareResponseSerializer,
    NewsSourceInputSerializer,
    NewsSourceResponseSerializer,
    NewsSyncRequestSerializer,
    NewsSyncRunResponseSerializer,
    NewsUpdateRequestSerializer,
    NewsVersionRequestSerializer,
)
from backend.content.api.serializers import (
    AdminMomentListResponseSerializer,
    MomentCategoryResponseSerializer,
    MomentExpectedVersionSerializer,
    MomentFeedContextSerializer,
    MomentInputSerializer,
    MomentListResponseSerializer,
    MomentNeighborsResponseSerializer,
    MomentProviderSerializer,
    MomentResponseSerializer,
    MomentReviewRequestSerializer,
    MomentSummarySerializer,
    MomentTagResponseSerializer,
    MomentUpdateRequestSerializer,
    MountableServiceSerializer,
)
from backend.content.models import (
    Moment,
    MomentCategory,
    MomentEvent,
    MomentMedia,
    MomentTag,
    MomentTagLink,
)
from backend.content.news_models import (
    NewsArticle,
    NewsArticleAttachment,
    NewsArticleCategory,
    NewsArticleEvent,
    NewsArticleMount,
    NewsCategory,
    NewsSource,
    NewsSyncRun,
)
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
    CouponRedemptionResponseSerializer,
    CouponResponseSerializer,
)
from backend.coupons.models import (
    CouponInstance,
    CouponRedemption,
    CouponStatusLog,
    CouponTemplate,
)
from backend.discovery.api.serializers import (
    AdminTrendingCreateResponseSerializer,
    AdminTrendingCreateSerializer,
    AdminTrendingKeywordResponseSerializer,
    AdminTrendingListResponseSerializer,
    AdminTrendingUpdateResponseSerializer,
    AdminTrendingUpdateSerializer,
    HomeFeedItemSerializer,
    HomeFeedLocationRequestSerializer,
    HomeProviderSerializer,
    HomeServiceSerializer,
    HomeVerificationSerializer,
    SearchMomentGroupSerializer,
    SearchMomentListResponseSerializer,
    SearchNewsGroupSerializer,
    SearchNewsListResponseSerializer,
    SearchProviderGroupSerializer,
    SearchProviderListResponseSerializer,
    SearchResponseSerializer,
    TrendingKeywordResponseSerializer,
    TrendingListResponseSerializer,
)
from backend.discovery.models import SearchQueryStat, SearchTrendingKeyword
from backend.identity.models import IdentityVerification
from backend.locations.api.serializers import (
    LocationQuickKeywordAdminListResponseSerializer,
    LocationQuickKeywordAdminResponseSerializer,
    LocationQuickKeywordCreateSerializer,
    LocationQuickKeywordDeactivateSerializer,
    LocationQuickKeywordListResponseSerializer,
    LocationQuickKeywordResponseSerializer,
    LocationQuickKeywordUpdateSerializer,
    LocationSearchItemSerializer,
    LocationSearchQuerySerializer,
    LocationSearchResponseSerializer,
    ProviderLocationStatusResponseSerializer,
    ProviderLocationUpdateSerializer,
)
from backend.locations.models import (
    LocationSearchKeyword,
    LocationSearchRule,
    ProviderLocationState,
)
from backend.media.api.serializers import (
    MediaAssetResponseSerializer,
    MediaAssetSummarySerializer,
    MediaUploadRequestSerializer,
)
from backend.media.models import MediaAsset
from backend.memberships.api.serializers import (
    AdminMembershipPlanCreateRequestSerializer,
    AdminMembershipPlanUpdateRequestSerializer,
    AdminMembershipPurchaseListResponseSerializer,
    MembershipBenefitResponseSerializer,
    MembershipPaymentResponseSerializer,
    MembershipPeriodResponseSerializer,
    MembershipPlanListResponseSerializer,
    MembershipPlanResponseSerializer,
    MembershipPurchaseCreateRequestSerializer,
    MembershipPurchaseListResponseSerializer,
    MembershipPurchaseResponseSerializer,
    MembershipPurchaseResultSerializer,
    MembershipSummaryResponseSerializer,
)
from backend.memberships.models import (
    MembershipAccount,
    MembershipBenefitGrant,
    MembershipPeriod,
    MembershipPlan,
    MembershipPlanVersion,
    MembershipPurchase,
    MembershipStatusLog,
)
from backend.messaging.api.serializers import (
    ChatOrderSummarySerializer,
    ChatUserSummarySerializer,
    ConversationListResponseSerializer,
    ConversationReadRequestSerializer,
    ConversationReadResponseSerializer,
    ConversationResponseSerializer,
    MessageAckSerializer,
    MessageCreateRequestSerializer,
    MessageCreateResponseSerializer,
    MessageListResponseSerializer,
    MessageResponseSerializer,
    UnreadConversationSerializer,
    UnreadSummaryResponseSerializer,
    WebSocketTicketResponseSerializer,
)
from backend.messaging.models import (
    Conversation,
    ConversationMember,
    Message,
    MessageDelivery,
    MessagingConnectionTicket,
)
from backend.orders.api.serializers import (
    OrderActionRequestSerializer,
    OrderContactSerializer,
    OrderCouponResponseSerializer,
    OrderCreateRequestSerializer,
    OrderCustomerParticipantSerializer,
    OrderMeetingLocationSerializer,
    OrderNextActionSerializer,
    OrderParticipantsSerializer,
    OrderPayRequestSerializer,
    OrderPriceSerializer,
    OrderProgressEventSerializer,
    OrderProgressSerializer,
    OrderProviderParticipantSerializer,
    OrderQuoteDiscountSerializer,
    OrderQuoteLineSerializer,
    OrderQuoteRequestSerializer,
    OrderQuoteResponseSerializer,
    OrderRefundRequestCreateSerializer,
    OrderRefundRequestListResponseSerializer,
    OrderRefundRequestSerializer,
    OrderRefundRetryRequestSerializer,
    OrderRefundReviewRequestSerializer,
    OrderResponseSerializer,
    OrderServiceResponseSerializer,
    OrderSummaryResponseSerializer,
    OrderVersionRequestSerializer,
)
from backend.orders.models import (
    Order,
    OrderRefundRequest,
    OrderScheduleSlot,
    OrderStatusLog,
)
from backend.payments.models import Payment, Refund
from backend.payouts.api.serializers import (
    EarningAccountResponseSerializer,
    EarningEntryListResponseSerializer,
    EarningEntryResponseSerializer,
    EarningTransactionListResponseSerializer,
    EarningTransactionResponseSerializer,
    PayoutMethodCreateRequestSerializer,
    PayoutMethodExpectedVersionSerializer,
    PayoutMethodListResponseSerializer,
    PayoutMethodResponseSerializer,
    WithdrawalCreateRequestSerializer,
    WithdrawalExpectedVersionSerializer,
    WithdrawalListResponseSerializer,
    WithdrawalPayoutMethodSerializer,
    WithdrawalResponseSerializer,
    WithdrawalReviewRequestSerializer,
)
from backend.payouts.models import (
    EarningAccount,
    EarningEntry,
    EarningTransaction,
    PayoutMethod,
    PayoutMethodEvent,
    Withdrawal,
    WithdrawalStatusLog,
)
from backend.profiles.api.serializers import (
    CityOptionResponseSerializer,
    InterestTagResponseSerializer,
    ProfileResponseSerializer,
    ProfileSummaryResponseSerializer,
    ProfileUpdateRequestSerializer,
    ProfileUpdateResponseSerializer,
    TrustLevelResponseSerializer,
)
from backend.profiles.models import (
    InterestTag,
    ProfileCityOption,
    UserProfile,
    UserProfileInterest,
)
from backend.providers.api.profile_serializers import (
    ProviderCategoryDisplaySerializer,
    ProviderProfileInputSerializer,
    ProviderProfileResponseSerializer,
    ProviderProfileUpdateResponseSerializer,
    ProviderTagDisplaySerializer,
)
from backend.providers.api.serializers import (
    ProviderApplicationInputSerializer,
    ProviderApplicationResponseSerializer,
    ProviderApplicationUpdateRequestSerializer,
    ProviderReviewRequestSerializer,
)
from backend.providers.models import (
    ProviderApplication,
    ProviderApplicationEvent,
    ProviderProfile,
    ProviderProfileCategory,
    ProviderProfileMedia,
    ProviderProfileTag,
)
from backend.reviews.api.serializers import (
    MyReviewItemSerializer,
    MyReviewListResponseSerializer,
    ProviderReviewListResponseSerializer,
    ProviderReviewSummarySerializer,
    ReviewListSummarySerializer,
    ReviewReplyRequestSerializer,
    ReviewReplyResponseSerializer,
    ReviewReplySummarySerializer,
    ReviewRequestSerializer,
    ReviewResponseSerializer,
    ReviewServiceSummarySerializer,
    ReviewUserSummarySerializer,
)
from backend.reviews.models import (
    ProviderRatingStat,
    Review,
    ReviewReply,
    ReviewTag,
    ReviewTagLink,
)
from backend.scheduling.api.serializers import (
    AvailabilityQuerySerializer,
    PublicAvailabilitySlotSerializer,
    ScheduleBulkErrorSerializer,
    ScheduleBulkUpdateResponseSerializer,
    ScheduleBulkUpdateSerializer,
    ScheduleCalendarQuerySerializer,
    ScheduleCalendarResponseSerializer,
    ScheduleCalendarSummarySerializer,
    ScheduleDayQuerySerializer,
    ScheduleDayResponseSerializer,
    ScheduleDaySerializer,
    ScheduleRuleCreateSerializer,
    ScheduleRuleDeleteResponseSerializer,
    ScheduleRuleDeleteSerializer,
    ScheduleRuleResponseSerializer,
    ScheduleRuleUpdateSerializer,
    ScheduleSlotCreateSerializer,
    ScheduleSlotDeleteResponseSerializer,
    ScheduleSlotDeleteSerializer,
    ScheduleSlotMutationResponseSerializer,
    ScheduleSlotResponseSerializer,
    ScheduleSlotServiceSerializer,
    ScheduleSlotStatusSerializer,
)
from backend.scheduling.models import ScheduleSlot
from backend.social.api.serializers import (
    CommentRequestSerializer,
    CommentResponseSerializer,
    FavoriteRequestSerializer,
    FavoriteResponseSerializer,
    FollowResponseSerializer,
    LikeResponseSerializer,
)
from backend.social.models import (
    Comment,
    CommentEvent,
    Favorite,
    MomentLike,
    UserFollow,
)
from backend.wallets.api.serializers import (
    WalletResponseSerializer,
    WalletTopUpRequestSerializer,
    WalletTopUpResponseSerializer,
    WalletTransactionResponseSerializer,
)
from backend.wallets.models import WalletAccount, WalletTopUp, WalletTransaction

CHINESE_PATTERN = re.compile(r"[\u4e00-\u9fff]")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUSINESS_MODULES = [
    "backend/adminops/company_services.py",
    "backend/adminops/display.py",
    "backend/accounts/services.py",
    "backend/accounts/authentication.py",
    "backend/identity/services.py",
    "backend/media/services.py",
    "backend/media/storage.py",
    "backend/providers/services.py",
    "backend/providers/profile_services.py",
    "backend/providers/public_services.py",
    "backend/profiles/services.py",
    "backend/catalog/services.py",
    "backend/discovery/services.py",
    "backend/discovery/search_services.py",
    "backend/discovery/trending_services.py",
    "backend/content/services.py",
    "backend/content/news_models.py",
    "backend/content/news_services.py",
    "backend/content/news_adapters.py",
    "backend/content/tasks.py",
    "backend/wallets/services.py",
    "backend/payments/services.py",
    "backend/coupons/services.py",
    "backend/memberships/services.py",
    "backend/social/services.py",
    "backend/scheduling/services.py",
    "backend/orders/services.py",
    "backend/messaging/services.py",
    "backend/messaging/consumers.py",
    "backend/messaging/tasks.py",
    "backend/reviews/services.py",
    "backend/payouts/services.py",
    "backend/payouts/adapters.py",
    "backend/locations/services.py",
    "backend/integrations/geo/contracts.py",
    "backend/integrations/geo/coordinates.py",
    "backend/integrations/geo/tencent.py",
    "backend/common/crypto.py",
    "backend/common/display.py",
    "backend/common/search.py",
]
MODEL_CLASSES = [
    CompanyProfile,
    AccountDeletionRecord,
    AccountSecurityEvent,
    PhoneChangeRequest,
    User,
    UserAuth,
    VerificationSendGuard,
    VerificationCode,
    LoginRequest,
    AuthToken,
    IdentityVerification,
    MediaAsset,
    ProviderApplication,
    ProviderApplicationEvent,
    InterestTag,
    ProfileCityOption,
    UserProfile,
    UserProfileInterest,
    ServiceCategory,
    ServiceTag,
    ProviderTag,
    ProviderService,
    ProviderServiceGalleryMedia,
    ProviderServiceTag,
    ProviderServiceEvent,
    ProviderProfile,
    ProviderProfileCategory,
    ProviderProfileTag,
    ProviderProfileMedia,
    MomentCategory,
    MomentTag,
    Moment,
    MomentMedia,
    MomentTagLink,
    MomentEvent,
    NewsCategory,
    NewsSource,
    NewsArticle,
    NewsArticleCategory,
    NewsArticleAttachment,
    NewsArticleMount,
    NewsArticleEvent,
    NewsSyncRun,
    SearchQueryStat,
    SearchTrendingKeyword,
    LocationSearchKeyword,
    LocationSearchRule,
    ProviderLocationState,
    WalletAccount,
    WalletTransaction,
    WalletTopUp,
    Payment,
    Refund,
    UserFollow,
    Favorite,
    MomentLike,
    Comment,
    CommentEvent,
    ScheduleSlot,
    Order,
    OrderRefundRequest,
    OrderScheduleSlot,
    OrderStatusLog,
    Conversation,
    ConversationMember,
    Message,
    MessagingConnectionTicket,
    MessageDelivery,
    ReviewTag,
    Review,
    ReviewTagLink,
    ReviewReply,
    ProviderRatingStat,
    PayoutMethod,
    PayoutMethodEvent,
    EarningAccount,
    EarningEntry,
    EarningTransaction,
    Withdrawal,
    WithdrawalStatusLog,
    CouponTemplate,
    CouponInstance,
    CouponRedemption,
    CouponStatusLog,
    MembershipPlan,
    MembershipPlanVersion,
    MembershipAccount,
    MembershipPurchase,
    MembershipPeriod,
    MembershipBenefitGrant,
    MembershipStatusLog,
]
SERIALIZER_CLASSES = [
    AccountSecurityResponseSerializer,
    SecuritySmsResponseSerializer,
    PasswordChangeRequestSerializer,
    PasswordChangeResponseSerializer,
    PasswordForgotSmsRequestSerializer,
    PasswordResetRequestSerializer,
    PasswordResetResponseSerializer,
    PhoneChangeRequestSerializer,
    PhoneChangeResponseSerializer,
    PhoneChangeConfirmRequestSerializer,
    PhoneChangeConfirmResponseSerializer,
    AccountDeletionCheckItemSerializer,
    AccountDeletionCheckResponseSerializer,
    AccountDeletionConfirmRequestSerializer,
    AccountDeletionSmsResponseSerializer,
    AccountDeletionResponseSerializer,
    AdminCompanyProfileResponseSerializer,
    AdminCompanyProfileUpdateRequestSerializer,
    AdminCompanyLicenseUploadRequestSerializer,
    PublicCompanyProfileResponseSerializer,
    PublicCompanyLicenseMediaSerializer,
    SmsCodeRequestSerializer,
    SmsCodeResponseSerializer,
    LoginRequestSerializer,
    PasswordLoginRequestSerializer,
    DevPasswordLoginRequestSerializer,
    RefreshRequestSerializer,
    TokenPairResponseSerializer,
    SessionResponseSerializer,
    LogoutResponseSerializer,
    InitialRoleRequestSerializer,
    InitialRoleResponseSerializer,
    MediaUploadRequestSerializer,
    MediaAssetSummarySerializer,
    MediaAssetResponseSerializer,
    ProviderApplicationInputSerializer,
    ProviderApplicationUpdateRequestSerializer,
    ProviderApplicationResponseSerializer,
    ProviderReviewRequestSerializer,
    CityOptionResponseSerializer,
    InterestTagResponseSerializer,
    TrustLevelResponseSerializer,
    ProfileResponseSerializer,
    ProfileSummaryResponseSerializer,
    ProfileUpdateRequestSerializer,
    ProfileUpdateResponseSerializer,
    MoneySerializer,
    ServiceCategoryResponseSerializer,
    ServiceTagResponseSerializer,
    ProviderTagResponseSerializer,
    ServiceCreateRequestSerializer,
    ServiceUpdateRequestSerializer,
    ServiceResponseSerializer,
    ServiceSummarySerializer,
    ServiceListResponseSerializer,
    ExpectedVersionSerializer,
    ServiceReviewRequestSerializer,
    AdminServiceProviderSerializer,
    AdminServiceResponseSerializer,
    AdminServiceSummarySerializer,
    AdminServiceListResponseSerializer,
    SearchProviderGroupSerializer,
    SearchMomentGroupSerializer,
    SearchNewsGroupSerializer,
    SearchResponseSerializer,
    SearchProviderListResponseSerializer,
    SearchMomentListResponseSerializer,
    SearchNewsListResponseSerializer,
    TrendingKeywordResponseSerializer,
    TrendingListResponseSerializer,
    AdminTrendingKeywordResponseSerializer,
    AdminTrendingCreateResponseSerializer,
    AdminTrendingUpdateResponseSerializer,
    AdminTrendingListResponseSerializer,
    AdminTrendingCreateSerializer,
    AdminTrendingUpdateSerializer,
    LocationSearchQuerySerializer,
    LocationSearchItemSerializer,
    LocationSearchResponseSerializer,
    LocationQuickKeywordResponseSerializer,
    LocationQuickKeywordListResponseSerializer,
    LocationQuickKeywordAdminResponseSerializer,
    LocationQuickKeywordAdminListResponseSerializer,
    LocationQuickKeywordCreateSerializer,
    LocationQuickKeywordUpdateSerializer,
    LocationQuickKeywordDeactivateSerializer,
    ProviderLocationUpdateSerializer,
    ProviderLocationStatusResponseSerializer,
    HomeProviderSerializer,
    HomeServiceSerializer,
    HomeVerificationSerializer,
    HomeFeedItemSerializer,
    HomeFeedLocationRequestSerializer,
    ProviderCategoryDisplaySerializer,
    ProviderProfileInputSerializer,
    ProviderProfileResponseSerializer,
    ProviderProfileUpdateResponseSerializer,
    ProviderTagDisplaySerializer,
    MomentTagResponseSerializer,
    MomentCategoryResponseSerializer,
    MomentInputSerializer,
    MomentUpdateRequestSerializer,
    MomentProviderSerializer,
    MomentResponseSerializer,
    MomentListResponseSerializer,
    MomentFeedContextSerializer,
    MomentNeighborsResponseSerializer,
    MomentSummarySerializer,
    AdminMomentListResponseSerializer,
    MomentExpectedVersionSerializer,
    MomentReviewRequestSerializer,
    MountableServiceSerializer,
    NewsCategoryResponseSerializer,
    NewsArticleInputSerializer,
    NewsUpdateRequestSerializer,
    NewsArticleResponseSerializer,
    NewsListResponseSerializer,
    NewsAttachmentInputSerializer,
    NewsAttachmentResponseSerializer,
    NewsMountInputSerializer,
    NewsMountResponseSerializer,
    NewsMerchantSummarySerializer,
    NewsReviewRequestSerializer,
    NewsDeleteRequestSerializer,
    NewsVersionRequestSerializer,
    NewsShareResponseSerializer,
    NewsSourceInputSerializer,
    NewsSourceResponseSerializer,
    NewsSyncRequestSerializer,
    NewsSyncRunResponseSerializer,
    WalletResponseSerializer,
    WalletTransactionResponseSerializer,
    WalletTopUpRequestSerializer,
    WalletTopUpResponseSerializer,
    OrderCreateRequestSerializer,
    OrderContactSerializer,
    OrderCustomerParticipantSerializer,
    OrderMeetingLocationSerializer,
    OrderNextActionSerializer,
    OrderPayRequestSerializer,
    OrderParticipantsSerializer,
    OrderProgressEventSerializer,
    OrderProgressSerializer,
    OrderProviderParticipantSerializer,
    OrderRefundRequestCreateSerializer,
    OrderRefundRequestListResponseSerializer,
    OrderRefundRequestSerializer,
    OrderRefundRetryRequestSerializer,
    OrderRefundReviewRequestSerializer,
    OrderQuoteRequestSerializer,
    OrderQuoteResponseSerializer,
    OrderQuoteLineSerializer,
    OrderQuoteDiscountSerializer,
    OrderActionRequestSerializer,
    OrderVersionRequestSerializer,
    OrderPriceSerializer,
    OrderResponseSerializer,
    OrderServiceResponseSerializer,
    OrderSummaryResponseSerializer,
    OrderCouponResponseSerializer,
    CouponResponseSerializer,
    CouponListResponseSerializer,
    CouponClaimRequestSerializer,
    CouponClaimResponseSerializer,
    CouponRedemptionResponseSerializer,
    CouponRedemptionListResponseSerializer,
    AdminCouponTemplateResponseSerializer,
    AdminCouponTemplateListResponseSerializer,
    AdminCouponTemplateCreateRequestSerializer,
    AdminCouponTemplateUpdateRequestSerializer,
    AdminCouponIssueRequestSerializer,
    AdminCouponIssueResponseSerializer,
    AdminCouponRevokeRequestSerializer,
    MembershipPlanResponseSerializer,
    MembershipPlanListResponseSerializer,
    MembershipBenefitResponseSerializer,
    MembershipPeriodResponseSerializer,
    MembershipSummaryResponseSerializer,
    MembershipPurchaseCreateRequestSerializer,
    MembershipPaymentResponseSerializer,
    MembershipPurchaseResponseSerializer,
    MembershipPurchaseResultSerializer,
    MembershipPurchaseListResponseSerializer,
    AdminMembershipPlanCreateRequestSerializer,
    AdminMembershipPlanUpdateRequestSerializer,
    AdminMembershipPurchaseListResponseSerializer,
    ScheduleSlotCreateSerializer,
    ScheduleSlotDeleteSerializer,
    ScheduleSlotDeleteResponseSerializer,
    ScheduleSlotMutationResponseSerializer,
    ScheduleSlotResponseSerializer,
    ScheduleSlotServiceSerializer,
    ScheduleSlotStatusSerializer,
    AvailabilityQuerySerializer,
    PublicAvailabilitySlotSerializer,
    ScheduleCalendarQuerySerializer,
    ScheduleCalendarResponseSerializer,
    ScheduleCalendarSummarySerializer,
    ScheduleDayQuerySerializer,
    ScheduleDayResponseSerializer,
    ScheduleDaySerializer,
    ScheduleBulkUpdateSerializer,
    ScheduleBulkUpdateResponseSerializer,
    ScheduleBulkErrorSerializer,
    ScheduleRuleCreateSerializer,
    ScheduleRuleUpdateSerializer,
    ScheduleRuleResponseSerializer,
    ScheduleRuleDeleteSerializer,
    ScheduleRuleDeleteResponseSerializer,
    FollowResponseSerializer,
    FavoriteRequestSerializer,
    FavoriteResponseSerializer,
    LikeResponseSerializer,
    CommentRequestSerializer,
    CommentResponseSerializer,
    ReviewRequestSerializer,
    ReviewResponseSerializer,
    ReviewReplyRequestSerializer,
    ReviewReplyResponseSerializer,
    ReviewServiceSummarySerializer,
    ReviewUserSummarySerializer,
    ReviewReplySummarySerializer,
    ReviewListSummarySerializer,
    MyReviewItemSerializer,
    MyReviewListResponseSerializer,
    ProviderReviewSummarySerializer,
    ProviderReviewListResponseSerializer,
    PayoutMethodCreateRequestSerializer,
    PayoutMethodExpectedVersionSerializer,
    PayoutMethodResponseSerializer,
    PayoutMethodListResponseSerializer,
    EarningAccountResponseSerializer,
    EarningEntryResponseSerializer,
    EarningEntryListResponseSerializer,
    EarningTransactionResponseSerializer,
    EarningTransactionListResponseSerializer,
    WithdrawalCreateRequestSerializer,
    WithdrawalExpectedVersionSerializer,
    WithdrawalReviewRequestSerializer,
    WithdrawalPayoutMethodSerializer,
    WithdrawalResponseSerializer,
    WithdrawalListResponseSerializer,
    ChatUserSummarySerializer,
    ChatOrderSummarySerializer,
    MessageResponseSerializer,
    ConversationResponseSerializer,
    ConversationListResponseSerializer,
    MessageListResponseSerializer,
    MessageCreateRequestSerializer,
    MessageCreateResponseSerializer,
    MessageAckSerializer,
    ConversationReadRequestSerializer,
    ConversationReadResponseSerializer,
    UnreadConversationSerializer,
    UnreadSummaryResponseSerializer,
    WebSocketTicketResponseSerializer,
]


def _has_chinese(value: str | None) -> bool:
    return bool(value and CHINESE_PATTERN.search(value))


@pytest.mark.parametrize("model_class", MODEL_CLASSES)
def test_every_model_table_and_field_has_chinese_database_comment(model_class) -> None:
    assert _has_chinese(model_class._meta.db_table_comment), (
        f"{model_class.__name__} 缺少中文表备注"
    )
    for field in model_class._meta.fields:
        assert _has_chinese(field.db_comment), (
            f"{model_class.__name__}.{field.name} 缺少中文字段备注"
        )


@pytest.mark.parametrize("relative_path", BUSINESS_MODULES)
def test_business_modules_have_chinese_module_and_public_callable_comments(
    relative_path: str,
) -> None:
    tree = ast.parse((PROJECT_ROOT / relative_path).read_text(encoding="utf-8"))
    assert _has_chinese(ast.get_docstring(tree)), f"{relative_path} 缺少中文模块说明"

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            assert _has_chinese(ast.get_docstring(node)), (
                f"{relative_path}:{node.name} 缺少中文类说明"
            )
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and not child.name.startswith("_"):
                    assert _has_chinese(ast.get_docstring(child)), (
                        f"{relative_path}:{node.name}.{child.name} 缺少中文方法说明"
                    )
        elif isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            assert _has_chinese(ast.get_docstring(node)), (
                f"{relative_path}:{node.name} 缺少中文函数说明"
            )


@pytest.mark.parametrize("serializer_class", SERIALIZER_CLASSES)
def test_api_serializer_fields_have_chinese_help_text(serializer_class) -> None:
    for field_name, field in serializer_class().fields.items():
        assert _has_chinese(field.help_text), (
            f"{serializer_class.__name__}.{field_name} 缺少中文接口参数说明"
        )


def test_schedule_openapi_documents_query_and_response_contracts() -> None:
    schema = (PROJECT_ROOT / "openapi.yaml").read_text(encoding="utf-8")
    assert "/api/v1/provider-schedule/calendar/:" in schema
    for parameter in (
        "name: view",
        "name: date",
        "name: date_from",
        "name: date_to",
        "name: timezone",
    ):
        assert parameter in schema
    for response_model in (
        "ScheduleCalendarResponse:",
        "ScheduleDayResponse:",
        "ScheduleBulkUpdateResponse:",
        "PublicAvailabilitySlot:",
    ):
        assert response_model in schema
    assert (
        "additionalProperties: {}"
        not in schema.split("ScheduleCalendarResponse:", 1)[1].split("ScheduleCalendarSummary:", 1)[
            0
        ]
    )


def test_search_openapi_documents_query_and_response_contracts() -> None:
    schema = (PROJECT_ROOT / "openapi.yaml").read_text(encoding="utf-8")
    for endpoint in (
        "/api/v1/search/:",
        "/api/v1/search/providers/:",
        "/api/v1/search/moments/:",
        "/api/v1/search/news/:",
        "/api/v1/search/trending/:",
        "/api/v1/admin/search/trending/:",
        "/api/v1/admin/search/trending/{trending_id}/:",
    ):
        assert endpoint in schema
    for response_model in (
        "SearchResponse:",
        "SearchProviderListResponse:",
        "SearchMomentListResponse:",
        "SearchNewsListResponse:",
        "TrendingListResponse:",
        "AdminTrendingListResponse:",
    ):
        assert response_model in schema
    search_contract = schema.split("/api/v1/search/:", 1)[1].split(
        "/api/v1/search/providers/:",
        1,
    )[0]
    for parameter in ("name: keyword", "name: limit"):
        assert parameter in search_contract
    assert "$ref: '#/components/schemas/SearchResponse'" in search_contract


def test_dev_password_login_openapi_documents_development_contract() -> None:
    schema = (PROJECT_ROOT / "openapi.yaml").read_text(encoding="utf-8")
    assert "/api/v1/dev/auth/password-login/:" in schema
    login_contract = schema.split("/api/v1/dev/auth/password-login/:", 1)[1]
    assert "DevPasswordLoginRequest" in login_contract
    assert "TokenPairResponse" in login_contract
    assert "仅供开发测试" in login_contract
    assert "生产环境强制禁用" in login_contract
    assert "$ref: '#/components/schemas/DevPasswordLoginRequestRequest'" in login_contract


def test_location_search_openapi_documents_query_and_response_contracts() -> None:
    schema = (PROJECT_ROOT / "openapi.yaml").read_text(encoding="utf-8")
    for endpoint in (
        "/api/v1/location-search/quick-keywords/:",
        "/api/v1/location-search/:",
        "/api/v1/provider/location/:",
        "/api/v1/admin/location-search/quick-keywords/:",
        "/api/v1/admin/location-search/quick-keywords/{keyword_id}/:",
    ):
        assert endpoint in schema
    search_contract = schema.split("/api/v1/location-search/:", 1)[1].split(
        "/api/v1/admin/location-search/quick-keywords/:",
        1,
    )[0]
    for parameter in (
        "name: keyword",
        "name: quick_keyword_code",
        "name: latitude",
        "name: longitude",
        "name: coordinate_system",
        "name: radius_m",
        "name: limit",
    ):
        assert parameter in search_contract
    for response_model in (
        "LocationSearchResponse:",
        "LocationSearchItem:",
        "LocationQuickKeywordListResponse:",
        "LocationQuickKeywordAdminListResponse:",
        "ProviderLocationStatusResponse:",
        "OrderMeetingLocation:",
        "HomeFeedLocationRequestRequest:",
    ):
        assert response_model in schema
    assert "listHomeFeedWithLocation" in schema
    assert "selection_token:" in schema
    assert "meeting_location:" in schema


def test_coupon_and_membership_openapi_documents_contracts() -> None:
    schema = (PROJECT_ROOT / "openapi.yaml").read_text(encoding="utf-8")
    for endpoint in (
        "/api/v1/coupons/:",
        "/api/v1/coupons/{coupon_no}/:",
        "/api/v1/coupon-templates/{template_no}/claim/:",
        "/api/v1/membership/:",
        "/api/v1/membership/plans/:",
        "/api/v1/membership/purchases/:",
        "/api/v1/membership/purchases/{purchase_no}/:",
        "/admin/v1/coupons/templates/:",
        "/admin/v1/coupons/issue/:",
        "/admin/v1/coupons/redemptions/:",
        "/admin/v1/membership/plans/:",
        "/admin/v1/membership/purchases/:",
    ):
        assert endpoint in schema
    for response_model in (
        "CouponResponse:",
        "CouponListResponse:",
        "CouponClaimResponse:",
        "CouponRedemptionListResponse:",
        "AdminCouponTemplateResponse:",
        "MembershipPlanResponse:",
        "MembershipSummaryResponse:",
        "MembershipPurchaseResponse:",
        "MembershipPurchaseResult:",
    ):
        assert response_model in schema
    contract = schema.split("/api/v1/orders/quotes/:", 1)[1]
    assert "coupon_no:" in contract
    assert "discount_amount_minor:" in contract
    assert "$ref: '#/components/schemas/OrderCouponResponse'" in schema
