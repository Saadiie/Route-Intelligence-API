# Fuel Route API

A Django REST API that plans road trips across the USA and finds the cheapest fuel stops along the way. Built as a technical assessment for a Backend Django Engineer position.

You give it a start and destination, it figures out where to stop for fuel, which stations have the best prices, and how much the whole trip is going to cost you in gas.

---

## What it does

- Accepts any two US city names as input
- Fetches the driving route (one API call, cached after that)
- Scans 7,531 real fuel stations from the provided dataset
- Picks the cheapest stations at logical intervals along the route
- Returns fuel stops, prices, gallons, cost per stop, and total trip cost
- Returns the full route geometry for mapping

### Example

```
POST /api/trips/
{
    "start": "Houston, TX",
    "destination": "Chicago, IL"
}
```

Response includes 3 fuel stops across 1,130 miles, total cost around $241 for 113 gallons.

---

## Tech stack

- Python 3.11
- Django 5.2 + Django REST Framework
- SQLite (default) or PostgreSQL
- NumPy for vectorized distance calculations
- OpenRouteService for routing (free tier, 1 API call per unique route)
- Offline fallback using built-in city coordinates (no API key required to run)

---

## Project structure

```
fuel_route_api/
├── config/              # Django settings and root URLs
├── fuel/                # Fuel station model, repository, import command
│   ├── models.py
│   ├── repositories/
│   └── management/commands/import_fuel_prices.py
├── routing/             # Route fetching, caching, geo utilities
│   ├── models.py        # Route model (cached in DB)
│   ├── services.py      # ORS / offline route builder
│   └── utils.py         # Haversine, interpolation, binary search
└── trips/               # Trip planning, optimizer, API view
    ├── fuel_optimizer.py # Core greedy algorithm with numpy
    ├── services.py
    ├── views.py
    └── tests.py          # 24 unit tests
```

---

## How a request flows through the system

When you POST to `/api/trips/`, here is exactly what happens step by step:

```
POST /api/trips/
{ "start": "Houston, TX", "destination": "Chicago, IL" }
        │
        ▼
1. REQUEST VALIDATION (trips/serializers.py)
   - Are both fields present?
   - Are start and destination different?
   - If not → 400 Bad Request immediately
        │
        ▼
2. ROUTE LOOKUP (routing/services.py)
   - Check database: has this route been fetched before?
   - Cache HIT  → return stored route instantly (0 external API calls)
   - Cache MISS → call OpenRouteService API (1 call)
                  or use offline city coordinates (0 calls)
                  → save route to database for next time
        │
        ▼
3. ROUTE ANNOTATION (routing/utils.py)
   - Convert raw [lon, lat] coordinates into RoutePoints
   - Attach cumulative mileage to every point
   - e.g. point at index 45 = mile 312.4 from start
        │
        ▼
4. FUEL OPTIMIZATION (trips/fuel_optimizer.py)
   - Load all 7,531 stations into NumPy arrays (one DB query)
   - Walk the route in windows:
       Window 1: miles 270–450
         → vectorized distance to all 7,531 stations (10ms)
         → filter to stations within 50 miles of route
         → pick cheapest → record Stop 1
       Window 2: miles 540–900
         → same process → record Stop 2
       Window 3: miles 810–1080
         → same process → record Stop 3
       Can we reach Chicago now? Yes → done
        │
        ▼
5. COST CALCULATION
   - gallons per leg = leg_miles / 10
   - cost per stop = gallons × price_per_gallon
   - total_cost = sum of all stop costs
        │
        ▼
6. JSON RESPONSE
   - distance_miles, duration_hours
   - fuel_stops array with all stop details
   - total_gallons, total_fuel_cost
   - route.geometry for mapping
   - summary with avg price and stop count
```

The whole thing — from receiving the request to sending the response — takes about 3 seconds on first call and under 1 second on repeat calls.

---

## Getting started

### 1. Clone the repo

```bash
git clone https://github.com/yourusername/fuel-route-api.git
cd fuel-route-api
```

### 2. Create a virtual environment

```bash
# Windows
py -3.11 -m venv venv
venv\Scripts\activate

# Mac/Linux
python3.11 -m venv venv
source venv/bin/activate
```

> **Important:** Use Python 3.11 specifically. Python 3.13+ has compatibility issues with NumPy that cause very slow performance.

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Set up environment variables

Copy the example file and edit it:

```bash
cp .env.example .env
```

At minimum, set a secret key:

```
DJANGO_SECRET_KEY=some-long-random-string-here
```

### 5. Run migrations

```bash
python manage.py migrate
```

### 6. Import the fuel station data

```bash
python manage.py import_fuel_prices --file "path/to/fuel-prices-for-be-assessment.csv"
```

This imports all 7,531 US stations in under 3 seconds. You'll see a summary like:

```
✓ Import complete in 2.4s
  Inserted : 7,531
  Skipped  : 620 (non-US stations)
  Total DB : 7,531
```

### 7. Start the server

```bash
python manage.py runserver
```

The API is now running at `http://127.0.0.1:8000`

---

## API reference

### POST /api/trips/

Plan a road trip with optimal fuel stops.

**Request body:**

```json
{
    "start": "Houston, TX",
    "destination": "Chicago, IL"
}
```

Both fields are required and must be US cities. Start and destination must be different.

**Response (200 OK):**

```json
{
    "distance_miles": 1130.3,
    "duration_hours": 18.84,
    "total_gallons": 113.03,
    "total_fuel_cost": 241.46,
    "fuel_stops": [
        {
            "stop_number": 1,
            "station_name": "SHELL",
            "city": "Osceola",
            "state": "AR",
            "address": "I-55, EXIT 48",
            "latitude": 34.97,
            "longitude": -92.37,
            "price_per_gallon": 2.999,
            "distance_from_start_miles": 398.2,
            "distance_from_route_miles": 5.21,
            "gallons_purchased": 39.82,
            "cost_at_stop": 119.42
        }
    ],
    "route": {
        "geometry": [[-95.37, 29.76], ...]
    },
    "summary": {
        "start": "Houston, TX",
        "destination": "Chicago, IL",
        "num_fuel_stops": 3,
        "avg_price_per_gallon": 2.942
    }
}
```

**Error responses:**

| Status | When |
|--------|------|
| 400 | Missing fields, same start and destination |
| 503 | Routing API unavailable |
| 500 | Unexpected server error |

---

## Routing API setup (optional but recommended)

The API works out of the box using offline city coordinates. For real road routes, get a free OpenRouteService key:

1. Sign up at https://openrouteservice.org/dev/#/signup
2. Copy your API key from the dashboard
3. Add it to your `.env` file:

```
ORS_API_KEY=your-key-here
```

Then restart the server. With an ORS key you get actual highway routes instead of interpolated straight lines.

Without a key the API still works — it uses built-in coordinates for all major US cities and estimates road distance as 1.2x the straight-line distance.

---

## PostgreSQL setup (optional)

SQLite works fine for development. For production, switch to PostgreSQL:

```sql
CREATE DATABASE fuel_route_db;
CREATE USER fuel_user WITH PASSWORD 'yourpassword';
GRANT ALL PRIVILEGES ON DATABASE fuel_route_db TO fuel_user;
```

Update `.env`:

```
DB_ENGINE=postgresql
DB_NAME=fuel_route_db
DB_USER=fuel_user
DB_PASSWORD=yourpassword
DB_HOST=localhost
DB_PORT=5432
```

---

## Running tests

```bash
python manage.py test --verbosity=2
```

24 tests covering:

- Haversine distance calculations (accuracy, symmetry, edge cases)
- Route annotation and binary search interpolation
- Fuel stop cost calculation
- Optimizer algorithm (short trips, stop selection)
- API validation (missing fields, same location, error handling)
- Response shape verification

---

## How the fuel stop algorithm works

The vehicle starts with a full tank (500 miles range, 10 MPG). The algorithm walks the route in windows:

1. From the current position, look ahead to the zone between 60% and 90% of remaining range — this is the ideal refuel zone
2. Find all fuel stations within 50 miles of the route in that zone
3. Pick the cheapest one (tie-break: smallest detour off the highway)
4. Record the stop, advance to that position, repeat
5. Stop when the destination is reachable on the current tank

**Why not find the mathematically perfect solution?** An exhaustive search across all 7,531 stations for every possible stop sequence would require billions of comparisons per request. The greedy window approach produces near-optimal results in under 3 seconds because fuel prices don't vary dramatically over 400-mile stretches.

**Why NumPy?** Distance from a point to all 7,531 stations is calculated in a single vectorized operation — all at once instead of one by one. This runs in under 10 milliseconds per calculation.

---

## Caching

Routes are saved to the database after the first fetch. If you request Houston → Chicago a second time, zero external API calls are made and the response comes back in under 1 second.

This satisfies the requirement of minimizing routing API calls — each unique city pair only ever hits the external API once.

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DJANGO_SECRET_KEY` | insecure default | Change this in production |
| `DJANGO_DEBUG` | `True` | Set to `False` in production |
| `DB_ENGINE` | `sqlite` | Set to `postgresql` for Postgres |
| `ORS_API_KEY` | empty | OpenRouteService API key (optional) |
| `VEHICLE_MAX_RANGE_MILES` | `500` | Vehicle range in miles |
| `VEHICLE_MPG` | `10` | Fuel efficiency |
| `FUEL_SEARCH_RADIUS_MILES` | `50` | How far off-route to search for stations |

---

## Postman collection

Import `postman_collection.json` into Postman to get 5 pre-built requests:

- Houston, TX → Chicago, IL
- New York, NY → Los Angeles, CA
- Seattle, WA → Miami, FL
- Validation error: same start and destination
- Validation error: missing destination field

Set the `base_url` variable to `http://127.0.0.1:8000` before running.