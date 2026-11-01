from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .serializers import CallbackSerializer, RechargeCreateSerializer, RechargeSerializer


class WalletView(APIView):
    def get(self, request):
        wallet = services.get_wallet(request.user)
        return Response({"balance": str(wallet.balance)})


class RechargeView(APIView):
    def post(self, request):
        serializer = RechargeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        txn = services.create_recharge(request.user, serializer.validated_data["amount"])
        return Response(RechargeSerializer(txn).data, status=201)


class RechargeCallbackView(APIView):
    """Mock gateway webhook. No auth: the gateway is not a logged-in user."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = CallbackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        txn = services.process_callback(
            serializer.validated_data["reference"], serializer.validated_data["status"]
        )
        balance = services.get_wallet(txn.user).balance
        return Response({**RechargeSerializer(txn).data, "balance": str(balance)})
