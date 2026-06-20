"""
Trip API views.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from routing.services import RoutingError
from trips.serializers import TripRequestSerializer
from trips.services import TripPlanResult, plan_trip

logger = logging.getLogger(__name__)


class TripPlanView(APIView):
    """
    POST /api/trips/

    Plan a road trip between two US locations and return optimal fuel stops.

    Request body
    ------------
    {
        "start": "Houston, TX",
        "destination": "Chicago, IL"
    }

    Response (200 OK)
    -----------------
    {
        "distance_miles": 1080.5,
        "duration_hours": 17.2,
        "total_gallons": 108.05,
        "total_fuel_cost": 335.40,
        "fuel_stops": [
            {
                "stop_number": 1,
                "station_name": "LOVES TRAVEL STOP #766",
                "city": "Atkinson",
                "state": "IL",
                "address": "I-80, EXIT 27",
                "latitude": 41.41,
                "longitude": -90.01,
                "price_per_gallon": 3.389,
                "distance_from_start_miles": 495.0,
                "distance_from_route_miles": 0.8,
                "gallons_purchased": 49.5,
                "cost_at_stop": 167.76
            }
        ],
        "route": {
            "geometry": [[lon, lat], ...]
        },
        "summary": {
            "num_fuel_stops": 1,
            "avg_price_per_gallon": 3.389,
            "start": "Houston, TX",
            "destination": "Chicago, IL"
        }
    }
    """

    def post(self, request: Request) -> Response:
        # 1. Validate input
        serializer = TripRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "Invalid request", "details": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        start: str = serializer.validated_data["start"]
        destination: str = serializer.validated_data["destination"]

        # 2. Plan trip
        try:
            result: TripPlanResult = plan_trip(start, destination)
        except ValueError as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except RoutingError as exc:
            logger.error("Routing failed for %s → %s: %s", start, destination, exc)
            return Response(
                {
                    "error": "Could not compute route.",
                    "details": str(exc),
                    "hint": (
                        "Ensure ORS_API_KEY is set for best results, "
                        "or the OSRM demo server may be temporarily unavailable."
                    ),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as exc:
            logger.exception("Unexpected error planning trip %s → %s", start, destination)
            return Response(
                {"error": "An unexpected error occurred.", "details": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # 3. Assemble response
        stops_data = [s.to_dict() for s in result.fuel_stops]
        avg_price = (
            sum(s["price_per_gallon"] for s in stops_data) / len(stops_data)
            if stops_data
            else 0.0
        )

        response_data = {
            "distance_miles": round(result.distance_miles, 1),
            "duration_hours": round(result.duration_hours, 2),
            "total_gallons": round(result.total_gallons, 2),
            "total_fuel_cost": round(float(result.total_fuel_cost), 2),
            "fuel_stops": stops_data,
            "route": {
                "geometry": result.route_geometry,
            },
            "summary": {
                "start": start,
                "destination": destination,
                "num_fuel_stops": len(stops_data),
                "avg_price_per_gallon": round(avg_price, 3),
            },
        }

        return Response(response_data, status=status.HTTP_200_OK)
