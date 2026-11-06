"""收款、收益和提现 API 路由。"""

from django.urls import path

from backend.payouts.api.views import (
    AdminWithdrawalApproveView,
    AdminWithdrawalListView,
    AdminWithdrawalRejectView,
    AdminWithdrawalRetryView,
    EarningAccountView,
    EarningEntryListView,
    EarningTransactionListView,
    PayoutMethodDeactivateView,
    PayoutMethodDefaultView,
    PayoutMethodListCreateView,
    WithdrawalCancelView,
    WithdrawalListCreateView,
)

urlpatterns = [
    path("payout-methods/", PayoutMethodListCreateView.as_view(), name="payout-methods"),
    path(
        "payout-methods/<uuid:payout_method_id>/set-default/",
        PayoutMethodDefaultView.as_view(),
        name="payout-method-default",
    ),
    path(
        "payout-methods/<uuid:payout_method_id>/deactivate/",
        PayoutMethodDeactivateView.as_view(),
        name="payout-method-deactivate",
    ),
    path("earnings/account/", EarningAccountView.as_view(), name="earning-account"),
    path("earnings/entries/", EarningEntryListView.as_view(), name="earning-entries"),
    path(
        "earnings/transactions/",
        EarningTransactionListView.as_view(),
        name="earning-transactions",
    ),
    path("withdrawals/", WithdrawalListCreateView.as_view(), name="withdrawals"),
    path(
        "withdrawals/<uuid:withdrawal_no>/cancel/",
        WithdrawalCancelView.as_view(),
        name="withdrawal-cancel",
    ),
    path("admin/withdrawals/", AdminWithdrawalListView.as_view(), name="admin-withdrawals"),
    path(
        "admin/withdrawals/<uuid:withdrawal_no>/approve/",
        AdminWithdrawalApproveView.as_view(),
        name="admin-withdrawal-approve",
    ),
    path(
        "admin/withdrawals/<uuid:withdrawal_no>/reject/",
        AdminWithdrawalRejectView.as_view(),
        name="admin-withdrawal-reject",
    ),
    path(
        "admin/withdrawals/<uuid:withdrawal_no>/retry/",
        AdminWithdrawalRetryView.as_view(),
        name="admin-withdrawal-retry",
    ),
]
