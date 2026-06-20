"""
Fuel Stop Optimisation Algorithm
==================================

Uses numpy vectorized operations for fast distance calculations across
all stations simultaneously — no Python loops over stations.

Algorithm: Greedy lookahead with cheapest-reachable-station selection.

Time complexity: O(W * N) where:
  W = number of fuel stops (typically 1-8)
  N = total stations (7531) — vectorized via numpy
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

import numpy as np
from django.conf import settings

from fuel.models import FuelStation
from fuel.repositories import FuelStationRepository
from routing.utils import (
    RoutePoint,
    annotate_route_with_distances,
)

logger = logging.getLogger(__name__)

EARTH_RADIUS_MILES = 3958.8


@dataclass
class FuelStopResult:
    station_id: int
    station_name: str
    city: str
    state: str
    address: str
    latitude: float
    longitude: float
    price_per_gallon: Decimal
    stop_number: int
    distance_from_start_miles: float
    distance_from_route_miles: float
    gallons_purchased: float
    cost_at_stop: Decimal

    def to_dict(self) -> dict:
        return {
            "stop_number": self.stop_number,
            "station_name": self.station_name,
            "city": self.city,
            "state": self.state,
            "address": self.address,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "price_per_gallon": float(self.price_per_gallon),
            "distance_from_start_miles": round(self.distance_from_start_miles, 1),
            "distance_from_route_miles": round(self.distance_from_route_miles, 2),
            "gallons_purchased": round(self.gallons_purchased, 2),
            "cost_at_stop": round(float(self.cost_at_stop), 2),
        }


@dataclass
class OptimisationResult:
    fuel_stops: list[FuelStopResult]
    total_gallons: float
    total_fuel_cost: Decimal
    distance_miles: float


class StationArray:
    def __init__(self, stations: list[FuelStation]) -> None:
        self.stations = stations
        self.lats = np.array([s.latitude for s in stations], dtype=np.float64)
        self.lons = np.array([s.longitude for s in stations], dtype=np.float64)
        self.prices = np.array([float(s.retail_price) for s in stations], dtype=np.float64)

    def distances_to_point(self, lat: float, lon: float) -> np.ndarray:
        phi1 = np.radians(lat)
        phi2 = np.radians(self.lats)
        dphi = np.radians(self.lats - lat)
        dlambda = np.radians(self.lons - lon)
        a = (
            np.sin(dphi / 2) ** 2
            + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2) ** 2
        )
        return 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(np.clip(a, 0, 1)))

    def find_cheapest_within_radius(
        self, lat: float, lon: float, radius_miles: float
    ) -> Optional[tuple[int, float]]:
        distances = self.distances_to_point(lat, lon)
        mask = distances <= radius_miles
        if not np.any(mask):
            return None
        candidate_prices = np.where(mask, self.prices, np.inf)
        best_idx = int(np.argmin(candidate_prices))
        return (best_idx, float(distances[best_idx]))


class FuelOptimizer:
    def __init__(
        self,
        max_range_miles: Optional[float] = None,
        mpg: Optional[float] = None,
        search_radius_miles: Optional[float] = None,
        safety_buffer_miles: Optional[float] = None,
    ) -> None:
        self.max_range = max_range_miles or settings.VEHICLE_MAX_RANGE_MILES
        self.mpg = mpg or settings.VEHICLE_MPG
        self.search_radius = search_radius_miles or settings.FUEL_SEARCH_RADIUS_MILES
        self.safety_buffer = safety_buffer_miles or settings.FUEL_STOP_THRESHOLD_MILES

    def optimise(
        self,
        geometry_coords: list[list[float]],
        total_distance_miles: float,
    ) -> OptimisationResult:

        # Downsample geometry to max 200 points
        if len(geometry_coords) > 200:
            step = len(geometry_coords) // 200
            geometry_coords = geometry_coords[::step]

        route_points = annotate_route_with_distances(geometry_coords)

        all_stations = list(FuelStationRepository.all_geocoded())
        if not all_stations:
            return OptimisationResult(
                fuel_stops=[],
                total_gallons=total_distance_miles / self.mpg,
                total_fuel_cost=Decimal("0"),
                distance_miles=total_distance_miles,
            )

        station_array = StationArray(all_stations)
        fuel_stops: list[FuelStopResult] = []
        current_miles = 0.0
        stop_number = 0
        max_stops = 10

        while current_miles < total_distance_miles and stop_number < max_stops:
            effective_range = self.max_range - self.safety_buffer  # 450 miles

            # Window starts well ahead to avoid re-selecting nearby stations
            # Ideal stop zone: between 60% and 90% of remaining range
            min_advance = current_miles + (effective_range * 0.6)  # don't stop too early
            window_end = min(current_miles + effective_range, total_distance_miles)

            # If we can reach the destination from here — we're done
            if window_end >= total_distance_miles:
                break

            best = self._find_best_in_window(
                route_points=route_points,
                station_array=station_array,
                window_start=min_advance,
                window_end=window_end,
            )

            if best is None:
                # No station in ideal zone — try full window
                best = self._find_best_in_window(
                    route_points=route_points,
                    station_array=station_array,
                    window_start=current_miles + 50,
                    window_end=window_end,
                )

            if best is None:
                # Still nothing — advance to end of window
                current_miles = window_end
                logger.warning("No station found, advancing to %.1f mi", current_miles)
                continue

            station_idx, stop_miles, detour_miles = best

            # Final safety: must always advance by at least 50 miles
            if stop_miles < current_miles + 50:
                stop_miles = min(current_miles + effective_range, total_distance_miles)

            station = all_stations[station_idx]
            segment_miles = stop_miles - current_miles
            gallons = segment_miles / self.mpg
            cost = Decimal(str(round(gallons, 6))) * station.retail_price

            stop_number += 1
            fuel_stops.append(
                FuelStopResult(
                    station_id=station.pk,
                    station_name=station.name,
                    city=station.city,
                    state=station.state,
                    address=station.address,
                    latitude=float(station.latitude),
                    longitude=float(station.longitude),
                    price_per_gallon=station.retail_price,
                    stop_number=stop_number,
                    distance_from_start_miles=round(stop_miles, 1),
                    distance_from_route_miles=round(detour_miles, 2),
                    gallons_purchased=round(gallons, 2),
                    cost_at_stop=cost,
                )
            )

            logger.info(
                "Stop %d: %s, %s @ $%.3f — mile %.1f (detour %.1f mi)",
                stop_number, station.name, station.city,
                station.retail_price, stop_miles, detour_miles,
            )
            current_miles = stop_miles

        total_gallons = total_distance_miles / self.mpg
        total_cost = sum(s.cost_at_stop for s in fuel_stops)

        if not fuel_stops:
            if route_points:
                result = station_array.find_cheapest_within_radius(
                    route_points[0].lat, route_points[0].lon, self.search_radius
                )
                price = Decimal(str(station_array.prices[result[0]])) if result else Decimal("3.50")
            else:
                price = Decimal("3.50")
            total_cost = Decimal(str(round(total_gallons, 4))) * price

        return OptimisationResult(
            fuel_stops=fuel_stops,
            total_gallons=total_gallons,
            total_fuel_cost=total_cost,
            distance_miles=total_distance_miles,
        )

    def _find_best_in_window(
        self,
        route_points: list[RoutePoint],
        station_array: StationArray,
        window_start: float,
        window_end: float,
    ) -> Optional[tuple[int, float, float]]:

        window_points = [
            p for p in route_points
            if window_start <= p.cumulative_miles <= window_end
        ]
        if not window_points:
            return None

        # Sample up to 20 evenly-spaced points
        step = max(1, len(window_points) // 20)
        sampled = window_points[::step]

        best_station_idx: Optional[int] = None
        best_price = float("inf")
        best_route_miles = 0.0
        best_detour = float("inf")

        for rp in sampled:
            result = station_array.find_cheapest_within_radius(
                rp.lat, rp.lon, self.search_radius
            )
            if result is None:
                continue
            idx, detour = result
            price = station_array.prices[idx]
            if price < best_price or (price == best_price and detour < best_detour):
                best_station_idx = idx
                best_price = price
                best_route_miles = rp.cumulative_miles
                best_detour = detour

        if best_station_idx is None:
            return None

        return (best_station_idx, best_route_miles, best_detour)