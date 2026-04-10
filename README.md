# WalkWithMe Backend — Pedestrian Routing, Route Enrichment, and City Discovery

This repository contains the backend API for WalkWithMe, a pedestrian-first city exploration system designed to support purpose-driven walking, landmark discovery, viral food spot discovery, scenic loop generation, AR navigation, and safety-aware routing.

The backend is built around Valhalla as the core routing engine and extends it with route enrichment via Overpass (OSM), themed walk generation, detour scoring, time-aware walk personas, unexplored city tracking, and AI-style route ranking. It is intentionally frontend-agnostic and serves the WalkWithMe iOS client.

The system is designed to work globally, without reliance on proprietary map SDKs or region-specific datasets.

---

System Responsibilities

The backend is responsible for:

- Computing pedestrian routes optimized for different intents and themes
- Enriching routes with landmarks, food spots, parks, and neighborhood flavor
- Discovering worthwhile detours along a route with quantified time cost
- Generating themed walking loops seeded by real POIs
- Providing time-aware walk personas based on weather and time of day
- Ranking routes based on safety, scenery, elevation, and context
- Tracking unexplored city coverage from client-submitted walk history
- Performing elevation analysis and difficulty estimation
- Exporting routes as standard GPX files
- Converting between human-readable locations and coordinates
- Providing structured, mobile-friendly JSON responses
- Supporting AR navigation with simplified waypoints and turn metadata
- Interpreting vision-based hazard signals for AR presentation

---

High-Level Architecture

The backend is structured as a layered FastAPI service:

Request Layer
- FastAPI endpoints defined in backend/main.py
- Input validation and error handling
- Stateless request handling
- In-memory TTL caching for routes and Overpass results

Routing Core
- Unified routing dispatcher in backend/routing.py
- Mode-specific routing logic split by intent
- Valhalla as the underlying graph and path engine
- Parallel Valhalla calls via ThreadPoolExecutor for multi-candidate modes

Enrichment and Discovery
- Overpass API (OSM) for landmark, food, park, and POI discovery
- Corridor-filtered POI attachment to route geometry
- Detour scoring engine with quantified time cost
- Neighborhood flavor classification
- Themed walk catalog and POI-seeded loop generation

Context and Personalization
- Time-aware walk personas (Morning, Golden Hour, Night, Rainy Day, etc.)
- Walk theme catalog (Coffee, History, Parks, Food, Landmark, Scenic, Explore)
- Unexplored city analysis from client walk history

Supporting Systems
- Geocoding and reverse geocoding (Nominatim + Photon fallback)
- Elevation analysis with multi-source fallback pipeline
- GPX export and import
- Vision interpretation endpoint

Caching
- Route cache: 30-min TTL for deterministic modes
- Overpass cache: 1-hour TTL keyed by bounding box hash
- In-memory, thread-safe, max-size eviction

---

Routing Architecture

Valhalla is used as the underlying pedestrian routing engine. All routing modes ultimately call Valhalla, but with different costing profiles, candidate generation strategies, and post-processing steps.

Routing flow:

1. Parse input locations (text or coordinates)
2. Check route cache — return immediately if hit
3. Generate one or more candidate routes via Valhalla (parallel where applicable)
4. Decode geometry (polyline6)
5. Extract turn-by-turn maneuvers
6. Simplify geometry for AR usage
7. Apply scoring or ranking logic
8. Optionally run enrichment and elevation in parallel
9. Return structured JSON suitable for mobile clients

The routing dispatcher (backend/routing.py) acts as a single entry point and delegates to mode-specific implementations.

---

Routing Modes

SHORTEST
Uses Valhalla pedestrian routing with minimal customization. Intended for efficiency and baseline comparisons.

SAFE
Adjusts pedestrian costing based on time of day. During night hours, it strongly prioritizes lit roads, avoids alleys, and increases safety weighting. Designed for real-world walking safety rather than shortest distance.

SCENIC
Biases routes toward greenery, parks, waterfronts, and low-density streets. Runs 3 candidate routes in parallel, scores each by green, water, and scenic signal derived from Valhalla maneuver street names and segment lengths, then selects the best candidate.

EXPLORE
Encourages lively, walkable streets and interesting areas. Costing is dynamically adjusted based on weather and time of day to avoid unpleasant or unsafe conditions.

ELEVATION
Minimizes elevation gain and steep slopes. Prefers Valhalla's own /height service for elevation data, with external fallback. Returns full elevation analytics alongside routing geometry.

BEST
Generates 5-7 candidate routes in parallel using different pedestrian costing presets. Each candidate is scored using weather, time of day, slope, distance, and safety heuristics. The highest-scoring route is returned.

LOOP
Generates round-trip walking loops optimized for a target distance. Attempts POI seeding first — finds real cafes, landmarks, or parks matching the loop theme via Overpass and routes through them. Falls back to geometric midpoint sampling if Overpass fails. Runs 3 parallel candidates and picks the one closest to the target distance.

Loop themes: scenic, explore, safe, coffee, food, landmark, history, parks

---

Route Enrichment

Enrichment is opt-in per request (enrich=true). It runs in parallel with elevation analysis and does not block the routing response if it fails.

Enrichment flow:

1. Compute bounding box from route coordinates
2. Check Overpass cache — return cached POIs if hit (1-hour TTL)
3. Query Overpass for landmarks, historic sites, cafes, restaurants, parks, and nature
4. Filter to POIs within 150m of the actual route line
5. Categorize and score each POI
6. Generate neighborhood flavor label (Coffee Culture, Foodie, Historic, Green, etc.)
7. Build highlight chips and narrative summary
8. Return structured enrichment block alongside route

Enrichment response includes:
- landmarks: historic sites, monuments, museums, viewpoints
- food: cafes, bakeries, restaurants, bars
- parks: green spaces along the route
- highlights: ready-to-display chips ("📍 Brooklyn Bridge", "☕ Balthazar")
- summary: deterministic narrative ("You'll pass Brooklyn Bridge. Balthazar is right along the route.")
- neighborhood_flavor: label, emoji, and description for the route character

---

Detour Economy

The /detours endpoint finds the most worthwhile things to step off your route for, with a quantified time cost per detour.

For each candidate POI within 500m of the route:
- Approximate extra walking time is computed (out-and-back at 5 km/h)
- Worth-it score = category importance / extra minutes
- Only POIs within category-specific time thresholds are included
- Results include a ready-to-display label: "+4 min · Brooklyn Bridge Park"

---

Walk Personas

The /persona endpoint returns a time-aware walk persona for a given location. Personas are computed from the current hour, weather, and night/day status. Deterministic and instant — no external API call at serve time.

Available personas: Morning Walk, Golden Hour Walk, Lunch Walk, After Work Walk, Night Walk, Rainy Day Walk, Cool Route Walk, City Walk

---

Walk Themes

The /themes endpoint returns the catalog of curated walk types available for loop generation.

Available themes: Coffee Shop Loop, Historic Walk, Green Loop, Food Discovery Loop, Landmark Loop, Scenic Loop, Explore Loop

Each theme includes a name, emoji, tagline, description, suggested duration, and tags for filtering.

---

Unexplored City

The /walks/analyze endpoint accepts a client's walk history (list of route coordinate arrays) and returns:
- Grid-cell-based street coverage statistics (~20m resolution)
- Coverage percentage of the surrounding area
- Total and unique distance walked
- Directional suggestions for unexplored areas nearby

No server-side user storage required. The iOS client holds walk history locally and sends it for analysis. The backend is stateless.

---

Turn-by-Turn and AR Support

For all routing modes, the backend provides:

- Full coordinate geometry for map rendering
- Simplified waypoints for AR navigation (aggressive reduction for anchor density control)
- Turn-by-turn instructions derived from Valhalla maneuvers
- Street names per maneuver step
- Distance and duration per step

---

Elevation Analysis

Elevation analysis is performed using a multi-source fallback pipeline to ensure robustness. The elevation routing mode queries Valhalla's own /height service first before falling back to external sources.

Elevation sources (in priority order):
1. Valhalla /height (where available)
2. OpenTopoData
3. ESRI World Elevation API
4. USGS Elevation (USA only)
5. Zero fallback for failure cases

Features:
- Batch fetching to respect API limits
- In-memory caching to reduce repeated calls
- Noise smoothing for realistic gain estimation
- Elevation gain and loss computation
- Slope calculation between consecutive points
- Walking-specific difficulty classification (Easy / Moderate / Hard / Very Hard)

Elevation is opt-in per request (elevation=false by default) to avoid adding latency to non-elevation routing modes.

---

Geocoding and Location Parsing

The backend accepts flexible location inputs, including:

- Free-text addresses
- Place and POI names
- Explicit latitude,longitude strings

Forward geocoding:
- Nominatim is used as the primary source
- Photon is used as a fast, unlimited fallback

Reverse geocoding:
- Nominatim reverse endpoint
- Returns human-readable location labels for UI display

Geocoding logic is resilient to rate limits and transient failures.

---

Vision Interpretation Endpoint

The /vision endpoint is designed to support AR hazard awareness.

Inputs:
- Object detections (from on-device vision models)
- User heading
- Distance to next turn

The endpoint applies conservative, rule-driven reasoning to identify only meaningful hazards and returns minimal, structured recommendations suitable for AR display. It is explicitly designed to avoid alarm fatigue and hallucinations.

Requires OPENAI_API_KEY. Returns 503 if not configured.

---

GPX Export and Import

Routes can be exported as GPX 1.1 files for offline use or external navigation tools.
GPX files can also be uploaded and parsed back into coordinates with elevation analysis.

Export features:
- Standards-compliant GPX output
- Compatible with Apple Maps, Garmin, Komoot, AllTrails
- Works for all routing modes including loop (no end coordinate required for loop)
- Generated directly from route geometry

Import features:
- Parses track points, route points, and waypoints
- Returns decoded coordinates and full elevation analysis

---

API Endpoints

GET /
Service health check

GET /autocomplete
Address and POI autocomplete. Fetches Photon and Nominatim in parallel. Falls back to Google Places for POI queries if GOOGLE_PLACES_API_KEY is set.
Parameters: q, user_lat, user_lon, limit

GET /route
Compute pedestrian routes with optional enrichment and elevation.
Parameters:
- start (required)
- end (required except loop mode)
- mode: shortest | safe | scenic | explore | elevation | best | loop
- duration: walk duration in minutes, used for loop distance (default 30)
- loop_theme: scenic | explore | safe | coffee | food | landmark | history | parks
- enrich: attach landmarks and food along the route (default false)
- elevation: attach full elevation profile (default false)

GET /detours
Find worthwhile detours along a route with quantified time cost.
Parameters: start, end, mode, max_detour_m, top_n

GET /persona
Return the current time-aware walk persona for a location.
Parameters: lat, lon

GET /themes
Return the themed walk catalog, optionally filtered by tag.
Parameters: tag

GET /themes/{theme_id}
Return a single theme by ID.

GET /nearby
Discover POIs near a coordinate.
Parameters: lat, lon, radius_m, category (all | food | landmark | park)

POST /walks/analyze
Analyze client walk history for coverage statistics and unexplored area suggestions.
Body: { routes, center_lat, center_lon, suggest_unexplored, radius_m }

GET /reverse_geocode
Convert coordinates to a human-readable address.
Parameters: coords (lat,lon)

GET /export_gpx
Export any route as a GPX file. Works for loop mode without an end coordinate.
Parameters: start, end, mode, duration, loop_theme, name

POST /import_gpx
Upload a GPX file and get back decoded coordinates and elevation analysis.

GET /places_search
Google Places text search for POIs near a location. Requires GOOGLE_PLACES_API_KEY.
Parameters: q, user_lat, user_lon

POST /vision
Interpret vision-based hazard signals for AR navigation. Requires OPENAI_API_KEY.
Body: { detections, heading, distance_to_next }

POST /loop_assistant
Convert a natural-language loop request into ranked, enriched loop options.
Body: { query, user_lat (optional), user_lon (optional), max_options (1–5, default 3) }

Accepts three query types:
- Station-based: "food loop from 14th Street", "create routes from 23rd St"
- Area-based: "scenic walk in SoHo", "generate a loop in East Village"
- Open-ended: "surprise me", "give me a good walk", "quick loop near me"

The assistant parses the query into a structured intent (theme, duration, location), resolves an
origin coordinate, generates candidates in parallel via the Valhalla routing stack, enriches each
with POI data, deduplicates near-identical routes, and returns ranked options. No LLM required.

Response:
- origin: resolved start point with label and origin_type (area / station / user_location / default)
- assistant_summary: one-line summary of results
- options[]: ranked loop options with title, subtitle, theme, duration_min, distance_miles,
  highlights, suggested_stops, neighborhood_character, why_this, and route_preview

---

Configuration

All configuration is driven by environment variables. Copy .env.example to .env.

Required:
- VALHALLA_URL — URL of the Valhalla routing instance

Optional:
- GOOGLE_PLACES_API_KEY — enables Google Places fallback in autocomplete and /places_search
- OPENAI_API_KEY — enables /vision endpoint
- OVERPASS_URL — Overpass API endpoint (defaults to public instance)
- OVERPASS_TIMEOUT — query timeout in seconds (default 6)
- ENRICHMENT_CORRIDOR_M — max POI distance from route in meters (default 150)
- VALHALLA_TIMEOUT — Valhalla request timeout in seconds (default 10)
- WALK_SPEED_KPH — used for loop duration-to-distance conversion (default 5.0)

---

Local Development

```bash
cp .env.example .env
# fill in VALHALLA_URL at minimum

pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8080
```

Interactive API docs available at http://localhost:8080/docs

---

Deployment Architecture

The WalkWithMe backend is a containerized FastAPI service designed to be deployment-agnostic.

Pedestrian routing is powered by a dedicated Valhalla instance running on a DigitalOcean droplet. Valhalla uses prebuilt, region-specific map tiles that are generated offline and persisted on disk. These tiles are not built dynamically at request time.

The backend communicates with Valhalla over HTTP and can be deployed independently of the routing engine.

This separation allows:
- Valhalla to remain stateful and tile-backed
- The backend API to remain stateless and horizontally scalable
- Flexible deployment of the backend across environments

```bash
docker build -t walkwithme-backend .
docker run -p 8080:8080 --env-file .env walkwithme-backend
```

---

Design Principles

- Pedestrian-first, not car-centric
- Discovery-driven, not just navigation
- Global operation without proprietary SDKs
- Graceful degradation — routing always returns even if enrichment fails
- Enrichment is additive and opt-in, never blocking
- Parallel execution wherever independent work allows
- Mobile-optimized JSON responses
- Designed to support AR navigation constraints
- No server-side user storage required for v1

---

Status

Active development

This backend powers the WalkWithMe iOS frontend and is intended to support future web, wearable, and AR-based navigation clients.
