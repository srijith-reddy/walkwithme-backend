# backend/main.py

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import rapidfuzz
import math
import os
import base64
import openai
import polyline

# ---------------------------
# ROUTING ENGINE (Valhalla)
# ---------------------------
from backend.routing import get_route

# GPX export
from backend.gpx.export_gpx import gpx_response

# Trails
from backend.trails.find_trails import find_nearby_trails
from backend.trails.trail_scorer import score_trails
from backend.trails.valhalla_trails import valhalla_trail_route

# Elevation analyzer
from backend.elevation import analyze_route_elevation

# Geocoding utilities
from backend.utils.geo import geocode, reverse_geocode, parse_location


# =============================================================
# CONFIG
# =============================================================
app = FastAPI(title="Walk With Me API — VALHALLA MODE")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

openai.api_key = os.getenv("OPENAI_API_KEY")

HEADERS = {"User-Agent": "WalkWithMe/1.0 (srijith-github)"}


@app.get("/")
def home():
    return {"message": "Walk With Me is running 🚶‍♂️ — VALHALLA MODE"}


# =============================================================
# Haversine + IP Bias
# =============================================================
def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2 +
        math.cos(math.radians(lat1)) *
        math.cos(math.radians(lat2)) *
        math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


def ip_bias(request: Request):
    try:
        ip = request.headers.get("x-forwarded-for") or request.client.host
        r = requests.get(f"https://ipapi.co/{ip}/json/", timeout=2).json()
        return float(r.get("latitude")), float(r.get("longitude"))
    except:
        return None, None


# =============================================================
# /autocomplete
# =============================================================
@app.get("/autocomplete")
def autocomplete(
    request: Request,
    q: str = Query(..., min_length=1),
    user_lat: float | None = None,
    user_lon: float | None = None,
    limit: int = 7
):
    q = q.strip()

    if user_lat is None or user_lon is None:
        user_lat, user_lon = ip_bias(request)

    geo_bias_enabled = user_lat is not None and user_lon is not None

    photon_results = []
    nominatim_results = []

    # Photon
    try:
        params = {"q": q, "limit": limit}
        if geo_bias_enabled:
            params["lat"] = user_lat
            params["lon"] = user_lon

        r = requests.get("https://photon.komoot.io/api/",
                         params=params, timeout=4).json()

        for f in r.get("features", []):
            props = f["properties"]
            label = ", ".join(x for x in [
                props.get("name"),
                props.get("street"),
                props.get("city"),
                props.get("state"),
                props.get("country")
            ] if x)

            lat = f["geometry"]["coordinates"][1]
            lon = f["geometry"]["coordinates"][0]

            photon_results.append({
                "label": label,
                "lat": lat,
                "lon": lon,
                "source": "photon"
            })
    except:
        pass

    # Nominatim
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": q, "format": "json", "limit": limit, "addressdetails": 1},
            headers={"User-Agent": "WalkWithMe/1.0"},
            timeout=4
        ).json()

        for item in r:
            nominatim_results.append({
                "label": item["display_name"],
                "lat": float(item["lat"]),
                "lon": float(item["lon"]),
                "source": "nominatim"
            })
    except:
        pass

    results = photon_results + nominatim_results

    ranked = []
    for o in results:
        score = rapidfuzz.fuzz.ratio(q.lower(), o["label"].lower())

        if geo_bias_enabled:
            dist = haversine(user_lat, user_lon, o["lat"], o["lon"])
            o["dist_km"] = dist

            if dist > 50 and score < 85:
                continue

            if dist < 10:
                score += 30

            score += max(0, 20 - dist)

        if o["source"] == "photon":
            score += 10

        o["score"] = score
        ranked.append(o)

    ranked.sort(key=lambda x: x["score"], reverse=True)

    return [
        {"label": o["label"], "lat": o["lat"], "lon": o["lon"]}
        for o in ranked[:limit]
    ]


# =============================================================
# /route — FINAL PRODUCTION VERSION
# =============================================================
@app.get("/route")
def route(start: str, end: str = None, mode: str = "shortest", duration: int = 20):

    lat1, lon1 = parse_location(start)

    end_tuple = None
    if end:
        lat2, lon2 = parse_location(end)
        end_tuple = (lat2, lon2)

    allowed = {"shortest", "safe", "scenic", "explore", "elevation", "best", "loop"}

    if mode not in allowed:
        raise HTTPException(400, f"Invalid mode '{mode}'")

    try:
        result = get_route((lat1, lon1), end_tuple, mode, duration)
    except Exception as e:
        raise HTTPException(500, f"Routing failed: {e}")

    # Ensure coordinates exist (decode polyline fallback)
    if "coordinates" not in result:
        if "coordinates_polyline" not in result:
            raise HTTPException(404, "Route not found")

        try:
            coords = polyline.decode(result["coordinates_polyline"], precision=6)
        except:
            raise HTTPException(500, "Polyline decode failed")

        result["coordinates"] = coords

    if not result["coordinates"]:
        raise HTTPException(404, "No coordinates generated")

    # Elevation analysis
    result["elevation"] = analyze_route_elevation(result["coordinates"])

    return result


# =============================================================
# /trails
# =============================================================
@app.get("/trails")
def trails(start: str, radius: int = 2000, limit: int = 5):
    lat, lon = parse_location(start)
    raw = find_nearby_trails(lat, lon, radius)
    if not raw:
        raise HTTPException(404, "No trails found")
    scored = score_trails(raw)
    return scored[:limit]


# =============================================================
# /trail_route
# =============================================================
@app.get("/trail_route")
def trail_route(start: str, end: str):
    lat1, lon1 = parse_location(start)
    lat2, lon2 = parse_location(end)
    result = valhalla_trail_route(lat1, lon1, lat2, lon2)
    if "error" in result:
        raise HTTPException(500, result["error"])
    return result


# =============================================================
# /reverse_geocode
# =============================================================
@app.get("/reverse_geocode")
def reverse_geocode_endpoint(coords: str):
    try:
        lat, lon = map(float, coords.split(","))
    except:
        raise HTTPException(400, "Invalid format. Use 'lat,lon'.")
    return {"address": reverse_geocode(lat, lon)}


# =============================================================
# /export_gpx
# =============================================================
@app.get("/export_gpx")
def export_gpx(start: str, end: str, mode: str = "shortest"):
    lat1, lon1 = parse_location(start)
    lat2, lon2 = parse_location(end)
    result = get_route((lat1, lon1), (lat2, lon2), mode)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return gpx_response(result["coordinates"])


# =============================================================
# /vision (unchanged)
# =============================================================
class VisionRequest(BaseModel):
    image_b64: str
    detections: list
    heading: float | None = None
    distance_to_next: float | None = None


@app.post("/vision")
async def vision(payload: VisionRequest):

    system_prompt = """
You are WALKR AR Vision — a real-time safety assistant for walking navigation.

You analyze:
- YOLO detections
- Camera frame
- User heading
- Distance to the next navigation step

Your job:
1. Identify **only meaningful hazards**.
2. Ignore harmless items (parked cars, distant people, objects far from path).
3. Warn ONLY when something may affect user safety or navigation.
4. Never hallucinate objects not in YOLO detections.
5. Always stay calm, minimal, and factual.

Rules:
- DO NOT warn about:
    - people who are not in the user's direct walking path
    - parked cars unless blocking sidewalk
    - bikes or cars that are stationary and far away
    - unrelated objects (bags, signs, poles unless blocking path)
- Warn ONLY IF:
    - something is blocking the sidewalk
    - a moving car/bike is approaching
    - a person is directly in path
    - an intersection/crossing is ahead
    - visibility is poor
- Keep descriptions focused and short.
- Never guess age, gender, race, or identity.
- For people, just say "people".
- If uncertain, say "uncertain".

Respond ONLY in this JSON structure:

{
  "hazards": [],
  "path_status": "",
  "recommendation": ""
}

Where:
- hazards: ONLY real risks (e.g., "bike approaching", "sidewalk blocked").
- path_status: "clear", "partially blocked", "obstructed", or "uncertain".
- recommendation: brief, non-intrusive guidance ("continue", "slow down", "shift right").
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text",
                 "text": f"""
YOLO detections: {payload.detections}
Heading: {payload.heading}
Distance: {payload.distance_to_next}
"""
                },
                {"type": "image_url",
                 "image_url": {
                     "url": f"data:image/jpeg;base64,{payload.image_b64}"
                 }},
            ]
        }
    ]

    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=300,
            temperature=0.1,
        )
        text = resp.choices[0].message["content"]
        return {"ok": True, "analysis": text}

    except Exception as e:
        raise HTTPException(500, f"Vision failed: {e}")
