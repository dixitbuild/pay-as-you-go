from rest_framework import serializers

from .models import Session


class SessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Session
        fields = [
            "id", "user", "provider", "status", "rate_per_minute", "started_at", "ended_at",
            "billed_minutes", "total_billed", "billable_seconds", "ended_by",
        ]
        read_only_fields = fields


class AssignSerializer(serializers.Serializer):
    provider_id = serializers.IntegerField()
