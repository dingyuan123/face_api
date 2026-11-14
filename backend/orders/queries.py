"""订单模块对其他模块提供的只读业务查询。"""

from __future__ import annotations

from django.db.models import Q, QuerySet

from backend.orders.models import Order


def get_chat_orders_for_users(user_ids: list[int]) -> QuerySet[Order]:
    """返回指定用户作为预约方或服务者的订单，供聊天模块只读聚合。"""

    return Order.objects.filter(
        Q(user_id__in=user_ids) | Q(provider_user_id__in=user_ids)
    ).select_related(
        "user",
        "provider_user",
        "service",
    )


def get_order_for_chat(*, order_no: str, user_id: int) -> Order | None:
    """按订单号返回当前用户作为预约方或服务者且允许创建会话的订单。"""

    try:
        return (
            Order.objects.select_related("user", "provider_user", "service")
            .filter(order_no=order_no)
            .filter(Q(user_id=user_id) | Q(provider_user_id=user_id))
            .first()
        )
    except (Order.DoesNotExist, ValueError):
        return None


def get_chat_orders_for_pair(*, customer_user_id: int, provider_user_id: int) -> QuerySet[Order]:
    """返回指定用户与服务者之间已形成聊天资格的订单，按最新订单优先。"""

    return (
        Order.objects.filter(
            user_id=customer_user_id,
            provider_user_id=provider_user_id,
        )
        .exclude(status=Order.Status.PENDING_PAYMENT)
        .select_related("user", "provider_user", "service")
        .order_by("-created_at", "-id")
    )


def get_latest_chat_order_between_users(*, first_user_id: int, second_user_id: int) -> Order | None:
    """返回任意两个订单参与方之间最新的聊天资格订单，用于打开共享会话。"""

    return (
        Order.objects.filter(
            Q(user_id=first_user_id, provider_user_id=second_user_id)
            | Q(user_id=second_user_id, provider_user_id=first_user_id)
        )
        .exclude(status=Order.Status.PENDING_PAYMENT)
        .select_related("user", "provider_user", "service")
        .order_by("-created_at", "-id")
        .first()
    )


def get_order_for_chat_activation(*, order_no: str) -> Order | None:
    """返回支付成功后需要激活聊天会话的订单，仅供聊天模块内部调用。"""

    try:
        return (
            Order.objects.select_related("user", "provider_user", "service")
            .filter(order_no=order_no)
            .first()
        )
    except (Order.DoesNotExist, ValueError):
        return None


def get_paid_orders_for_chat_activation() -> QuerySet[Order]:
    """返回已支付订单，供聊天模块幂等补齐双方会话和支付提示。"""

    return (
        Order.objects.select_related("user", "provider_user", "service")
        .filter(paid_at__isnull=False)
        .order_by("paid_at", "id")
    )
