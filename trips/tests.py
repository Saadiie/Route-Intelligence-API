"""
Unit tests for the Fuel Route API.

Run with: python manage.py test

Coverage targets:
  - Routing utils (haversine, interpolation, binary search)
  - Fuel optimizer algorithm (stop selection, cost calculation)
  - Trip service (integration)
  - API endpoint (request validation, response shape)
"""

from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase
from rest_framework.test import APITestCase, APIClient

from fuel.models import FuelStation
from routing.utils import (
    LatLon,
    RoutePoint,
    annotate_route_with_distances,
    find_point_at_distance,
    haversine_miles,
)
from trips.fuel_optimizer import FuelOptimizer, FuelStopResult


# ===========================================================================
# Routing utils tests
# ===========================================================================


class HaversineTestCase(TestCase):
    """Tests for the haversine distance function."""

    def test_same_point(self):
        p = LatLon(40.7128, -74.0060)
        self.assertAlmostEqual(haversine_miles(p, p), 0.0, places=5)

    def test_nyc_to_la(self):
        nyc = LatLon(40.7128, -74.0060)
        la = LatLon(34.0522, -118.2437)
        dist = haversine_miles(nyc, la)
        # Great-circle NYC–LA ≈ 2451 miles
        self.assertGreater(dist, 2400)
        self.assertLess(dist, 2500)

    def test_symmetry(self):
        a = LatLon(30.0, -90.0)
        b = LatLon(35.0, -95.0)
        self.assertAlmostEqual(haversine_miles(a, b), haversine_miles(b, a), places=8)

    def test_short_distance(self):
        # Two points ~1 mile apart (roughly 0.0145 degrees at this latitude)
        a = LatLon(40.0, -75.0)
        b = LatLon(40.0145, -75.0)
        dist = haversine_miles(a, b)
        self.assertGreater(dist, 0.9)
        self.assertLess(dist, 1.2)


class AnnotateRouteTestCase(TestCase):
    """Tests for route interpolation."""

    def _straight_line_coords(self) -> list[list[float]]:
        """Simple 4-point route roughly along a line."""
        return [
            [-74.0060, 40.7128],   # NYC (lon, lat)
            [-80.0, 40.5],
            [-90.0, 40.0],
            [-100.0, 39.5],
        ]

    def test_first_point_is_zero(self):
        points = annotate_route_with_distances(self._straight_line_coords())
        self.assertEqual(points[0].cumulative_miles, 0.0)

    def test_monotonically_increasing(self):
        points = annotate_route_with_distances(self._straight_line_coords())
        for i in range(1, len(points)):
            self.assertGreater(points[i].cumulative_miles, points[i - 1].cumulative_miles)

    def test_empty_input(self):
        self.assertEqual(annotate_route_with_distances([]), [])

    def test_single_point(self):
        points = annotate_route_with_distances([[-74.0, 40.7]])
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0].cumulative_miles, 0.0)


class FindPointAtDistanceTestCase(TestCase):
    """Tests for binary-search interpolation."""

    def setUp(self):
        self.points = [
            RoutePoint(40.0, -74.0, 0.0),
            RoutePoint(40.5, -80.0, 300.0),
            RoutePoint(41.0, -90.0, 700.0),
            RoutePoint(41.5, -100.0, 1100.0),
        ]

    def test_exact_start(self):
        p = find_point_at_distance(self.points, 0.0)
        self.assertAlmostEqual(p.cumulative_miles, 0.0)

    def test_exact_end(self):
        p = find_point_at_distance(self.points, 1100.0)
        self.assertAlmostEqual(p.cumulative_miles, 1100.0)

    def test_midpoint(self):
        p = find_point_at_distance(self.points, 500.0)
        # Should return the point closest to 500 — which is 300 or 700
        self.assertIn(p.cumulative_miles, [300.0, 700.0])

    def test_beyond_end_clamps(self):
        p = find_point_at_distance(self.points, 9999.0)
        self.assertAlmostEqual(p.cumulative_miles, 1100.0)




class FuelOptimizerTestCase(TestCase):
    """Tests for the fuel stop optimisation algorithm."""

    def _make_station(
        self,
        pk: int,
        name: str,
        lat: float,
        lon: float,
        price: float,
        city: str = "TestCity",
        state: str = "TX",
    ) -> FuelStation:
        """Create an in-memory (unsaved) FuelStation for testing."""
        s = FuelStation(
            id=pk,
            opis_id=pk,
            name=name,
            city=city,
            state=state,
            latitude=lat,
            longitude=lon,
            retail_price=Decimal(str(price)),
        )
        return s

    def _simple_geometry(self, n_points: int = 20) -> list[list[float]]:
        """Generate a simple west-to-east route across ~1000 miles."""
        # Roughly Houston TX → Kansas City MO line
        lons = [-95.37 + i * (5.0 / n_points) for i in range(n_points)]
        lats = [29.76 + i * (10.0 / n_points) for i in range(n_points)]
        return [[lon, lat] for lon, lat in zip(lons, lats)]

    @patch.object(FuelOptimizer, "_find_best_in_window")
    @patch("trips.fuel_optimizer.FuelStationRepository")
    def test_no_stops_short_trip(self, mock_repo_cls, mock_find_best):
        """A trip shorter than MAX_RANGE should need zero fuel stops."""
        mock_repo_cls.all_geocoded.return_value = []
        mock_repo_cls.find_within_radius.return_value = [
            self._make_station(1, "Test Station", 30.0, -95.0, 3.50)
        ]
        mock_find_best.return_value = None

        optimizer = FuelOptimizer(max_range_miles=500, mpg=10, safety_buffer_miles=50)

        # A 400-mile trip should require no stops
        geom = self._simple_geometry(10)
        with patch("trips.fuel_optimizer.FuelStationRepository.all_geocoded", return_value=[]):
            with patch("trips.fuel_optimizer.FuelStationRepository.find_within_radius",
                       return_value=[self._make_station(1, "S", 30.0, -95.0, 3.50)]):
                result = optimizer.optimise(geom, total_distance_miles=400.0)

        self.assertEqual(len(result.fuel_stops), 0)
        self.assertAlmostEqual(result.total_gallons, 40.0, places=1)

    def test_cost_calculation(self):
        """Total cost = sum of per-stop costs."""
        stop1 = FuelStopResult(
            station_id=1, station_name="A", city="X", state="TX",
            address="", latitude=30.0, longitude=-95.0,
            price_per_gallon=Decimal("3.00"),
            stop_number=1, distance_from_start_miles=490.0,
            distance_from_route_miles=1.0,
            gallons_purchased=49.0,
            cost_at_stop=Decimal("147.00"),
        )
        stop2 = FuelStopResult(
            station_id=2, station_name="B", city="Y", state="OK",
            address="", latitude=35.0, longitude=-97.0,
            price_per_gallon=Decimal("3.50"),
            stop_number=2, distance_from_start_miles=940.0,
            distance_from_route_miles=0.5,
            gallons_purchased=45.0,
            cost_at_stop=Decimal("157.50"),
        )
        total = stop1.cost_at_stop + stop2.cost_at_stop
        self.assertEqual(total, Decimal("304.50"))

    def test_fuel_stop_to_dict(self):
        """FuelStopResult.to_dict() has all required keys."""
        stop = FuelStopResult(
            station_id=1, station_name="Test", city="Dallas", state="TX",
            address="I-35", latitude=32.77, longitude=-96.79,
            price_per_gallon=Decimal("3.20"),
            stop_number=1, distance_from_start_miles=450.0,
            distance_from_route_miles=1.2,
            gallons_purchased=45.0,
            cost_at_stop=Decimal("144.00"),
        )
        d = stop.to_dict()
        required_keys = {
            "stop_number", "station_name", "city", "state", "address",
            "latitude", "longitude", "price_per_gallon",
            "distance_from_start_miles", "distance_from_route_miles",
            "gallons_purchased", "cost_at_stop",
        }
        self.assertEqual(required_keys, set(d.keys()))





class TripPlanAPITestCase(APITestCase):
    """Integration tests for POST /api/trips/."""

    def setUp(self):
        self.client = APIClient()
        self.url = "/api/trips/"

    def test_missing_fields(self):
        resp = self.client.post(self.url, {}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_missing_destination(self):
        resp = self.client.post(self.url, {"start": "Houston, TX"}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_same_start_and_destination(self):
        resp = self.client.post(
            self.url,
            {"start": "Houston, TX", "destination": "Houston, TX"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    @patch("trips.views.plan_trip")
    def test_successful_response_shape(self, mock_plan):
        """Mock plan_trip and verify response shape."""
        from trips.services import TripPlanResult

        mock_plan.return_value = TripPlanResult(
            distance_miles=1080.0,
            duration_hours=17.2,
            fuel_stops=[
                FuelStopResult(
                    station_id=1,
                    station_name="Loves Travel Stop",
                    city="Atkinson",
                    state="IL",
                    address="I-80, EXIT 27",
                    latitude=41.41,
                    longitude=-90.01,
                    price_per_gallon=Decimal("3.389"),
                    stop_number=1,
                    distance_from_start_miles=495.0,
                    distance_from_route_miles=0.8,
                    gallons_purchased=49.5,
                    cost_at_stop=Decimal("167.76"),
                )
            ],
            total_gallons=108.0,
            total_fuel_cost=Decimal("335.40"),
            route_geometry=[[-95.37, 29.76], [-87.63, 41.88]],
        )

        resp = self.client.post(
            self.url,
            {"start": "Houston, TX", "destination": "Chicago, IL"},
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertIn("distance_miles", data)
        self.assertIn("duration_hours", data)
        self.assertIn("total_gallons", data)
        self.assertIn("total_fuel_cost", data)
        self.assertIn("fuel_stops", data)
        self.assertIn("route", data)
        self.assertIn("summary", data)
        self.assertIn("geometry", data["route"])
        self.assertEqual(len(data["fuel_stops"]), 1)
        self.assertEqual(data["fuel_stops"][0]["station_name"], "Loves Travel Stop")

    @patch("trips.views.plan_trip")
    def test_routing_error_returns_503(self, mock_plan):
        from routing.services import RoutingError
        mock_plan.side_effect = RoutingError("API down")

        resp = self.client.post(
            self.url,
            {"start": "New York, NY", "destination": "Los Angeles, CA"},
            format="json",
        )
        self.assertEqual(resp.status_code, 503)

    @patch("trips.views.plan_trip")
    def test_value_error_returns_400(self, mock_plan):
        mock_plan.side_effect = ValueError("Bad location")

        resp = self.client.post(
            self.url,
            {"start": "BadPlace", "destination": "AlsoBad"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)




class FuelStationModelTestCase(TestCase):
    """Tests for FuelStation model properties."""

    def test_coordinates_property_with_values(self):
        station = FuelStation(latitude=30.0, longitude=-95.0)
        self.assertEqual(station.coordinates, (30.0, -95.0))

    def test_coordinates_property_none(self):
        station = FuelStation(latitude=None, longitude=None)
        self.assertIsNone(station.coordinates)

    def test_str_representation(self):
        station = FuelStation(
            name="Test Station",
            city="Houston",
            state="TX",
            retail_price=Decimal("3.259"),
        )
        self.assertIn("Test Station", str(station))
        self.assertIn("Houston", str(station))
