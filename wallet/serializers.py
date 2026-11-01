from decimal import Decimal

from rest_framework import serializers

from .models import RechargeTransaction


class RechargeCreateSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))


class CallbackSerializer(serializers.Serializer):
    reference = serializers.CharField()
    status = serializers.ChoiceField(choices=["success", "failed"])


class RechargeSerializer(serializers.ModelSerializer):
    class Meta:
        model = RechargeTransaction
        fields = ["reference", "amount", "status"]
