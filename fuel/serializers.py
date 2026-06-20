"""Serializers for fuel app."""

from rest_framework import serializers

from fuel.models import FuelStation


class FuelStationSerializer(serializers.ModelSerializer):
    """Public serializer for a fuel station fuel stop."""

    class Meta:
        model = FuelStation
        fields = [
            "id",
            "name",
            "city",
            "state",
            "address",
            "latitude",
            "longitude",
            "retail_price",
        ]
