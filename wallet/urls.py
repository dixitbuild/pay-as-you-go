from django.urls import path

from . import views

urlpatterns = [
    path("", views.WalletView.as_view()),
    path("recharge/", views.RechargeView.as_view()),
    path("recharge/callback/", views.RechargeCallbackView.as_view()),
]
