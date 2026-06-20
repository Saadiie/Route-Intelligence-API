# Fuel Route API

A production-quality Django REST API that plans a road trip between two US locations, finds optimal (cheapest) fuel stops along the route, and returns the estimated total fuel cost.

---

## Architecture Overview

```
fuel_route_api/
├── config/                  # Django project settings & root URLs
├── fuel/                    # Fuel station data model + repository + management commands
│   ├── models.py            # FuelStation model
│   ├── repositories/        # FuelStationRepository (data-access layer)
│   └── management/commands/ # import_fuel_prices command
├── routing/                 # Route fetching & geospatial utilities
│   ├── models.py            # Route model (DB-cached routes)
│   ├── services.py          # get_route() — ORS / OSRM integration
│   └── utils.py             # Haversine, route interpolation, binary search
└── trips/                   # Trip planning orchestration
    ├── fuel_optimizer.py    # Core optimisation algorithm
    ├── services.py          # plan_trip() orchestrator
    ├── serializers.py       # DRF serializers
    ├── views.py             # TripPlanView
    └── tests.py             # 24 unit + integration tests
```

### Request Lifecycle

```
POST /api/trips/
     │
     ▼
TripRequestSerializer.validate()
     │
     ▼
routing.services.get_route()
  ├── DB cache hit? → return cached Route
  └── API miss → ORS (1 call) or OSRM (3 calls) → save to DB
     │
     ▼
trips.fuel_optimizer.FuelOptimizer.optimise()
  ├── annotate_route_with_distances()   O(n)
  ├── For each 500-mile window:
  │     ├── Bounding-box pre-filter     O(S) DB query (index)
  │     ├── Haversine exact filter      O(S_local) Python
  │     └── Sort by (price, detour)     O(S_local log S_local)
  └── Collect fuel stops
     │
     ▼
JSON Response
```

---

## Fuel Stop Optimisation Algorithm

**Strategy**: Greedy lookahead with cheapest-reachable-station selection.

**Why greedy?**
An exact DP solution over all station sequences would be O(S² · N) — with
8000 stations and 1000+ route points that's ~64B operations per request.
The greedy approach achieves near-optimal results because:
- It looks ahead a full tank's worth (500 miles) before committing to a stop
- It selects the *cheapest* station in the window, not the first
- Detour tie-breaking prevents costly off-route diversions

**Time Complexity per call**: `O(W · S_local · log N)`
- `W` = number of fuel stops ≈ route_miles / 450 (typically 1–8)
- `S_local` = stations within bounding box ≈ 20–200
- `N` = route geometry points (typically 100–5000)

**Priority order** (primary → secondary → tertiary):
1. **Lowest price** — minimise cost
2. **Smallest detour** — avoid long diversions
3. **Closest to window midpoint** — avoid stopping too early

---

## Quick Start

### 1. Clone & install

```bash
git clone <repo-url> fuel_route_api
cd fuel_route_api
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### 2. Environment variables

```bash
cp .env.example .env
# Edit .env — at minimum set DJANGO_SECRET_KEY
```

### 3. PostgreSQL setup (recommended)

```sql
CREATE DATABASE fuel_route_db;
CREATE USER fuel_user WITH PASSWORD 'yourpassword';
GRANT ALL PRIVILEGES ON DATABASE fuel_route_db TO fuel_user;
```

In `.env`:
```
DB_ENGINE=postgresql
DB_NAME=fuel_route_db
DB_USER=fuel_user
DB_PASSWORD=yourpassword
```

> **SQLite fallback**: Leave `DB_ENGINE=sqlite` (default) for local development without PostgreSQL.

### 4. Routing API key (recommended)

Get a **free** OpenRouteService key at https://openrouteservice.org/  
Add to `.env`:
```
ORS_API_KEY=your-key-here
```

Without a key the app falls back to the OSRM public demo server (uses 3 API calls instead of 1 for ORS).

### 5. Apply migrations

```bash
python manage.py migrate
```

### 6. Import fuel price data

```bash
python manage.py import_fuel_prices --file path/to/fuel-prices-for-be-assessment.csv
```

Output:
```
✓ Import complete in 0.5s
  Inserted : 7,531
  Skipped  : 620 (non-US / invalid)
  Total DB : 7,531
```

### 7. Run server

```bash
python manage.py runserver
```

---

## API Reference

### `POST /api/trips/`

Plan a road trip with optimal fuel stops.

**Request**
```json
{
    "start": "Houston, TX",
    "destination": "Chicago, IL"
}
```

**Response 200 OK**
```json
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
        "geometry": [[-95.37, 29.76], [-90.0, 35.0], [-87.63, 41.88]]
    },
    "summary": {
        "start": "Houston, TX",
        "destination": "Chicago, IL",
        "num_fuel_stops": 1,
        "avg_price_per_gallon": 3.389
    }
}
```

**Error responses**

| Status | Condition |
|--------|-----------|
| 400    | Missing fields, same start/destination |
| 503    | Routing API unavailable |
| 500    | Unexpected server error |

---

## Running Tests

```bash
python manage.py test --verbosity=2
```

24 tests covering:
- Haversine distance (symmetry, known distances, edge cases)
- Route annotation & binary search interpolation
- Fuel stop cost calculation
- Optimiser (no-stop short trips, stop selection)
- API endpoint (validation, response shape, error handling)

---

## Performance Notes

- **Route caching**: Identical (start, destination) pairs never hit the external API twice
- **Memory processing**: Fuel stop optimisation runs entirely in Python — zero extra DB queries during the algorithm
- **Bounding-box pre-filter**: SQL index on `(latitude, longitude)` shrinks the candidate set before exact Haversine calculation
- **Bulk import**: Management command uses `bulk_create(batch_size=500)` — 7500 rows in < 1 second

---

## Scalability Considerations

- Add **Redis** caching for the local-memory cache to work across multiple server processes
- Use **PostgreSQL PostGIS** + `ST_DWithin` for O(log n) spatial queries at scale
- The optimiser is stateless — horizontally scalable behind a load balancer
- Route geometry is stored in the DB — a CDN or object store could serve large geometries
