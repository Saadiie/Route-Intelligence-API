"""
Routing models.

Route objects are cached in the DB keyed on (start, destination) so
repeated identical requests hit zero external API calls.
"""

from __future__ import annotations

import json

from django.db import models


class Route(models.Model):
    """A computed route between two US locations."""

    start_location = models.CharField(max_length=255, db_index=True)
    destination_location = models.CharField(max_length=255, db_index=True)

    # Total distance in miles
    distance_miles = models.FloatField()
    # Total estimated duration in minutes
    duration_minutes = models.FloatField()

    # GeoJSON LineString geometry (list of [lon, lat] pairs stored as JSON)
    geometry_json = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("start_location", "destination_location")]
        verbose_name = "Route"
        verbose_name_plural = "Routes"

    def __str__(self) -> str:
        return f"{self.start_location} → {self.destination_location} ({self.distance_miles:.0f} mi)"

    @property
    def geometry(self) -> list[list[float]]:
        """Decoded geometry as list of [lon, lat] coordinate pairs."""
        return json.loads(self.geometry_json)

    @geometry.setter
    def geometry(self, coords: list[list[float]]) -> None:
        self.geometry_json = json.dumps(coords)
