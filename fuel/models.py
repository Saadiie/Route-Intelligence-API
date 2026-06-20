"""
Fuel app models.

FuelStation stores data imported from the OPIS truckstop CSV.
City-level geocoding is resolved at import time; no lat/lon in source data.
"""

from django.db import models


class FuelStation(models.Model):
    """A truckstop/fuel station with price and geographic data."""

    opis_id = models.IntegerField(db_index=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, db_index=True)
    state = models.CharField(max_length=10, db_index=True)
    rack_id = models.IntegerField(null=True, blank=True)
    retail_price = models.DecimalField(max_digits=8, decimal_places=5)

    # Geocoded coordinates (resolved during import)
    latitude = models.FloatField(null=True, blank=True, db_index=True)
    longitude = models.FloatField(null=True, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Fuel Station"
        verbose_name_plural = "Fuel Stations"
        indexes = [
            models.Index(fields=["state", "city"]),
            models.Index(fields=["latitude", "longitude"]),
            models.Index(fields=["retail_price"]),
        ]
        # Allow multiple price rows per station (different fuel grades)
        unique_together: list = []

    def __str__(self) -> str:
        return f"{self.name} — {self.city}, {self.state} @ ${self.retail_price}"

    @property
    def coordinates(self) -> tuple[float, float] | None:
        """Return (lat, lon) tuple or None if not geocoded."""
        if self.latitude is not None and self.longitude is not None:
            return (self.latitude, self.longitude)
        return None
