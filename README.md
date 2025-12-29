# WalkWithMe Backend — Pedestrian Routing, Trails, Elevation, and AI Scoring

This repository contains the backend API for WalkWithMe, a pedestrian-first navigation system designed to support AR walking, scenic routing, safety-aware paths, trail discovery, elevation analysis, and GPX export.

The backend is built around Valhalla as the core routing engine, augmented with geocoding, elevation services, trail extraction, and AI-style scoring layers. It is designed to be frontend-agnostic and serves both AR navigation and traditional map-based navigation clients.

---

High-Level Responsibilities

- Pedestrian routing using Valhalla
- Multiple routing modes (shortest, safe, scenic, explore, elevation, best, loop)
- Trail discovery within walking radius
- Elevation profiling and difficulty estimation
- GPX export for offline or external navigation tools
- Address search, autocomplete, and reverse geocoding
- AI-assisted route ranking and hazard interpretation
- JSON-first API designed for mobile clients

---

Core Architecture

FastAPI application
- Entry point: backend/main.py
- Stateless HTTP API
- CORS enabled for mobile and web clients

Routing layer
- Central dispatcher: backend/routing.py
- Valhalla client wrapper: backend/valhalla_client.py
- Mode-specific routing implementations:
  - shortest
  - safe (day/night aware)
  - scenic
  - explore
  - elevation
  - best (AI-ranked)
  - loop (round-trip routes)

Trail system
- Isochrone-based trail discovery using Valhalla
- Edge extraction via trace_attributes
- Trail scoring based on length, elevation, surface, safety, and scenery

Elevation system
- Multi-source elevation fetching
- Caching and batching
- Gain, loss, slope, and difficulty classification

Geocoding system
- Forward geocoding via Nominatim with Photon fallback
- Reverse geocoding via Nominatim
- Input parsing for coordinates or free-text locations

AI and scoring
- Rule-based scoring for safety, scenic value, greenery, and water proximity
- Weather-aware and time-of-day–aware route ranking
- LLM-powered vision interpretation endpoint (used by AR frontend)

---

API Endpoints

GET /
Health check

GET /autocomplete
Address and POI autocomplete with optional geo-bias

GET /route
Compute a pedestrian route
Parameters:
- start
- end (optional for loop)
- mode: shortest | safe | scenic | explore | elevation | best | loop
- duration (for loop)

GET /trails
Discover nearby walkable trails
Parameters:
- start
- radius
- limit

GET /trail_route
Compute a route between two trail points

GET /reverse_geocode
Convert coordinates to a human-readable address

GET /export_gpx
Export a route as a GPX file

POST /vision
LLM-based interpretation of detected hazards for AR navigation

---

Routing Modes Explained

shortest
- Pure Valhalla pedestrian routing
- Minimal customization

safe
- Day/night aware pedestrian costing
- Prioritizes lit roads and safety factors

scenic
- Biases routes toward parks, greenery, and waterfronts
- Uses Valhalla metadata for green and water scoring

explore
- Encourages lively streets and walkable areas
- Weather- and time-aware costing

elevation
- Minimizes elevation gain
- Returns full elevation analytics

best
- Evaluates multiple candidate routes
- Scores them using weather, time, slope, and length
- Returns the highest-ranked route

loop
- Generates round-trip walking routes
- Optimized for target distance

---

Trail Discovery System

Trail discovery uses a multi-step process:
1. Generate a pedestrian isochrone using Valhalla
2. Extract all walkable edges within the polygon
3. Filter to footpaths, trails, sidewalks, and tracks
4. Compute elevation gain and distance
5. Score difficulty, scenic value, and safety
6. Return iOS-ready trail objects with geometry and metadata

This avoids reliance on third-party trail datasets and works globally.

---

Elevation Analysis

Elevation data is fetched using a prioritized fallback chain:
1. OpenTopoData
2. ESRI Elevation API
3. USGS (USA only)
4. Zero fallback

Features:
- Batch fetching with caching
- Noise smoothing
- Elevation gain and loss
- Slope calculation
- Walking-specific difficulty classification

---

GPX Export

Routes can be exported as standard GPX 1.1 files:
- Compatible with Apple Maps, Garmin, AllTrails, Komoot
- Includes track name and geometry
- Generated directly from route coordinates

---

Geocoding and Location Parsing

Inputs accepted:
- Free-text addresses
- POI names
- Lat,lon coordinate strings

Forward geocoding:
- Nominatim (primary)
- Photon (fallback)

Reverse geocoding:
- Nominatim reverse endpoint

---

Vision Endpoint

The /vision endpoint processes:
- Object detections
- User heading
- Distance to next turn

It returns minimal, safety-focused recommendations intended for AR display. The endpoint is designed to be conservative and non-alarming.

---

Deployment

Docker-based deployment
- Python 3.11 slim image
- GEOS and spatial dependencies installed
- FastAPI served via Uvicorn on port 8080

Valhalla is expected to run as a separate service.

---

Design Principles

- Pedestrian-first routing
- Global coverage
- No dependency on proprietary map SDKs
- Graceful fallbacks at every layer
- JSON outputs optimized for mobile and AR clients
- Clear separation between routing, scoring, and presentation

---

Status

Active development

This backend powers the WalkWithMe iOS frontend and is designed to support future web and wearable clients.
