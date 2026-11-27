"""优惠券订单联动和会员购买、续费、权益及退款限制测试。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from backend.common.errors import ErrorCode
from backend.common.exceptions import ApiError
from backend.coupons.models import (
    CouponInstance,
    CouponRedemption,
    CouponStatusLog,
    CouponTemplate,
)
from backend.coupons.services import (
    CouponScopeContext,
    claim_coupon,
    issue_coupon,
    preview_coupon_discount,
)
from backend.memberships.models import (
    MembershipBenefitGrant,
    MembershipPeriod,
    MembershipPurchase,
)
from backend.memberships.services import (
    create_membership_plan,
    create_membership_purchase,
    get_membership_summary,
    update_membership_plan,
)
from backend.orders.services import cancel_order, create_order, pay_order, quote_order
from backend.payments.models import Payment
from backend.payments.services import refund_wallet_for_payment
from tests.test_booking_flow import (
    create_customer,
    create_provider_fixture,
    create_user,
)

pytestmark = pytest.mark.django_db


def _fixed_coupon_template(
    *,
    code: str = "TEST_COUPON",
    amount_minor: int = 3000,
    min_spend_amount_minor: int = 5000,
    per_user_issue_limit: int = 2,
) -> CouponTemplate:
    """创建测试固定金额优惠券模板。"""
    now = timezone.now()
    return CouponTemplate.objects.create(
        code=code,
        name="测试优惠券",
        discount_type=CouponTemplate.DiscountType.FIXED_AMOUNT,
        currency="CNY",
        discount_amount_minor=amount_minor,
        min_spend_amount_minor=min_spend_amount_minor,
        scope_type=CouponTemplate.ScopeType.SERVICE_CATEGORY,
        scope_value="SPORT",
        validity_type=CouponTemplate.ValidityType.FIXED_PERIOD,
        valid_from=now - timedelta(days=1),
        valid_to=now + timedelta(days=30),
        per_user_issue_limit=per_user_issue_limit,
        status=CouponTemplate.Status.ACTIVE,
    )


def test_coupon_discount_order_payment_refund_and_release_lifecycle() -> None:
    admin = create_user("coupon-admin", is_staff=True)
    customer = create_customer("coupon-customer", admin)
    _provider, service, slot = create_provider_fixture("coupon-provider")
    template = _fixed_coupon_template()
    coupon, created = issue_coupon(
        user=customer,
        template_no=str(template.template_no),
        source_type=CouponInstance.SourceType.USER_CLAIM,
        source_no="coupon-claim-1",
    )

    quote = quote_order(
        user=customer,
        service_id=str(service.public_id),
        slot_id=str(slot.public_id),
        coupon_no=str(coupon.coupon_no),
    )
    result = create_order(
        user=customer,
        service_id=str(service.public_id),
        slot_id=str(slot.public_id),
        note="优惠券订单",
        expected_service_version=service.version,
        expected_slot_version=slot.version,
        coupon_no=str(coupon.coupon_no),
        idempotency_key="coupon-order-1",
    )
    repeated = create_order(
        user=customer,
        service_id=str(service.public_id),
        slot_id=str(slot.public_id),
        note="优惠券订单",
        expected_service_version=service.version,
        expected_slot_version=slot.version,
        coupon_no=str(coupon.coupon_no),
        idempotency_key="coupon-order-1",
    )

    assert created is True
    assert quote["discount_amount_minor"] == 3000
    assert quote["payable_amount_minor"] == 3800
    assert result.order.discount_amount_minor == 3000
    assert result.order.payable_amount_minor == 3800
    assert repeated.reused is True
    assert repeated.order.id == result.order.id
    redemption = CouponRedemption.objects.get(order_no=str(result.order.order_no))
    coupon.refresh_from_db()
    assert redemption.status == CouponRedemption.Status.RESERVED
    assert coupon.status == CouponInstance.Status.RESERVED

    pay_order(
        user=customer,
        order_no=str(result.order.order_no),
        payment_method=Payment.Method.BALANCE,
        expected_version=result.order.version,
        idempotency_key="coupon-order-pay-1",
    )
    coupon.refresh_from_db()
    redemption.refresh_from_db()
    assert coupon.status == CouponInstance.Status.USED
    assert redemption.status == CouponRedemption.Status.USED

    cancel_order(
        user=customer,
        order_no=str(result.order.order_no),
        expected_version=result.order.version + 1,
        reason="测试退款",
    )
    coupon.refresh_from_db()
    redemption.refresh_from_db()
    assert coupon.status == CouponInstance.Status.USED
    assert redemption.status == CouponRedemption.Status.USED
    assert CouponStatusLog.objects.filter(
        coupon=coupon,
        event_type=CouponStatusLog.EventType.ORDER_REFUNDED,
    ).exists()

    second_coupon, _ = issue_coupon(
        user=customer,
        template_no=str(template.template_no),
        source_type=CouponInstance.SourceType.USER_CLAIM,
        source_no="coupon-claim-2",
    )
    slot.refresh_from_db()
    second_result = create_order(
        user=customer,
        service_id=str(service.public_id),
        slot_id=str(slot.public_id),
        note="释放优惠券",
        expected_service_version=service.version,
        expected_slot_version=slot.version,
        coupon_no=str(second_coupon.coupon_no),
        idempotency_key="coupon-order-2",
    )
    cancel_order(
        user=customer,
        order_no=str(second_result.order.order_no),
        expected_version=second_result.order.version,
        reason="未支付取消",
    )
    second_coupon.refresh_from_db()
    second_redemption = CouponRedemption.objects.get(order_no=str(second_result.order.order_no))
    assert second_coupon.status == CouponInstance.Status.AVAILABLE
    assert second_redemption.status == CouponRedemption.Status.RELEASED


def test_coupon_scope_threshold_and_claim_idempotency() -> None:
    user = create_user("coupon-rule-user")
    template = _fixed_coupon_template(
        code="RULE_COUPON",
        amount_minor=500,
        min_spend_amount_minor=10000,
        per_user_issue_limit=1,
    )
    coupon, created = claim_coupon(
        user=user,
        template_no=str(template.template_no),
        idempotency_key="claim-1",
    )
    repeated, repeated_created = claim_coupon(
        user=user,
        template_no=str(template.template_no),
        idempotency_key="claim-1",
    )

    assert created is True
    assert repeated_created is False
    assert coupon.id == repeated.id

    with pytest.raises(ApiError) as threshold_error:
        preview_coupon_discount(
            user=user,
            coupon_no=str(coupon.coupon_no),
            original_amount_minor=5000,
            currency="CNY",
            context=CouponScopeContext(category_code="SPORT"),
        )
    assert threshold_error.value.machine_code == ErrorCode.COUPON_INVALID

    with pytest.raises(ApiError) as scope_error:
        preview_coupon_discount(
            user=user,
            coupon_no=str(coupon.coupon_no),
            original_amount_minor=12000,
            currency="CNY",
            context=CouponScopeContext(category_code="COFFEE"),
        )
    assert scope_error.value.machine_code == ErrorCode.COUPON_INVALID


def test_membership_purchase_renewal_benefits_and_no_refund() -> None:
    admin = create_user("membership-admin", is_staff=True)
    customer = create_user("membership-customer")
    _fixed_coupon_template(
        code="MEMBER_COUPON",
        amount_minor=1000,
        min_spend_amount_minor=0,
        per_user_issue_limit=10,
    )
    plan = create_membership_plan(
        operator=admin,
        payload={
            "code": "GOLD",
            "name": "金卡会员",
            "description": "测试会员套餐",
            "duration_days": 30,
            "currency": "CNY",
            "price_amount_minor": 2800,
            "benefits": [
                {"code": "PRIORITY_RECOMMENDATION"},
                {"code": "MEMBER_COUPON", "coupon_template_code": "MEMBER_COUPON", "count": 1},
            ],
            "sort_order": 1,
        },
    )
    update_membership_plan(
        operator=admin,
        plan_no=plan["plan_no"],
        payload={"status": "ACTIVE"},
        expected_version=plan["version"],
    )
    from backend.wallets.services import admin_top_up_wallet

    admin_top_up_wallet(
        target_user=customer,
        created_by=admin,
        amount_minor=10000,
        reason="会员测试余额",
        idempotency_key="membership-topup-1",
    )

    first = create_membership_purchase(
        user=customer,
        plan_code="GOLD",
        payment_method=Payment.Method.BALANCE,
        idempotency_key="membership-1",
    )
    first_repeated = create_membership_purchase(
        user=customer,
        plan_code="GOLD",
        payment_method=Payment.Method.BALANCE,
        idempotency_key="membership-1",
    )
    second = create_membership_purchase(
        user=customer,
        plan_code="GOLD",
        payment_method=Payment.Method.BALANCE,
        idempotency_key="membership-2",
    )

    assert first.created is True
    assert first.purchase.status == MembershipPurchase.Status.PAID
    assert first_repeated.reused is True
    assert first_repeated.purchase.id == first.purchase.id
    assert MembershipPeriod.objects.filter(user=customer).count() == 2
    first_period = first.purchase.period
    second_period = second.purchase.period
    assert second_period.starts_at >= first_period.ends_at
    assert second_period.ends_at > first_period.ends_at
    assert first.payment.status == Payment.Status.SUCCESS
    assert first.payment.business_type == Payment.BusinessType.MEMBERSHIP_PURCHASE
    assert (
        MembershipBenefitGrant.objects.filter(
            user=customer,
            benefit_code="MEMBER_COUPON",
            status=MembershipBenefitGrant.Status.ACTIVE,
        ).count()
        == 2
    )
    assert (
        CouponInstance.objects.filter(
            user=customer,
            source_type=CouponInstance.SourceType.MEMBERSHIP,
        ).count()
        == 2
    )

    summary = get_membership_summary(user=customer)
    assert summary["is_member"] is True
    assert summary["period"]["ends_at"] == second_period.ends_at

    with pytest.raises(ApiError) as refund_error:
        refund_wallet_for_payment(
            payment=first.payment,
            refund_amount_minor=first.payment.amount_minor,
            idempotency_key="membership-refund-1",
        )
    assert refund_error.value.machine_code == ErrorCode.PAYMENT_REFUND_NOT_ALLOWED
