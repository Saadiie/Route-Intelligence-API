"""
Management command: import_fuel_prices
=======================================

Reads the OPIS truckstop CSV, geocodes each unique city/state pair using
the US city centroid lookup table (no external API needed), and bulk-inserts
FuelStation records.

Usage:
    python manage.py import_fuel_prices --file path/to/fuel-prices.csv

Options:
    --file      Path to the CSV file (required)
    --clear     Drop existing records before importing (default: False)
    --batch     Bulk-insert batch size (default: 500)
"""

from __future__ import annotations

import csv
import logging
import math
import os
import time
from decimal import Decimal, InvalidOperation
from typing import Optional

from django.core.management.base import BaseCommand, CommandError

from fuel.models import FuelStation

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# US city centroid lookup — curated from public domain Census data.
# Keys are (city_lower, state_upper). Covers every city that appears in
# common truckstop datasets. Falls back to state centroid for unknowns.
# ---------------------------------------------------------------------------

# fmt: off
US_CITY_COORDS: dict[tuple[str, str], tuple[float, float]] = {
    # Alabama
    ("birmingham", "AL"): (33.5186, -86.8104),
    ("huntsville", "AL"): (34.7304, -86.5861),
    ("mobile", "AL"): (30.6954, -88.0399),
    ("montgomery", "AL"): (32.3617, -86.2792),
    ("shorter", "AL"): (32.3952, -85.9169),
    # Arizona
    ("flagstaff", "AZ"): (35.1983, -111.6513),
    ("gila bend", "AZ"): (32.9476, -112.7185),
    ("eloy", "AZ"): (32.7837, -111.5548),
    ("lupton", "AZ"): (35.0083, -109.0704),
    ("phoenix", "AZ"): (33.4484, -112.0740),
    ("tucson", "AZ"): (32.2226, -110.9747),
    ("yuma", "AZ"): (32.6927, -114.6277),
    # Arkansas
    ("fort smith", "AR"): (35.3859, -94.3985),
    ("little rock", "AR"): (34.7465, -92.2896),
    ("west memphis", "AR"): (35.1465, -90.1848),
    # California
    ("bakersfield", "CA"): (35.3733, -119.0187),
    ("fresno", "CA"): (36.7378, -119.7871),
    ("los angeles", "CA"): (34.0522, -118.2437),
    ("sacramento", "CA"): (38.5816, -121.4944),
    ("san diego", "CA"): (32.7157, -117.1611),
    ("san francisco", "CA"): (37.7749, -122.4194),
    # Colorado
    ("atwood", "CO"): (40.5427, -103.2613),
    ("colorado springs", "CO"): (38.8339, -104.8214),
    ("denver", "CO"): (39.7392, -104.9903),
    ("dumont", "CO"): (39.7241, -105.7027),
    ("montrose", "CO"): (38.4783, -107.8762),
    # Connecticut
    ("hartford", "CT"): (41.7658, -72.6734),
    # Delaware
    ("laurel", "DE"): (38.5571, -75.5710),
    ("new castle", "DE"): (39.6620, -75.5660),
    # Florida
    ("ellenton", "FL"): (27.5239, -82.5301),
    ("jacksonville", "FL"): (30.3322, -81.6557),
    ("miami", "FL"): (25.7617, -80.1918),
    ("orlando", "FL"): (28.5383, -81.3792),
    ("tampa", "FL"): (27.9506, -82.4572),
    ("denham springs", "LA"): (30.4877, -90.9582),
    # Georgia
    ("atlanta", "GA"): (33.7490, -84.3880),
    ("crawfordville", "GA"): (33.5565, -82.8982),
    # Idaho
    ("boise", "ID"): (43.6150, -116.2023),
    # Illinois
    ("atkinson", "IL"): (41.4103, -90.0151),
    ("chicago", "IL"): (41.8781, -87.6298),
    ("effingham", "IL"): (39.1203, -88.5434),
    # Indiana
    ("daleville", "IN"): (40.1189, -85.5444),
    ("fort wayne", "IN"): (41.1306, -85.1289),
    ("hebron", "IN"): (41.3242, -87.2036),
    ("indianapolis", "IN"): (39.7684, -86.1581),
    ("lake station", "IN"): (41.5742, -87.2536),
    ("seymour", "IN"): (38.9584, -85.8913),
    # Iowa
    ("clear lake", "IA"): (43.1380, -93.3774),
    ("council bluffs", "IA"): (41.2619, -95.8608),
    ("latimer", "IA"): (42.7658, -93.3688),
    ("stuart", "IA"): (41.5033, -94.3186),
    # Kansas
    ("kansas city", "KS"): (39.1155, -94.6268),
    ("wichita", "KS"): (37.6872, -97.3301),
    # Kentucky
    ("henderson", "KY"): (37.8362, -87.5900),
    ("louisville", "KY"): (38.2527, -85.7585),
    # Louisiana
    ("baton rouge", "LA"): (30.4515, -91.1871),
    ("new orleans", "LA"): (29.9511, -90.0715),
    # Maine
    ("portland", "ME"): (43.6615, -70.2553),
    # Maryland
    ("baltimore", "MD"): (39.2904, -76.6122),
    # Massachusetts
    ("boston", "MA"): (42.3601, -71.0589),
    # Michigan
    ("bridgeport", "MI"): (43.3584, -83.8816),
    ("detroit", "MI"): (42.3314, -83.0458),
    # Minnesota
    ("minneapolis", "MN"): (44.9778, -93.2650),
    # Mississippi
    ("jackson", "MS"): (32.2988, -90.1848),
    # Missouri
    ("kansas city", "MO"): (39.0997, -94.5786),
    ("st. louis", "MO"): (38.6270, -90.1994),
    ("saint louis", "MO"): (38.6270, -90.1994),
    ("st louis", "MO"): (38.6270, -90.1994),
    # Montana
    ("billings", "MT"): (45.7833, -108.5007),
    # Nebraska
    ("gothenburg", "NE"): (40.9294, -100.1607),
    ("omaha", "NE"): (41.2565, -95.9345),
    # Nevada
    ("las vegas", "NV"): (36.1699, -115.1398),
    ("reno", "NV"): (39.5296, -119.8138),
    # New Jersey
    ("columbia", "NJ"): (40.9215, -75.1010),
    ("newark", "NJ"): (40.7357, -74.1724),
    # New Mexico
    ("albuquerque", "NM"): (35.0844, -106.6504),
    # New York
    ("new york", "NY"): (40.7128, -74.0060),
    ("buffalo", "NY"): (42.8864, -78.8784),
    # North Carolina
    ("charlotte", "NC"): (35.2271, -80.8431),
    # North Dakota
    ("bismarck", "ND"): (46.8083, -100.7837),
    ("sterling", "ND"): (46.8375, -100.2674),
    # Ohio
    ("cleveland", "OH"): (41.4993, -81.6944),
    ("columbus", "OH"): (39.9612, -82.9988),
    # Oklahoma
    ("big cabin", "OK"): (36.5412, -95.2202),
    ("oklahoma city", "OK"): (35.4676, -97.5164),
    ("tulsa", "OK"): (36.1540, -95.9928),
    # Oregon
    ("portland", "OR"): (45.5051, -122.6750),
    # Pennsylvania
    ("philadelphia", "PA"): (39.9526, -75.1652),
    ("pittsburgh", "PA"): (40.4406, -79.9959),
    # South Carolina
    ("columbia", "SC"): (34.0007, -81.0348),
    # South Dakota
    ("sioux falls", "SD"): (43.5446, -96.7311),
    # Tennessee
    ("memphis", "TN"): (35.1495, -90.0490),
    ("nashville", "TN"): (36.1627, -86.7816),
    # Texas
    ("amarillo", "TX"): (35.2220, -101.8313),
    ("austin", "TX"): (30.2672, -97.7431),
    ("dallas", "TX"): (32.7767, -96.7970),
    ("houston", "TX"): (29.7604, -95.3698),
    ("jarrell", "TX"): (30.8313, -97.6044),
    ("nacogdoches", "TX"): (31.6035, -94.6552),
    ("san antonio", "TX"): (29.4241, -98.4936),
    # Utah
    ("salt lake city", "UT"): (40.7608, -111.8910),
    # Virginia
    ("mount jackson", "VA"): (38.7462, -78.6427),
    ("richmond", "VA"): (37.5407, -77.4360),
    # Washington
    ("seattle", "WA"): (47.6062, -122.3321),
    # Wisconsin
    ("milwaukee", "WI"): (43.0389, -87.9065),
    ("tomah", "WI"): (43.9744, -90.5021),
    # Wyoming
    ("cheyenne", "WY"): (41.1400, -104.8202),
    ("moorcroft", "WY"): (44.2641, -104.9513),
    # West Virginia
    ("charleston", "WV"): (38.3498, -81.6326),
}

# State centroid fallbacks (when city not found)
US_STATE_CENTROIDS: dict[str, tuple[float, float]] = {
    "AL": (32.806671, -86.791130), "AK": (61.370716, -152.404419),
    "AZ": (33.729759, -111.431221), "AR": (34.969704, -92.373123),
    "CA": (36.116203, -119.681564), "CO": (39.059811, -105.311104),
    "CT": (41.597782, -72.755371), "DE": (39.318523, -75.507141),
    "FL": (27.766279, -81.686783), "GA": (33.040619, -83.643074),
    "HI": (21.094318, -157.498337), "ID": (44.240459, -114.478828),
    "IL": (40.349457, -88.986137), "IN": (39.849426, -86.258278),
    "IA": (42.011539, -93.210526), "KS": (38.526600, -96.726486),
    "KY": (37.668140, -84.670067), "LA": (31.169960, -91.867805),
    "ME": (44.693947, -69.381927), "MD": (39.063946, -76.802101),
    "MA": (42.230171, -71.530106), "MI": (43.326618, -84.536095),
    "MN": (45.694454, -93.900192), "MS": (32.741646, -89.678696),
    "MO": (38.456085, -92.288368), "MT": (46.921925, -110.454353),
    "NE": (41.125370, -98.268082), "NV": (38.313515, -117.055374),
    "NH": (43.452492, -71.563896), "NJ": (40.298904, -74.521011),
    "NM": (34.840515, -106.248482), "NY": (42.165726, -74.948051),
    "NC": (35.630066, -79.806419), "ND": (47.528912, -99.784012),
    "OH": (40.388783, -82.764915), "OK": (35.565342, -96.928917),
    "OR": (44.572021, -122.070938), "PA": (40.590752, -77.209755),
    "RI": (41.680893, -71.511780), "SC": (33.856892, -80.945007),
    "SD": (44.299782, -99.438828), "TN": (35.747845, -86.692345),
    "TX": (31.054487, -97.563461), "UT": (40.150032, -111.862434),
    "VT": (44.045876, -72.710686), "VA": (37.769337, -78.169968),
    "WA": (47.400902, -121.490494), "WV": (38.491226, -80.954453),
    "WI": (44.268543, -89.616508), "WY": (42.755966, -107.302490),
}
# fmt: on

US_STATES = set(US_STATE_CENTROIDS.keys())


def get_city_coords(city: str, state: str) -> Optional[tuple[float, float]]:
    """Resolve (lat, lon) for a city/state pair without any API call."""
    key = (city.strip().lower(), state.strip().upper())
    if key in US_CITY_COORDS:
        return US_CITY_COORDS[key]
    # Try state centroid as last resort
    return US_STATE_CENTROIDS.get(state.strip().upper())


class Command(BaseCommand):
    help = "Import fuel price data from the OPIS CSV file into the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            required=True,
            help="Path to the fuel-prices CSV file",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            default=False,
            help="Clear existing records before import",
        )
        parser.add_argument(
            "--batch",
            type=int,
            default=500,
            help="Bulk-insert batch size (default: 500)",
        )

    def handle(self, *args, **options) -> None:
        file_path: str = options["file"]
        clear: bool = options["clear"]
        batch_size: int = options["batch"]

        if not os.path.exists(file_path):
            raise CommandError(f"File not found: {file_path}")

        if clear:
            deleted, _ = FuelStation.objects.all().delete()
            self.stdout.write(f"Cleared {deleted} existing records.")

        self.stdout.write(f"Reading {file_path} …")
        t0 = time.time()

        stations: list[FuelStation] = []
        skipped = 0
        geocode_misses = 0

        with open(file_path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            for row_num, row in enumerate(reader, start=2):
                # --- Validate required fields ---
                try:
                    opis_id = int(row["OPIS Truckstop ID"])
                    name = row["Truckstop Name"].strip()
                    city = row["City"].strip()
                    state = row["State"].strip().upper()
                    price_raw = row["Retail Price"].strip()
                    retail_price = Decimal(price_raw)
                except (ValueError, KeyError, InvalidOperation) as exc:
                    logger.warning("Row %d skipped — %s: %s", row_num, type(exc).__name__, exc)
                    skipped += 1
                    continue

                # Skip non-US stations
                if state not in US_STATES:
                    skipped += 1
                    continue

                # Negative or zero prices are invalid
                if retail_price <= 0:
                    skipped += 1
                    continue

                coords = get_city_coords(city, state)
                if coords is None:
                    geocode_misses += 1

                rack_id_raw = row.get("Rack ID", "").strip()
                rack_id = int(rack_id_raw) if rack_id_raw.isdigit() else None

                stations.append(
                    FuelStation(
                        opis_id=opis_id,
                        name=name,
                        address=row.get("Address", "").strip(),
                        city=city,
                        state=state,
                        rack_id=rack_id,
                        retail_price=retail_price,
                        latitude=coords[0] if coords else None,
                        longitude=coords[1] if coords else None,
                    )
                )

        if not stations:
            self.stdout.write(self.style.WARNING("No valid records found — nothing imported."))
            return

        # Bulk insert
        self.stdout.write(f"Inserting {len(stations):,} records (batch={batch_size}) …")
        FuelStation.objects.bulk_create(stations, batch_size=batch_size, ignore_conflicts=False)

        elapsed = time.time() - t0
        self.stdout.write(
            self.style.SUCCESS(
                f"\n✓ Import complete in {elapsed:.1f}s\n"
                f"  Inserted : {len(stations):,}\n"
                f"  Skipped  : {skipped:,}\n"
                f"  No-geocode: {geocode_misses:,}\n"
                f"  Total DB : {FuelStation.objects.count():,}"
            )
        )
