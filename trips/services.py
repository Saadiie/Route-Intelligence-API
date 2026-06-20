"""
Trip planning service.

Orchestrates:
  1. Route retrieval (cached or fresh API call)
  2. Fuel stop optimisation
  3. Result assembly

This is the single entry point for the trips view.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from routing.models import Route
from routing.services import get_route
from trips.fuel_optimizer import FuelOptimizer, FuelStopResult, OptimisationResult

logger = logging.getLogger(__name__)


@dataclass
class TripPlanResult:
    """Final result returned to the API view."""

    distance_miles: float
    duration_hours: float
    fuel_stops: list[FuelStopResult]
    total_gallons: float
    total_fuel_cost: Decimal
    route_geometry: list[list[float]]  # [[lon, lat], ...]


def plan_trip(start: str, destination: str) -> TripPlanResult:
    """
    Plan a road trip from *start* to *destination*.

    Returns
    -------
    TripPlanResult
        All data needed to assemble the API response.

    Raises
    ------
    routing.services.RoutingError
        If the route cannot be fetched.
    ValueError
        If inputs are empty or identical.
    """
    start = start.strip()
    destination = destination.strip()

    if not start or not destination:
        raise ValueError("Both 'start' and 'destination' are required.")
    if start.lower() == destination.lower():
        raise ValueError("Start and destination must be different locations.")

    logger.info("Planning trip: %s → %s", start, destination)

    # 1. Fetch (or load cached) route
    route: Route = get_route(start, destination)
    logger.info("Route: %.1f miles, %.1f min", route.distance_miles, route.duration_minutes)

    # 2. Optimise fuel stops
    optimizer = FuelOptimizer()
    result: OptimisationResult = optimizer.optimise(
        geometry_coords=route.geometry,
        total_distance_miles=route.distance_miles,
    )

    return TripPlanResult(
        distance_miles=route.distance_miles,
        duration_hours=route.duration_minutes / 60,
        fuel_stops=result.fuel_stops,
        total_gallons=result.total_gallons,
        total_fuel_cost=result.total_fuel_cost,
        route_geometry=route.geometry,
    )
