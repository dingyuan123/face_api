"""账号注销条件检查、短信确认、数据清理和不可变审计服务。"""

from __future__ import annotations

import re
from typing import Any

from django.contrib.auth.hashers import check_password
from django.db import transaction
from django.db.models import F, Q, Sum
from django.utils import timezone

from backend.accounts.models import (
    AccountDeletionRecord,
    AuthToken,
    LoginRequest,
    User,
    UserAuth,
    VerificationCode,
)
from backend.accounts.services import send_sms_code
from backend.catalog.models import ProviderService
from backend.common.context import current_trace_id
from backend.common.crypto import decrypt_text, sensitive_fingerprint
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.content.models import Moment, MomentMedia, MomentTagLink
from backend.identity.models import IdentityVerification
from backend.media.models import MediaAsset
from backend.media.storage import delete as delete_media_file
from backend.orders.models import Order, OrderRefundRequest
from backend.payouts.models import (
    EarningAccount,
    EarningEntry,
    EarningTransaction,
    Withdrawal,
    WithdrawalStatusLog,
)
from backend.profiles.models import UserProfile
from backend.providers.models import ProviderApplication, ProviderProfile
from backend.referrals.models import ReferralReward, ReferralRewardStatusLog
from backend.social.models import Comment, Favorite, MomentLike, UserFollow
from backend.support.models import SupportTicket
from backend.wallets.models import WalletAccount, WalletTransaction

CODE_PATTERN = re.compile(r"^\d{6}$")

RETAINED_CATEGORIES = [
    "ORDERS",
    "PAYMENTS",
    "REFUNDS",
    "PAYOUTS",
    "SECURITY_LOGS",
    "CHAT_HISTORY",
    "SUPPORT_RECORDS",
    "REVIEW_RECORDS",
    "AUDIT_LOGS",
]


def _invalid(field: str, message: str) -> ApiError:
    """返回账号注销参数校验错误。"""
    return ApiError(
        ErrorCode.ACCOUNT_DELETION_INVALID,
        message,
        status_code=400,
        details={field: message},
    )


def _amount_text(amount_minor: int) -> str:
    """将人民币分转换为注销条件展示文本。"""
    return f"¥{amount_minor / 100:.2f}"


def _item(
    *,
    key: str,
    title: str,
    description: str,
    passed: bool,
    action: str,
    action_route: str,
) -> dict[str, Any]:
    """构造前端固定四项注销条件之一。"""
    return {
        "key": key,
        "title": title,
        "description": description,
        "passed": passed,
        "action": action if not passed else "已通过",
        "action_route": action_route if not passed else "",
    }


def account_deletion_check(*, user: User) -> dict[str, Any]:
    """检查订单、资金、服务发布和账号安全四项注销条件。"""
    active_order_statuses = [
        Order.Status.PENDING_PAYMENT,
        Order.Status.PENDING_ACCEPT,
        Order.Status.PENDING_SERVICE,
        Order.Status.IN_SERVICE,
        Order.Status.PENDING_CONFIRM,
    ]
    active_order_count = user.orders.filter(status__in=active_order_statuses).count()
    active_refund_count = OrderRefundRequest.objects.filter(
        Q(order__user=user) | Q(order__provider_user=user),
        status__in=[
            OrderRefundRequest.Status.PENDING,
            OrderRefundRequest.Status.PROCESSING,
            OrderRefundRequest.Status.FAILED,
        ],
    ).count()
    orders_passed = active_order_count == 0 and active_refund_count == 0
    if not orders_passed:
        order_description = (
            f"有 {active_order_count} 笔进行中的订单、{active_refund_count} 笔处理中售后"
        )
    else:
        order_description = "没有进行中的订单或售后"

    wallet_balance = (
        WalletAccount.objects.filter(user=user).aggregate(
            total=Sum("balance_amount_minor") + Sum("frozen_amount_minor")
        )["total"]
        or 0
    )
    earning_balance = (
        EarningAccount.objects.filter(user=user).aggregate(
            total=Sum("available_amount_minor") + Sum("frozen_amount_minor")
        )["total"]
        or 0
    )
    pending_earning = (
        EarningEntry.objects.filter(
            user=user,
            status=EarningEntry.Status.PENDING_SETTLEMENT,
        ).aggregate(total=Sum("net_amount_minor"))["total"]
        or 0
    )
    pending_reward = (
        ReferralReward.objects.filter(
            inviter_user=user,
            status__in=[
                ReferralReward.Status.PENDING_SETTLEMENT,
                ReferralReward.Status.FROZEN,
            ],
        ).aggregate(total=Sum("amount_minor"))["total"]
        or 0
    )
    pending_withdrawal_count = user.withdrawals.filter(
        status__in=[
            Withdrawal.Status.PENDING_REVIEW,
            Withdrawal.Status.PROCESSING,
        ]
    ).count()
    blocked_amount_minor = wallet_balance + earning_balance + pending_earning + pending_reward
    wallet_passed = blocked_amount_minor == 0 and pending_withdrawal_count == 0
    if wallet_passed:
        wallet_description = "没有可提现余额、待结算收益或处理中提现"
    else:
        wallet_description = (
            f"待处理资金 {_amount_text(blocked_amount_minor)}，"
            f"{pending_withdrawal_count} 笔提现处理中"
        )

    active_service_count = ProviderService.objects.filter(
        provider_user=user,
        deleted_at__isnull=True,
        status__in=[
            ProviderService.Status.PENDING,
            ProviderService.Status.APPROVED,
            ProviderService.Status.ONLINE,
        ],
    ).count()
    pending_provider_review_count = (
        ProviderApplication.objects.filter(
            user=user,
            status=ProviderApplication.Status.PENDING,
        ).count()
        + IdentityVerification.objects.filter(
            user=user,
            status=IdentityVerification.Status.PENDING,
        ).count()
    )
    services_passed = active_service_count == 0 and pending_provider_review_count == 0
    services_description = (
        "没有上架、审核中服务或待审核资料"
        if services_passed
        else (
            f"有 {active_service_count} 个上架或审核中服务、"
            f"{pending_provider_review_count} 项待审核资料"
        )
    )

    open_support_count = user.support_tickets.filter(
        status__in=[SupportTicket.Status.OPEN, SupportTicket.Status.PENDING]
    ).count()
    security_blockers = []
    if not user.phone_hash:
        security_blockers.append("未绑定手机号")
    if user.status != User.Status.ACTIVE:
        security_blockers.append("账号存在状态限制")
    if user.is_staff:
        security_blockers.append("管理员账号不支持自助注销")
    if open_support_count:
        security_blockers.append(f"{open_support_count} 个客服工单未完结")
    security_passed = not security_blockers
    security_description = (
        "没有处理中申诉或安全限制" if security_passed else "、".join(security_blockers)
    )

    items = [
        _item(
            key="orders",
            title="订单与售后",
            description=order_description,
            passed=orders_passed,
            action="去处理",
            action_route="/pages/order/list",
        ),
        _item(
            key="wallet",
            title="钱包与资金",
            description=wallet_description,
            passed=wallet_passed,
            action="去提现",
            action_route="/pages/wallet/wallet",
        ),
        _item(
            key="services",
            title="服务与发布",
            description=services_description,
            passed=services_passed,
            action="去处理",
            action_route="/pages/provider/services",
        ),
        _item(
            key="security",
            title="账号安全",
            description=security_description,
            passed=security_passed,
            action="去处理",
            action_route="/pages/account/security",
        ),
    ]
    return {
        "can_delete": all(item["passed"] for item in items),
        "items": items,
    }


def send_account_deletion_sms(
    *,
    user: User,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """向当前账号绑定手机号发送注销确认验证码。"""
    if user.status != User.Status.ACTIVE:
        raise ApiError(
            ErrorCode.ACCOUNT_DELETION_BLOCKED,
            ERROR_MESSAGES[ErrorCode.ACCOUNT_DELETION_BLOCKED],
            status_code=409,
            details=account_deletion_check(user=user),
        )
    if not user.phone_hash or not user.phone_encrypted:
        raise ApiError(
            ErrorCode.ACCOUNT_DELETION_PHONE_REQUIRED,
            ERROR_MESSAGES[ErrorCode.ACCOUNT_DELETION_PHONE_REQUIRED],
            status_code=409,
        )
    result = send_sms_code(
        phone_value=decrypt_text(user.phone_encrypted),
        idempotency_key=idempotency_key,
        purpose=VerificationCode.Purpose.ACCOUNT_DELETION,
    )
    return {
        "phone_masked": user.phone_masked,
        "request_id": result.request_id,
        "expires_in": result.expires_in,
        "debug_code": result.debug_code,
    }


def _consume_deletion_code(
    *,
    user: User,
    code: str,
    verification_request_id: str | None,
) -> VerificationCode:
    """校验并一次性消费账号注销验证码。"""
    normalized_code = str(code or "").strip()
    if not CODE_PATTERN.fullmatch(normalized_code):
        raise _invalid("code", "验证码必须为 6 位数字")
    queryset = VerificationCode.objects.select_for_update().filter(
        phone_hash=user.phone_hash,
        purpose=VerificationCode.Purpose.ACCOUNT_DELETION,
    )
    if verification_request_id:
        queryset = queryset.filter(request_id=verification_request_id)
    verification = queryset.order_by("-created_at", "-id").first()
    if verification is None:
        raise _invalid("code", "注销验证码不存在或已失效")
    if verification.consumed_at is not None:
        raise _invalid("code", "注销验证码已使用")
    if verification.expires_at <= timezone.now():
        raise _invalid("code", "注销验证码已过期")
    if verification.attempts >= verification.max_attempts:
        raise ApiError(
            ErrorCode.AUTH_CODE_ATTEMPTS_EXCEEDED,
            ERROR_MESSAGES[ErrorCode.AUTH_CODE_ATTEMPTS_EXCEEDED],
            status_code=423,
        )
    if not check_password(normalized_code, verification.code_hash):
        VerificationCode.objects.filter(pk=verification.pk).update(
            attempts=verification.attempts + 1
        )
        raise _invalid("code", "注销验证码不正确")
    verification.consumed_at = timezone.now()
    verification.save(update_fields=["consumed_at"])
    return verification


def _cleanup_personal_data(user: User) -> dict[str, int]:
    """清理个人内容和登录绑定，并匿名化依法保留的安全资料。"""
    now = timezone.now()
    cleanup_counts = {}

    auth_deleted, _ = UserAuth.objects.filter(user=user).delete()
    cleanup_counts["auth_bindings_deleted"] = auth_deleted
    cleanup_counts["tokens_revoked"] = AuthToken.objects.filter(
        user=user,
        revoked_at__isnull=True,
    ).update(revoked_at=now)

    profile_deleted, _ = UserProfile.objects.filter(user=user).delete()
    cleanup_counts["profiles_deleted"] = profile_deleted

    personal_media_ids = list(
        MediaAsset.objects.filter(
            owner=user,
            status=MediaAsset.Status.AVAILABLE,
            purpose__in=[
                MediaAsset.Purpose.USER_PROFILE_AVATAR,
                MediaAsset.Purpose.PROVIDER_APPLICATION_AVATAR,
                MediaAsset.Purpose.PROVIDER_APPLICATION_LIFE_PHOTO,
                MediaAsset.Purpose.PROVIDER_PROFILE_AVATAR,
                MediaAsset.Purpose.PROVIDER_PROFILE_PHOTO,
                MediaAsset.Purpose.MOMENT_IMAGE,
                MediaAsset.Purpose.MOMENT_VIDEO,
            ],
        ).values_list("storage_key", flat=True)
    )
    cleanup_counts["media_assets_deleted"] = MediaAsset.objects.filter(
        storage_key__in=personal_media_ids
    ).update(
        status=MediaAsset.Status.DELETED,
        deleted_at=now,
    )
    for storage_key in personal_media_ids:
        delete_media_file(storage_key)

    cleanup_counts["moment_media_deleted"] = MomentMedia.objects.filter(
        moment__provider_user=user
    ).delete()[0]
    MomentTagLink.objects.filter(moment__provider_user=user).delete()
    cleanup_counts["moments_cleared"] = Moment.objects.filter(provider_user=user).update(
        content="",
        cover_media_id="",
        allow_recommend=False,
        status=Moment.Status.DELETED,
        attached_service=None,
        deleted_at=now,
    )
    cleanup_counts["comments_cleared"] = Comment.objects.filter(user=user).update(
        content="",
        status=Comment.Status.DELETED,
        deleted_at=now,
    )
    cleanup_counts["moment_likes_deleted"] = MomentLike.objects.filter(user=user).delete()[0]
    cleanup_counts["favorites_deleted"] = Favorite.objects.filter(user=user).delete()[0]
    cleanup_counts["follows_deleted"] = UserFollow.objects.filter(
        Q(follower=user) | Q(followed=user)
    ).delete()[0]

    cleanup_counts["provider_profiles_deleted"] = ProviderProfile.objects.filter(
        user=user
    ).delete()[0]
    cleanup_counts["services_archived"] = ProviderService.objects.filter(
        provider_user=user,
        deleted_at__isnull=True,
        status__in=[
            ProviderService.Status.DRAFT,
            ProviderService.Status.REJECTED,
            ProviderService.Status.OFFLINE,
        ],
    ).update(
        status=ProviderService.Status.OFFLINE,
        deleted_at=now,
    )

    cleanup_counts["provider_applications_anonymized"] = ProviderApplication.objects.filter(
        user=user
    ).update(
        introduction="",
        real_name_encrypted="",
        id_card_encrypted="",
        id_card_hash="",
        id_card_front_media_id="",
        id_card_back_media_id="",
        emergency_contact_name_encrypted="",
        emergency_contact_phone_encrypted="",
        emergency_contact_phone_masked="",
        avatar_media_id="",
        life_photo_media_ids=[],
        reject_reason="",
        idempotency_key=None,
        request_fingerprint="",
    )
    cleanup_counts["identity_verifications_anonymized"] = IdentityVerification.objects.filter(
        user=user
    ).update(
        real_name_encrypted="",
        id_card_number_encrypted="",
        id_card_hash="",
        id_card_front_media_id="",
        id_card_back_media_id="",
        reject_reason="",
        provider_request_no="",
    )

    LoginRequest.objects.filter(user=user).update(
        phone_hash="",
        phone_masked="",
    )
    if user.phone_hash:
        VerificationCode.objects.filter(phone_hash=user.phone_hash).update(
            phone_hash="",
            phone_masked="",
        )

    user.phone_hash = None
    user.phone_masked = ""
    user.phone_encrypted = None
    user.status = User.Status.LOGOFF
    user.initial_role_selected = False
    user.initial_role = None
    user.primary_role = None
    user.default_workspace = None
    user.initial_role_selected_at = None
    user.provider_status = User.ProviderStatus.NOT_SUBMITTED
    user.provider_enabled = False
    user.last_login_at = None
    user.last_login = None
    user.set_unusable_password()
    user.version += 1
    user.save()
    return cleanup_counts


def clear_account_balances(
    *,
    operator: User,
    user_public_id: str,
    reason: str,
    idempotency_key: str = "",
) -> dict[str, Any]:
    """人工清空用户钱包和收益余额，并写入不可变调整流水。"""
    normalized_reason = str(reason or "").strip()
    if len(normalized_reason) < 2:
        raise _invalid("reason", "资金清空原因至少需要 2 个字符")
    fingerprint = sensitive_fingerprint(
        {
            "user_public_id": user_public_id,
            "operator_user_id": operator.id,
            "reason": normalized_reason,
            "idempotency_key": idempotency_key,
        }
    )
    with transaction.atomic():
        user = User.objects.select_for_update().filter(public_id=user_public_id).first()
        if user is None:
            raise ApiError(
                ErrorCode.NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.NOT_FOUND],
                status_code=404,
            )
        if operator.id == user.id:
            raise _invalid("user_public_id", "不能清空当前登录管理员自己的资金")

        withdrawals = list(
            user.withdrawals.select_for_update().filter(
                status__in=[
                    Withdrawal.Status.PENDING_REVIEW,
                    Withdrawal.Status.PROCESSING,
                ]
            )
        )
        for withdrawal in withdrawals:
            previous_status = withdrawal.status
            withdrawal.status = Withdrawal.Status.CANCELED
            withdrawal.review_note = normalized_reason
            withdrawal.version = F("version") + 1
            withdrawal.save(
                update_fields=[
                    "status",
                    "review_note",
                    "version",
                    "updated_at",
                ]
            )
            withdrawal.refresh_from_db()
            WithdrawalStatusLog.objects.create(
                withdrawal=withdrawal,
                action=WithdrawalStatusLog.Action.CANCEL,
                from_status=previous_status,
                to_status=withdrawal.status,
                actor_user_id=operator.id,
                reason=normalized_reason,
                idempotency_key=f"account-clear:{fingerprint}",
                request_fingerprint=fingerprint,
            )

        pending_rewards = list(
            ReferralReward.objects.select_for_update().filter(
                inviter_user=user,
                status__in=[
                    ReferralReward.Status.PENDING_SETTLEMENT,
                    ReferralReward.Status.FROZEN,
                ],
            )
        )
        pending_reward_amount_minor = sum(reward.amount_minor for reward in pending_rewards)
        for reward in pending_rewards:
            previous_status = reward.status
            reward.status = ReferralReward.Status.CANCELED
            reward.cancel_reason = normalized_reason[:255]
            reward.version = F("version") + 1
            reward.save(
                update_fields=[
                    "status",
                    "cancel_reason",
                    "version",
                    "updated_at",
                ]
            )
            reward.refresh_from_db()
            ReferralRewardStatusLog.objects.create(
                reward=reward,
                from_status=previous_status,
                to_status=reward.status,
                reason=normalized_reason[:255],
                operator_user_id=operator.id,
                trace_id=current_trace_id(),
            )

        pending_entries = EarningEntry.objects.filter(
            user=user,
            status=EarningEntry.Status.PENDING_SETTLEMENT,
        )
        pending_entry_amount_minor = (
            pending_entries.aggregate(total=Sum("net_amount_minor"))["total"] or 0
        )
        pending_entries.update(status=EarningEntry.Status.CANCELED)

        wallet_amount_minor = 0
        wallet_transactions = []
        for account in user.wallet_accounts.select_for_update():
            amount_minor = account.balance_amount_minor
            wallet_amount_minor += amount_minor
            if amount_minor > 0:
                transaction_record, created = WalletTransaction.objects.get_or_create(
                    account=account,
                    user=user,
                    business_type="ACCOUNT_BALANCE_CLEAR",
                    business_no=f"CLEAR:{fingerprint[:32]}",
                    idempotency_key=f"account-clear:{fingerprint}",
                    defaults={
                        "direction": WalletTransaction.Direction.DEBIT,
                        "transaction_type": WalletTransaction.TransactionType.ADJUSTMENT,
                        "currency": account.currency,
                        "amount_minor": amount_minor,
                        "balance_after_amount_minor": 0,
                        "request_fingerprint": fingerprint,
                        "trace_id": current_trace_id(),
                    },
                )
                if not created and transaction_record.request_fingerprint != fingerprint:
                    raise ApiError(
                        ErrorCode.ACCOUNT_DELETION_IDEMPOTENCY_CONFLICT,
                        ERROR_MESSAGES[ErrorCode.ACCOUNT_DELETION_IDEMPOTENCY_CONFLICT],
                        status_code=409,
                    )
                wallet_transactions.append(str(transaction_record.transaction_no))
            account.balance_amount_minor = 0
            account.frozen_amount_minor = 0
            account.version = F("version") + 1
            account.save(
                update_fields=[
                    "balance_amount_minor",
                    "frozen_amount_minor",
                    "version",
                    "updated_at",
                ]
            )

        earning_amount_minor = 0
        earning_transactions = []
        for account in user.earning_accounts.select_for_update():
            amount_minor = account.available_amount_minor + account.frozen_amount_minor
            earning_amount_minor += amount_minor
            if amount_minor > 0:
                transaction_record, created = EarningTransaction.objects.get_or_create(
                    account=account,
                    user=user,
                    business_type="ACCOUNT_BALANCE_CLEAR",
                    business_no=f"CLEAR:{fingerprint[:32]}",
                    idempotency_key=f"account-clear:{fingerprint}",
                    defaults={
                        "direction": EarningTransaction.Direction.DEBIT,
                        "transaction_type": EarningTransaction.TransactionType.ADJUSTMENT,
                        "currency": account.currency,
                        "amount_minor": amount_minor,
                        "available_after_amount_minor": 0,
                        "frozen_after_amount_minor": 0,
                        "total_income_after_amount_minor": account.total_income_amount_minor,
                        "total_withdrawn_after_amount_minor": account.total_withdrawn_amount_minor,
                        "request_fingerprint": fingerprint,
                        "trace_id": current_trace_id(),
                    },
                )
                if not created and transaction_record.request_fingerprint != fingerprint:
                    raise ApiError(
                        ErrorCode.ACCOUNT_DELETION_IDEMPOTENCY_CONFLICT,
                        ERROR_MESSAGES[ErrorCode.ACCOUNT_DELETION_IDEMPOTENCY_CONFLICT],
                        status_code=409,
                    )
                earning_transactions.append(str(transaction_record.transaction_no))
            account.available_amount_minor = 0
            account.frozen_amount_minor = 0
            account.version = F("version") + 1
            account.save(
                update_fields=[
                    "available_amount_minor",
                    "frozen_amount_minor",
                    "version",
                    "updated_at",
                ]
            )

        return {
            "user_public_id": str(user.public_id),
            "cleared_wallet_amount_minor": wallet_amount_minor,
            "cleared_earning_amount_minor": earning_amount_minor,
            "canceled_pending_reward_amount_minor": pending_reward_amount_minor,
            "canceled_pending_earning_amount_minor": pending_entry_amount_minor,
            "canceled_withdrawal_count": len(withdrawals),
            "wallet_transaction_nos": wallet_transactions,
            "earning_transaction_nos": earning_transactions,
            "cleared_amount_minor": wallet_amount_minor
            + earning_amount_minor
            + pending_reward_amount_minor
            + pending_entry_amount_minor,
        }


def _deletion_payload(record: AccountDeletionRecord) -> dict[str, Any]:
    """返回账号注销完成审计的安全摘要。"""
    return {
        "request_no": str(record.request_no),
        "phone_masked": record.phone_masked,
        "deleted_at": record.completed_at,
        "deletion_mode": record.deletion_mode,
        "operator_user_id": record.operator_user_id,
        "reason": record.reason,
        "cleared_amount_minor": record.cleared_amount_minor,
        "cleanup_counts": record.cleanup_counts,
        "retained_categories": record.retained_categories,
    }


def delete_account(
    *,
    user: User,
    code: str,
    confirm: bool,
    verification_request_id: str | None = None,
) -> dict[str, Any]:
    """确认验证码并幂等执行账号注销、个人内容清理和审计留痕。"""
    if not confirm:
        raise _invalid("confirm", "必须确认不可恢复的账号注销")
    existing = (
        AccountDeletionRecord.objects.filter(user=user).order_by("-created_at", "-id").first()
    )
    if existing is not None:
        return _deletion_payload(existing)

    conditions = account_deletion_check(user=user)
    if not conditions["can_delete"]:
        raise ApiError(
            ErrorCode.ACCOUNT_DELETION_BLOCKED,
            ERROR_MESSAGES[ErrorCode.ACCOUNT_DELETION_BLOCKED],
            status_code=409,
            details=conditions,
        )
    phone_masked = user.phone_masked
    request_fingerprint = sensitive_fingerprint(
        {
            "user_id": user.id,
            "verification_request_id": verification_request_id or "",
            "conditions": conditions,
        }
    )
    with transaction.atomic():
        User.objects.select_for_update().get(pk=user.pk)
        verification = _consume_deletion_code(
            user=user,
            code=code,
            verification_request_id=verification_request_id,
        )
        cleanup_counts = _cleanup_personal_data(user)
        record = AccountDeletionRecord.objects.create(
            user=user,
            phone_masked=phone_masked,
            deletion_mode="USER_NORMAL",
            conditions_snapshot=conditions,
            cleanup_counts=cleanup_counts,
            retained_categories=RETAINED_CATEGORIES,
            verification_request_id=verification.request_id,
            request_fingerprint=request_fingerprint,
            trace_id=current_trace_id(),
        )
        return _deletion_payload(record)


def force_delete_account(
    *,
    operator: User,
    user_public_id: str,
    expected_version: int,
    reason: str,
    idempotency_key: str = "",
) -> dict[str, Any]:
    """管理员跳过资金门槛强制注销用户，并保留完整清理审计。"""
    normalized_reason = str(reason or "").strip()
    if len(normalized_reason) < 2:
        raise _invalid("reason", "强制注销原因至少需要 2 个字符")
    existing = (
        AccountDeletionRecord.objects.filter(user__public_id=user_public_id)
        .order_by("-created_at", "-id")
        .first()
    )
    if existing is not None:
        return _deletion_payload(existing)
    phone_masked = ""
    request_fingerprint = sensitive_fingerprint(
        {
            "operator_user_id": operator.id,
            "user_public_id": user_public_id,
            "expected_version": expected_version,
            "reason": normalized_reason,
            "idempotency_key": idempotency_key,
        }
    )
    with transaction.atomic():
        user = User.objects.select_for_update().filter(public_id=user_public_id).first()
        if user is None:
            raise ApiError(
                ErrorCode.NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.NOT_FOUND],
                status_code=404,
            )
        if operator.id == user.id:
            raise _invalid("user_public_id", "管理员不能强制注销自己的账号")
        if user.version != expected_version:
            raise ApiError(
                ErrorCode.ADMIN_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.ADMIN_VERSION_CONFLICT],
                status_code=409,
            )
        existing = (
            AccountDeletionRecord.objects.filter(user=user).order_by("-created_at", "-id").first()
        )
        if existing is not None:
            return _deletion_payload(existing)
        phone_masked = user.phone_masked
        conditions_snapshot = account_deletion_check(user=user)
        cleared = clear_account_balances(
            operator=operator,
            user_public_id=user_public_id,
            reason=normalized_reason,
            idempotency_key=idempotency_key,
        )
        cleanup_counts = _cleanup_personal_data(user)
        record = AccountDeletionRecord.objects.create(
            user=user,
            phone_masked=phone_masked,
            deletion_mode="ADMIN_FORCE",
            operator_user_id=operator.id,
            reason=normalized_reason,
            conditions_snapshot=conditions_snapshot,
            cleanup_counts={
                **cleanup_counts,
                "fund_clear_transactions": {
                    "wallet": cleared["wallet_transaction_nos"],
                    "earning": cleared["earning_transaction_nos"],
                },
            },
            cleared_amount_minor=cleared["cleared_amount_minor"],
            retained_categories=RETAINED_CATEGORIES,
            request_fingerprint=request_fingerprint,
            trace_id=current_trace_id(),
        )
        return {
            **_deletion_payload(record),
            "fund_clear": cleared,
        }
