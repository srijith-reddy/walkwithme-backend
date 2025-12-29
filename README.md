# WalkWithMe Backend — Pedestrian Routing, Trails, Elevation, and AI Scoring

This repository contains the backend API for WalkWithMe, a pedestrian-first navigation system designed to support AR walking, safety-aware routing, scenic and exploratory paths, trail discovery, elevation analysis, and GPX export.

The backend is built around Valhalla as the core routing engine and extends it with custom logic for pedestrian-specific costing, trail extraction, elevation analytics, geocoding, and AI-style route ranking. It is intentionally frontend-agnostic and serves both AR navigation clients and traditional map-based interfaces.

The system is designed to work globally, without reliance on proprietary map SDKs or region-specific datasets.

---

System Responsibilities

The backend is responsible for:

- Computing pedestrian routes optimized for different intents
- Ranking routes based on safety, scenery, elevation, and context
- Discovering real walkable trails near a user
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

Routing Core
- Unified routing dispatcher in backend/routing.py
- Mode-specific routing logic split by intent
- Valhalla as the underlying graph and path engine

Analytics and Scoring
- Elevation analysis
- Scenic, safety, and greenery scoring
- Weather and time-of-day awareness
- AI-style candidate evaluation

Supporting Systems
- Geocoding and reverse geocoding
- Trail extraction and scoring
- GPX export
- Vision interpretation endpoint

---

Routing Architecture

Valhalla is used as the underlying pedestrian routing engine. All routing modes ultimately call Valhalla, but with different costing profiles, candidate generation strategies, and post-processing steps.

Routing flow:

1. Parse input locations (text or coordinates)
2. Generate one or more candidate routes via Valhalla
3. Decode geometry (polyline6)
4. Extract turn-by-turn maneuvers
5. Simplify geometry for AR usage
6. Apply scoring or ranking logic
7. Return structured JSON suitable for mobile clients

The routing dispatcher (backend/routing.py) acts as a single entry point and delegates to mode-specific implementations.

---

Routing Modes

SHORTEST  
Uses Valhalla pedestrian routing with minimal customization. Intended for efficiency and baseline comparisons.

SAFE  
Adjusts pedestrian costing based on time of day. During night hours, it strongly prioritizes lit roads, avoids alleys, and increases safety weighting. Designed for real-world walking safety rather than shortest distance.

SCENIC  
Biases routes toward greenery, parks, waterfronts, and low-density streets. Uses Valhalla edge metadata to compute green, water, and scenic scores, then selects the most scenic candidate.

EXPLORE  
Encourages lively, walkable streets and interesting areas. Costing is dynamically adjusted based on weather and time of day to avoid unpleasant or unsafe conditions.

ELEVATION 
Minimizes elevation gain and steep slopes. In addition to routing, it performs full elevation analysis and returns gain, loss, slope profile, and walking-specific difficulty classification.

BEST  
Generates multiple candidate routes using different pedestrian costing presets. Each candidate is scored using weather, time of day, slope, distance, and safety heuristics. The highest-scoring route is returned.

LOOP  
Generates round-trip walking routes optimized for a target distance. Uses directional sampling and candidate scoring to produce a loop suitable for exercise or casual walks.

---

Turn-by-Turn and AR Support

For all routing modes, the backend provides:

- Full coordinate geometry for map rendering
- Simplified waypoints for AR navigation
- Turn-by-turn instructions derived from Valhalla maneuvers
- Next-turn metadata for HUD display

Waypoint simplification is intentionally aggressive to reduce AR anchor density and improve runtime stability on mobile devices.

---

Elevation Analysis

Elevation analysis is performed using a multi-source fallback pipeline to ensure robustness.

Elevation sources (in priority order):
1. OpenTopoData
2. ESRI World Elevation API
3. USGS Elevation (USA only)
4. Zero fallback for failure cases

Features:
- Batch fetching to respect API limits
- In-memory caching to reduce repeated calls
- Noise smoothing for realistic gain estimation
- Elevation gain and loss computation
- Slope calculation between consecutive points
- Walking-specific difficulty classification

Elevation analytics are returned inline with routing responses where applicable.

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

---

GPX Export

Routes can be exported as GPX 1.1 files for offline use or external navigation tools.

Features:
- Standards-compliant GPX output
- Compatible with Apple Maps, Garmin, Komoot, AllTrails
- Generated directly from route geometry
- Includes route metadata and track name

---

API Endpoints

GET /
Service health check

GET /autocomplete
Address and POI autocomplete with optional geographic bias

GET /route
Compute pedestrian routes
Parameters:
- start
- end (optional for loop mode)
- mode
- duration (for loop mode)

GET /trails
Discover nearby walkable trails

GET /trail_route
Compute a route between two trail points

GET /reverse_geocode
Convert coordinates to a human-readable address

GET /export_gpx
Export a route as a GPX file

POST /vision
Interpret vision-based hazard signals for AR navigation

---

Deployment

The backend is containerized using Docker:

- Python 3.11 slim base image
- GEOS and spatial dependencies installed
- FastAPI served via Uvicorn on port 8080

Valhalla is expected to run as a separate service and is accessed via HTTP.

---

Design Principles

- Pedestrian-first, not car-centric
- Global operation without proprietary SDKs
- Graceful degradation and fallbacks
- Clear separation of routing, analytics, and presentation
- Mobile-optimized JSON responses
- Designed to support AR navigation constraints

---

Status

Active development

This backend powers the WalkWithMe iOS frontend and is intended to support future web, wearable, and AR-based navigation clients.

