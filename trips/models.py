"""
Trip model — optional persistence of trip results.

Each Trip corresponds to a planner request and stores the computed
fuel stops and cost so the result can be retrieved without re-computation.
"""

from __future__ import annotations

import json

from django.db import models

from routing.models import Route


class Trip(models.Model):
    """A planned road trip with fuel stop optimisation results."""

    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name="trips")

    # Serialised list of FuelStopResult dicts
    fuel_stops_json = models.TextField(default="[]")

    total_fuel_cost = models.DecimalField(max_digits=10, decimal_places=2)
    total_gallons = models.FloatField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Trip"
        verbose_name_plural = "Trips"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return (
            f"Trip {self.pk}: {self.route.start_location} → "
            f"{self.route.destination_location} — ${self.total_fuel_cost}"
        )

    @property
    def fuel_stops(self) -> list[dict]:
        return json.loads(self.fuel_stops_json)

    @fuel_stops.setter
    def fuel_stops(self, stops: list[dict]) -> None:
        self.fuel_stops_json = json.dumps(stops)
