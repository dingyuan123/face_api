from __future__ import annotations

from rest_framework import serializers

from backend.catalog.api.serializers import (
    MoneySerializer,
    ServiceCategoryResponseSerializer,
    ServiceTagResponseSerializer,
)
from backend.media.api.serializers import MediaAssetSummarySerializer


class OrderCreateRequestSerializer(serializers.Serializer):
    """预约订单创建请求。"""

    service_id = serializers.UUIDField(help_text="预约服务 UUID")
    slot_id = serializers.UUIDField(help_text="预约起始小时单元 UUID；后端按服务时长锁定连续单元")
    note = serializers.CharField(required=False, allow_blank=True, help_text="用户预约备注")
    expected_service_version = serializers.IntegerField(
        min_value=1,
        help_text="下单前服务版本号",
    )
    expected_slot_version = serializers.IntegerField(
        min_value=1,
        help_text="预约起始小时单元查询版本号",
    )
    location_selection_token = serializers.CharField(
        help_text="地点搜索接口返回的短期地点选择凭证；订单只接受已过滤公共场所",
    )
    coupon_no = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="可选用户优惠券 UUID；金额和服务端优惠金额由后端重新计算",
    )


class OrderQuoteRequestSerializer(serializers.Serializer):
    """下单前金额试算请求。"""

    service_id = serializers.UUIDField(help_text="预约服务 UUID")
    slot_id = serializers.UUIDField(help_text="预约起始小时单元 UUID；后端按服务时长检查连续单元")
    location_selection_token = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="可选的地点选择凭证，用于报价确认地点摘要",
    )
    coupon_no = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="可选用户优惠券 UUID，用于试算服务端可享受的订单优惠",
    )


class OrderMeetingLocationSerializer(serializers.Serializer):
    """订单见面地点快照，不含用户当前位置。"""

    poi_id = serializers.CharField(help_text="地图 POI 标识")
    name = serializers.CharField(help_text="见面地点名称")
    address = serializers.CharField(help_text="见面地点完整地址")
    province = serializers.CharField(help_text="见面地点省份")
    city = serializers.CharField(help_text="见面地点城市")
    district = serializers.CharField(help_text="见面地点区县")
    latitude = serializers.FloatField(allow_null=True, help_text="见面地点纬度")
    longitude = serializers.FloatField(allow_null=True, help_text="见面地点经度")
    category_code = serializers.CharField(help_text="见面地点地图分类代码")
    source = serializers.CharField(help_text="地点来源")
    policy_version = serializers.CharField(help_text="地点过滤规则版本")
    selected_at = serializers.DateTimeField(help_text="用户确认地点时间")


class OrderQuoteLineSerializer(serializers.Serializer):
    """金额试算明细，为后续优惠和营销活动保留扩展结构。"""

    type = serializers.CharField(help_text="明细类型，例如 SERVICE、DISCOUNT、FEE")
    name = serializers.CharField(help_text="明细展示名称")
    quantity = serializers.IntegerField(help_text="计价数量")
    unit_amount_minor = serializers.IntegerField(help_text="单价，单位为币种最小单位")
    amount_minor = serializers.IntegerField(help_text="明细金额，单位为币种最小单位")


class OrderQuoteDiscountSerializer(serializers.Serializer):
    """优惠明细；当前阶段没有优惠活动时返回空列表。"""

    code = serializers.CharField(help_text="优惠或活动稳定代码")
    name = serializers.CharField(help_text="优惠展示名称")
    amount_minor = serializers.IntegerField(help_text="优惠金额，单位为币种最小单位")


class OrderCouponResponseSerializer(serializers.Serializer):
    """订单优惠券锁定或核销摘要。"""

    redemption_no = serializers.UUIDField(help_text="优惠券核销记录 UUID")
    coupon_no = serializers.UUIDField(help_text="用户优惠券 UUID")
    coupon_name = serializers.CharField(help_text="优惠券展示名称")
    order_no = serializers.CharField(help_text="关联订单业务 UUID")
    status = serializers.CharField(help_text="优惠券核销状态")
    status_text = serializers.CharField(help_text="优惠券核销状态中文含义")
    currency = serializers.CharField(help_text="金额币种")
    original_amount_minor = serializers.IntegerField(help_text="优惠前订单原价，单位为分")
    discount_amount_minor = serializers.IntegerField(help_text="优惠金额，单位为分")
    payable_amount_minor = serializers.IntegerField(help_text="优惠后应付金额，单位为分")
    reserved_at = serializers.DateTimeField(help_text="订单创建锁定优惠券时间")
    used_at = serializers.DateTimeField(allow_null=True, help_text="支付成功核销时间")
    released_at = serializers.DateTimeField(allow_null=True, help_text="订单取消释放时间")


class OrderQuoteResponseSerializer(serializers.Serializer):
    """下单前金额试算响应。"""

    pricing_unit = serializers.CharField(help_text="计价单位，当前固定为 HOUR")
    currency = serializers.CharField(help_text="币种")
    hourly_amount_minor = serializers.IntegerField(help_text="服务每小时价格，单位为币种最小单位")
    booking_unit_count = serializers.IntegerField(help_text="预约小时数量")
    original_amount_minor = serializers.IntegerField(help_text="优惠前服务原价，单位为币种最小单位")
    discount_amount_minor = serializers.IntegerField(
        help_text="优惠总额，由服务端按优惠券规则计算，单位为币种最小单位"
    )
    platform_fee_amount_minor = serializers.IntegerField(
        help_text="平台服务费，当前为 0，单位为币种最小单位"
    )
    platform_commission_amount_minor = serializers.IntegerField(
        help_text="平台从服务者收入中抽取的佣金，不增加用户应付金额，单位为分"
    )
    payable_amount_minor = serializers.IntegerField(help_text="最终应付金额，单位为币种最小单位")
    payable_display = serializers.CharField(help_text="只读应付金额展示字符串")
    service_version = serializers.IntegerField(help_text="下单时作为 expected_service_version")
    slot_version = serializers.IntegerField(help_text="下单时作为 expected_slot_version")
    breakdown = OrderQuoteLineSerializer(many=True, help_text="金额计算明细")
    discounts = OrderQuoteDiscountSerializer(many=True, help_text="优惠明细")
    meeting_location = OrderMeetingLocationSerializer(
        allow_null=True,
        help_text="本次试算关联的见面地点摘要；未提供凭证时为空",
    )
    quoted_at = serializers.DateTimeField(help_text="金额试算时间")


class OrderPriceSerializer(serializers.Serializer):
    """订单价格快照。"""

    currency = serializers.CharField(help_text="币种")
    original_amount_minor = serializers.IntegerField(
        help_text="按小时计算的优惠前服务原价，单位为分"
    )
    discount_amount_minor = serializers.IntegerField(help_text="折扣金额，单位为分")
    platform_fee_amount_minor = serializers.IntegerField(help_text="平台服务费，单位为分")
    platform_commission_amount_minor = serializers.IntegerField(
        help_text="平台从服务者收入中抽取的佣金，单位为分",
    )
    payable_amount_minor = serializers.IntegerField(help_text="订单应付金额，单位为分")
    paid_amount_minor = serializers.IntegerField(help_text="已支付金额，单位为分")
    refunded_amount_minor = serializers.IntegerField(help_text="已退款金额，单位为分")


class OrderServiceResponseSerializer(serializers.Serializer):
    """订单关联服务及历史展示信息。"""

    id = serializers.UUIDField(help_text="服务 UUID")
    version = serializers.IntegerField(help_text="下单时或当前服务版本号")
    title = serializers.CharField(help_text="服务名称")
    category_code = serializers.CharField(help_text="服务类目代码")
    category = ServiceCategoryResponseSerializer(help_text="服务类目代码和中文展示信息")
    pricing_unit = serializers.CharField(help_text="计价单位，当前固定为 HOUR")
    price = MoneySerializer(help_text="服务每小时价格")
    price_display = serializers.CharField(help_text="只读每小时价格展示字符串")
    duration_minutes = serializers.IntegerField(help_text="服务时长，单位为分钟")
    introduction = serializers.CharField(help_text="服务介绍")
    cover_media = MediaAssetSummarySerializer(
        allow_null=True,
        help_text="服务封面媒体摘要和临时展示地址",
    )
    gallery_media = MediaAssetSummarySerializer(
        many=True,
        help_text="服务图集媒体摘要和临时展示地址",
    )
    tag_codes = serializers.ListField(
        child=serializers.CharField(),
        help_text="服务标签代码",
    )
    tags = ServiceTagResponseSerializer(
        many=True,
        help_text="服务标签代码、名称和分类",
    )
    location_type = serializers.CharField(help_text="服务地点类型")
    status = serializers.CharField(help_text="服务当前状态或历史快照状态")
    status_text = serializers.CharField(help_text="服务状态或历史快照状态中文含义")


class OrderCustomerParticipantSerializer(serializers.Serializer):
    """订单普通用户公开展示信息。"""

    user_public_id = serializers.UUIDField(help_text="用户公开 UUID")
    nickname = serializers.CharField(allow_null=True, help_text="用户昵称")
    avatar_media = MediaAssetSummarySerializer(
        allow_null=True,
        help_text="用户头像媒体摘要和临时展示地址",
    )
    phone_display = serializers.CharField(help_text="脱敏手机号")


class OrderProviderParticipantSerializer(serializers.Serializer):
    """订单服务者公开展示和履约统计信息。"""

    user_public_id = serializers.UUIDField(help_text="服务者公开 UUID")
    nickname = serializers.CharField(allow_null=True, help_text="服务者昵称")
    avatar_media = MediaAssetSummarySerializer(
        allow_null=True,
        help_text="服务者头像媒体摘要和临时展示地址",
    )
    phone_display = serializers.CharField(help_text="脱敏手机号")
    rating_average = serializers.CharField(help_text="服务者平均评分，保留两位小数")
    review_count = serializers.IntegerField(help_text="有效评价数量")
    completed_order_count = serializers.IntegerField(help_text="已完成订单数量")
    verification = serializers.DictField(help_text="实名和人脸认证状态")


class OrderParticipantsSerializer(serializers.Serializer):
    """见面双方公开展示信息。"""

    customer = OrderCustomerParticipantSerializer(help_text="普通用户信息")
    provider = OrderProviderParticipantSerializer(help_text="服务者信息")


class OrderContactSerializer(serializers.Serializer):
    """当前登录者联系订单对方的信息。"""

    target_role = serializers.ChoiceField(
        choices=["USER", "PROVIDER", "ADMIN"],
        help_text="联系目标角色",
    )
    target_name = serializers.CharField(allow_null=True, help_text="联系目标昵称")
    phone_display = serializers.CharField(help_text="脱敏手机号")
    phone_dial = serializers.CharField(
        allow_null=True,
        help_text="可拨号手机号；未补充加密手机号时为空",
    )
    tel_uri = serializers.CharField(
        allow_null=True,
        help_text="前端可直接使用的 tel URI",
    )
    can_call = serializers.BooleanField(help_text="当前是否允许拨打电话")
    action_label = serializers.CharField(help_text="联系按钮展示文案")


class OrderProgressEventSerializer(serializers.Serializer):
    """订单进度时间线事件。"""

    event_type = serializers.CharField(help_text="订单事件类型")
    status = serializers.CharField(help_text="事件后的订单状态")
    status_text = serializers.CharField(help_text="订单状态中文文案")
    actor_role = serializers.ChoiceField(
        choices=["USER", "PROVIDER", "SYSTEM"],
        help_text="执行事件的角色",
    )
    occurred_at = serializers.DateTimeField(help_text="事件发生时间")
    reason = serializers.CharField(help_text="取消、拒绝或退款原因")


class OrderNextActionSerializer(serializers.Serializer):
    """当前登录者可执行的订单操作。"""

    role = serializers.ChoiceField(
        choices=["USER", "PROVIDER", "NONE"],
        help_text="可执行操作的角色",
    )
    action = serializers.CharField(help_text="操作代码")
    label = serializers.CharField(help_text="前端按钮展示文案")


class OrderProgressSerializer(serializers.Serializer):
    """订单进度和操作信息。"""

    current_status = serializers.CharField(help_text="当前订单状态")
    current_status_text = serializers.CharField(help_text="当前订单状态中文文案")
    next_action = OrderNextActionSerializer(help_text="当前登录者下一步操作")
    can_request_refund = serializers.BooleanField(help_text="当前用户是否可以申请退款")
    review_status = serializers.ChoiceField(
        choices=["NOT_AVAILABLE", "NOT_REVIEWED", "REVIEWED", "EXPIRED"],
        help_text="评价状态",
    )
    review_status_text = serializers.CharField(help_text="评价状态中文文案")
    can_review = serializers.BooleanField(help_text="当前用户是否可以提交评价")
    timeline = OrderProgressEventSerializer(many=True, help_text="订单状态时间线")


class OrderResponseSerializer(serializers.Serializer):
    """预约订单响应。"""

    order_no = serializers.UUIDField(help_text="订单业务 UUID")
    status = serializers.CharField(help_text="订单状态")
    status_text = serializers.CharField(help_text="订单状态中文文案")
    user_public_id = serializers.UUIDField(help_text="下单用户 UUID")
    provider_public_id = serializers.UUIDField(help_text="服务者用户 UUID")
    service = OrderServiceResponseSerializer(help_text="订单服务和封面信息")
    schedule_slot = serializers.DictField(help_text="预约时段快照")
    meeting_location = OrderMeetingLocationSerializer(
        allow_null=True,
        help_text="订单见面地点快照，仅订单参与人可访问",
    )
    participants = OrderParticipantsSerializer(help_text="见面双方信息")
    contact = OrderContactSerializer(help_text="当前登录者联系对方的信息")
    progress = OrderProgressSerializer(help_text="订单进度和下一步操作")
    price = OrderPriceSerializer(help_text="订单价格快照")
    coupon = OrderCouponResponseSerializer(
        allow_null=True,
        help_text="订单优惠券锁定、核销或释放摘要；未使用优惠券时为空",
    )
    note = serializers.CharField(help_text="预约备注")
    reject_reason = serializers.CharField(help_text="拒绝原因")
    version = serializers.IntegerField(help_text="订单版本号")
    created_at = serializers.DateTimeField(help_text="订单创建时间")
    updated_at = serializers.DateTimeField(help_text="订单最近更新时间")
    paid_at = serializers.DateTimeField(allow_null=True, help_text="支付时间")
    completed_at = serializers.DateTimeField(allow_null=True, help_text="订单完成时间")
    review_expires_at = serializers.DateTimeField(allow_null=True, help_text="评价截止时间")


class OrderSummaryResponseSerializer(serializers.Serializer):
    """订单管理状态数量汇总。"""

    total = serializers.IntegerField(help_text="订单总数")
    status_counts = serializers.DictField(help_text="按订单状态统计的数量")


class PaymentResponseSerializer(serializers.Serializer):
    """订单支付单和原生支付 SDK 参数。"""

    payment_no = serializers.UUIDField(help_text="支付单 UUID")
    order_no = serializers.CharField(help_text="兼容关联业务单号")
    business_type = serializers.CharField(help_text="支付关联业务类型")
    business_no = serializers.CharField(help_text="支付关联业务单号")
    payment_method = serializers.ChoiceField(
        choices=["BALANCE", "WECHAT_APP", "ALIPAY_APP"],
        help_text="支付方式",
    )
    payment_method_text = serializers.CharField(help_text="支付方式中文含义")
    payment_channel = serializers.CharField(help_text="支付渠道代码")
    currency = serializers.CharField(help_text="支付币种")
    amount_minor = serializers.IntegerField(help_text="支付金额，单位为分")
    status = serializers.ChoiceField(
        choices=["PENDING", "SUCCESS", "FAILED", "CLOSED", "REFUNDED"],
        help_text="支付单状态",
    )
    status_text = serializers.CharField(help_text="支付单状态中文含义")
    client_payload = serializers.DictField(
        help_text="微信或支付宝原生 SDK 调起参数；余额支付为空对象"
    )
    expires_at = serializers.DateTimeField(
        allow_null=True,
        help_text="支付参数失效时间",
    )
    paid_at = serializers.DateTimeField(allow_null=True, help_text="支付成功时间")
    version = serializers.IntegerField(help_text="支付单版本号")


class OrderPayResponseSerializer(serializers.Serializer):
    """订单支付发起结果。"""

    order = OrderResponseSerializer(help_text="支付发起后的订单")
    payment = PaymentResponseSerializer(help_text="支付单及原生支付参数")
    payment_action = serializers.ChoiceField(
        choices=["NONE", "NATIVE_PAY"],
        help_text="NONE 表示直接成功，NATIVE_PAY 表示需要调起客户端支付 SDK",
    )
    reused = serializers.BooleanField(help_text="是否复用了相同幂等请求")


class OrderVersionRequestSerializer(serializers.Serializer):
    """订单操作版本请求。"""

    expected_version = serializers.IntegerField(min_value=1, help_text="当前订单版本号")


class OrderPayRequestSerializer(OrderVersionRequestSerializer):
    """余额、微信 App 或支付宝 App 支付订单请求。"""

    payment_method = serializers.ChoiceField(
        choices=["BALANCE", "WECHAT_APP", "ALIPAY_APP"],
        default="BALANCE",
        help_text="支付方式；外部支付必须通过回调确认成功",
    )


class OrderActionRequestSerializer(OrderVersionRequestSerializer):
    """订单状态操作请求。"""

    reason = serializers.CharField(required=False, allow_blank=True, help_text="拒绝或取消原因")


class OrderRefundRequestCreateSerializer(serializers.Serializer):
    """用户订单退款申请请求。"""

    reason = serializers.CharField(help_text="退款原因，2 到 500 个字符")
    expected_order_version = serializers.IntegerField(
        min_value=1,
        help_text="申请前订单版本号",
    )


class OrderRefundRequestSerializer(serializers.Serializer):
    """退款申请和审核结果响应。"""

    request_no = serializers.UUIDField(help_text="退款申请业务 UUID")
    order_no = serializers.UUIDField(help_text="关联订单业务 UUID")
    status = serializers.ChoiceField(
        choices=["PENDING", "REJECTED", "PROCESSING", "REFUNDED", "FAILED", "CANCELED"],
        help_text="退款申请状态",
    )
    status_text = serializers.CharField(help_text="退款申请状态中文文案")
    reason = serializers.CharField(help_text="用户退款申请原因")
    currency = serializers.CharField(help_text="退款币种")
    refund_amount_minor = serializers.IntegerField(help_text="全额退款金额，单位为币种最小单位")
    approved_refund_amount_minor = serializers.IntegerField(
        allow_null=True,
        help_text="管理员同意的实际退款金额，单位为分",
    )
    review_note = serializers.CharField(help_text="后台审核说明")
    reviewed_at = serializers.DateTimeField(
        allow_null=True,
        help_text="后台审核完成时间",
    )
    failure_reason = serializers.CharField(help_text="退款执行失败原因")
    version = serializers.IntegerField(help_text="退款申请版本号")
    created_at = serializers.DateTimeField(help_text="退款申请创建时间")
    updated_at = serializers.DateTimeField(help_text="退款申请最近更新时间")


class OrderRefundRequestListResponseSerializer(serializers.Serializer):
    """后台退款申请列表响应。"""

    items = OrderRefundRequestSerializer(many=True, help_text="退款申请列表")
    total = serializers.IntegerField(help_text="筛选后的退款申请总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")


class OrderRefundReviewRequestSerializer(serializers.Serializer):
    """后台退款申请审核请求。"""

    expected_version = serializers.IntegerField(
        min_value=1,
        help_text="退款申请当前版本号",
    )
    review_note = serializers.CharField(help_text="审核说明，2 到 500 个字符")
    refund_amount_minor = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="本次同意退款金额，可小于申请金额实现部分退款",
    )


class OrderRefundRetryRequestSerializer(serializers.Serializer):
    """退款失败申请重新处理请求。"""

    expected_version = serializers.IntegerField(
        min_value=1,
        help_text="退款申请当前版本号",
    )
