from django.urls import path

from backend.wallets.api.views import (
    AdminWalletTopUpView,
    WalletTransactionsView,
    WalletView,
)

urlpatterns = [
    path("wallet/", WalletView.as_view(), name="wallet"),
    path("wallet/transactions/", WalletTransactionsView.as_view(), name="wallet-transactions"),
    path(
        "admin/wallet/topups/",
        AdminWalletTopUpView.as_view(),
        name="admin-wallet-topups",
    ),
]
