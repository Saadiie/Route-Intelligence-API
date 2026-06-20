"""
Repository layer for FuelStation queries.

Encapsulates all DB access so services stay DB-agnostic.
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db.models import QuerySet

from fuel.models import FuelStation

if TYPE_CHECKING:
    pass


class FuelStationRepository:
    """Data-access methods for :model:`fuel.FuelStation`."""

    
    # Writes
        

    @staticmethod
    def bulk_create(stations: list[FuelStation], batch_size: int = 500) -> int:
        """
        Insert stations in bulk, ignoring conflicts (idempotent import).
        Returns count of rows actually inserted.
        """
        created = FuelStation.objects.bulk_create(
            stations,
            batch_size=batch_size,
            ignore_conflicts=True,
        )
        return len(created)

    
    # Reads
    

    @staticmethod
    def all_geocoded() -> QuerySet[FuelStation]:
        """Return all stations that have been successfully geocoded."""
        return (
            FuelStation.objects.filter(
                latitude__isnull=False,
                longitude__isnull=False,
            )
            .only("id", "name", "city", "state", "latitude", "longitude", "retail_price", "address")
            .order_by("retail_price")
        )

    @staticmethod
    def find_within_radius(
        lat: float,
        lon: float,
        radius_miles: float,
        max_results: int = 20,
    ) -> list[FuelStation]:
        """
        Return stations within *radius_miles* of (lat, lon), sorted by price.

        Uses a bounding-box pre-filter (cheap SQL) followed by exact
        Haversine filtering in Python — avoids PostGIS dependency while
        keeping the SQL set small.

        Time complexity: O(n) scan over geocoded stations — acceptable
        because the bounding-box index shrinks n significantly for typical
        radius values.
        """
        # 1° latitude ≈ 69 miles; 1° longitude varies with cos(lat)
        lat_delta = radius_miles / 69.0
        lon_delta = radius_miles / (69.0 * math.cos(math.radians(lat)))

        candidates: QuerySet[FuelStation] = FuelStation.objects.filter(
            latitude__range=(lat - lat_delta, lat + lat_delta),
            longitude__range=(lon - lon_delta, lon + lon_delta),
            latitude__isnull=False,
            longitude__isnull=False,
        ).only(
            "id", "name", "city", "state",
            "latitude", "longitude", "retail_price", "address",
        )

        # Exact Haversine filter
        results: list[tuple[float, FuelStation]] = []
        for station in candidates:
            dist = _haversine(lat, lon, station.latitude, station.longitude)  # type: ignore[arg-type]
            if dist <= radius_miles:
                results.append((dist, station))

        results.sort(key=lambda x: (float(x[1].retail_price), x[0]))
        return [s for _, s in results[:max_results]]

    @staticmethod
    def count() -> int:
        return FuelStation.objects.count()

    @staticmethod
    def count_geocoded() -> int:
        return FuelStation.objects.filter(
            latitude__isnull=False, longitude__isnull=False
        ).count()



# Internal helpers


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in miles between two lat/lon points."""
    R = 3958.8  # Earth radius in miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))
