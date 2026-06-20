"""
Serializers for the trips API.
"""

from __future__ import annotations

from rest_framework import serializers


class TripRequestSerializer(serializers.Serializer):
    """Validates incoming trip planning requests."""

    start = serializers.CharField(
        max_length=255,
        help_text="Starting location within the USA (e.g. 'Houston, TX')",
    )
    destination = serializers.CharField(
        max_length=255,
        help_text="Destination within the USA (e.g. 'Chicago, IL')",
    )

    def validate_start(self, value: str) -> str:
        return value.strip()

    def validate_destination(self, value: str) -> str:
        return value.strip()

    def validate(self, attrs: dict) -> dict:
        if attrs["start"].lower() == attrs["destination"].lower():
            raise serializers.ValidationError(
                "Start and destination must be different locations."
            )
        return attrs


class FuelStopSerializer(serializers.Serializer):
    """Serialises a single FuelStopResult."""

    stop_number = serializers.IntegerField()
    station_name = serializers.CharField()
    city = serializers.CharField()
    state = serializers.CharField()
    address = serializers.CharField()
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    price_per_gallon = serializers.FloatField()
    distance_from_start_miles = serializers.FloatField()
    distance_from_route_miles = serializers.FloatField()
    gallons_purchased = serializers.FloatField()
    cost_at_stop = serializers.FloatField()


class RouteSerializer(serializers.Serializer):
    """Serialises route geometry."""

    # Each item is [lon, lat]
    geometry = serializers.ListField(
        child=serializers.ListField(child=serializers.FloatField())
    )


class TripResponseSerializer(serializers.Serializer):
    """Full trip planning response."""

    distance_miles = serializers.FloatField()
    duration_hours = serializers.FloatField()
    total_gallons = serializers.FloatField()
    total_fuel_cost = serializers.FloatField()
    fuel_stops = FuelStopSerializer(many=True)
    route = RouteSerializer()
    summary = serializers.DictField()
