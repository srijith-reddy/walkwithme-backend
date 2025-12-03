# backend/main.py

from fastapi import FastAPI, HTTPException, Query, Request, UploadFile, File
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

# GPX import
from backend.gpx.import_gpx import import_gpx

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

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "YOUR_API_KEY_HERE")


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
# GOOGLE PLACES SEARCH (NEW)
# =============================================================
def places_text_search(query: str, lat: float, lon: float):
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"

    params = {
        "query": query,
        "location": f"{lat},{lon}",
        "radius": 3000,
        "key": GOOGLE_PLACES_API_KEY
    }

    try:
        r = requests.get(url, params=params, timeout=5).json()
    except Exception as e:
        raise HTTPException(500, f"Google Places failed: {e}")

    results = []
    for place in r.get("results", []):
        loc = place["geometry"]["location"]
        p_lat = loc["lat"]
        p_lon = loc["lng"]

        results.append({
            "name": place.get("name"),
            "address": place.get("formatted_address"),
            "rating": place.get("rating"),
            "reviews": place.get("user_ratings_total"),
            "lat": p_lat,
            "lon": p_lon,
            "open_now": place.get("opening_hours", {}).get("open_now"),
            "distance_km": round(haversine(lat, lon, p_lat, p_lon), 3)
        })

    return results


# =============================================================
# /places_search (NEW ENDPOINT)
# =============================================================
@app.get("/places_search")
def places_search(
    request: Request,
    q: str = Query(..., min_length=1),
    user_lat: float | None = None,
    user_lon: float | None = None
):
    if user_lat is None or user_lon is None:
        user_lat, user_lon = ip_bias(request)

    if user_lat is None or user_lon is None:
        raise HTTPException(400, "Missing user location.")

    results = places_text_search(q, user_lat, user_lon)

    return {
        "query": q,
        "count": len(results),
        "results": results
    }

# =============================================================
# /autocomplete — SMART (OSM first, Google fallback)
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

    # ----------------------------------------
    # 1. Detect if query is a PLACE/POI search
    # ----------------------------------------
    # Heuristics:
    # - No street number
    # - Contains POI keywords
    # - Multi-word query that isn't address-like
    # - Looks like “cafe near me”
    # ----------------------------------------
    poi_keywords = [
        "cafe", "coffee", "restaurant", "food", "pizza", "thai",
        "gym", "park", "museum", "mall", "atm", "hotel",
        "bar", "burger", "boba", "tea", "pharmacy", "clinic",
        "movie", "cinema", "theatre", "store", "shop"
    ]

    looks_like_address = any(char.isdigit() for char in q)
    looks_like_poi = (
        any(k in q.lower() for k in poi_keywords) or
        "near me" in q.lower()
    )

    # ----------------------------------------
    # Use user location bias
    # ----------------------------------------
    if user_lat is None or user_lon is None:
        user_lat, user_lon = ip_bias(request)

    geo_bias_enabled = user_lat is not None and user_lon is not None

    # ----------------------------------------
    # 2. First try OSM: Photon + Nominatim (FREE)
    # ----------------------------------------
    photon_results = []
    nominatim_results = []

    # ----- PHOTON -----
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

    # ----- NOMINATIM -----
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

    osm_results = photon_results + nominatim_results
    
    # DEBUG: Print OSM result count
    print(f"[AUTOCOMPLETE] OSM returned {len(osm_results)} results for '{q}'")
    # ----------------------------------------------------------
    # TRIGGER GOOGLE ONLY IF OSM FAILS
    # ----------------------------------------------------------
    should_use_google = False

    # Count OSM results
    osm_count = len(osm_results)
    print(f"[AUTOCOMPLETE] OSM returned {osm_count} results for '{q}'")

    # 1. If user hasn't typed enough, NEVER trigger Google
    if len(q) < 4:
        print(f"[AUTOCOMPLETE] Google NOT triggered — query too short ('{q}')")
        should_use_google = False

    # 2. If OSM returned **zero**, trigger Google
    elif osm_count == 0:
        should_use_google = True
        print(f"⚠️ [AUTOCOMPLETE] GOOGLE TRIGGERED — OSM empty for '{q}'")

    # 3. If POI-like query (ex: 'cafes near me', 'pizza', 'restaurant')
    elif looks_like_poi:
        should_use_google = True
        print(f"⚠️ [AUTOCOMPLETE] GOOGLE TRIGGERED — POI query detected ('{q}')")

    # 4. Otherwise keep OSM only
    else:
        best_osm_score = max(
            rapidfuzz.fuzz.ratio(q.lower(), o["label"].lower())
            for o in osm_results
        )
        print(f"[AUTOCOMPLETE] Google NOT triggered for '{q}' (best_osm_score={best_osm_score})")



    # ----------------------------------------
    # 4. Google Places Text Search (PAID)
    # ----------------------------------------
    google_results = []

    if should_use_google:
        try:
            GOOGLE_KEY = os.getenv("GOOGLE_PLACES_API_KEY")
            if GOOGLE_KEY:
                params = {
                    "query": q,
                    "key": GOOGLE_KEY
                }
                if geo_bias_enabled:
                    params["location"] = f"{user_lat},{user_lon}"
                    params["radius"] = 1500

                gr = requests.get(
                    "https://maps.googleapis.com/maps/api/place/textsearch/json",
                    params=params,
                    timeout=4
                ).json()

                for p in gr.get("results", []):
                    google_results.append({
                        "label": p.get("name"),
                        "lat": p["geometry"]["location"]["lat"],
                        "lon": p["geometry"]["location"]["lng"],
                        "source": "google"
                    })
        except Exception as e:
            print("Google Places error:", e)

    # ----------------------------------------
    # 5. Merge results → rank by similarity + distance
    # ----------------------------------------
    results = osm_results + google_results

    ranked = []
    for o in results:
        score = rapidfuzz.fuzz.ratio(q.lower(), o["label"].lower())

        if geo_bias_enabled:
            dist = haversine(user_lat, user_lon, o["lat"], o["lon"])
            o["dist_km"] = dist

            # Very far + low match → drop
            if dist > 50 and score < 85:
                continue

            # Nearby places get boost
            if dist < 10:
                score += 30

            score += max(0, 20 - dist)

        # Photon gets small boost
        if o["source"] == "photon":
            score += 10

        ranked.append({**o, "score": score})

    ranked.sort(key=lambda x: x["score"], reverse=True)

    # ----------------------------------------
    # 6. Final return shape (same as before)
    # ----------------------------------------
    return [
        {"label": o["label"], "lat": o["lat"], "lon": o["lon"]}
        for o in ranked[:limit]
    ]


# =============================================================
# /route — FINAL PRODUCTION VERSION (unchanged)
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
# /reverse_geocode (unchanged)
# =============================================================
@app.get("/reverse_geocode")
def reverse_geocode_endpoint(coords: str):
    try:
        lat, lon = map(float, coords.split(","))
    except:
        raise HTTPException(400, "Invalid format. Use 'lat,lon'.")
    return {"address": reverse_geocode(lat, lon)}


# =============================================================
# /import_gpx — upload GPX → coords + elevation
# =============================================================
@app.post("/import_gpx")
async def import_gpx_endpoint(file: UploadFile = File(...)):
    """
    Upload a GPX file and get back:
    - decoded coordinates [(lat, lon)]
    - basic elevation analysis (same shape as /route["elevation"])
    """

    coords = await import_gpx(file)

    if not coords:
        raise HTTPException(400, "No coordinates found in GPX file.")

    elevation = analyze_route_elevation(coords)

    return {
        "points": len(coords),
        "coordinates": coords,
        "elevation": elevation
    }

# =============================================================
# /vision — NO IMAGE VERSION (YOLO ONLY)
# =============================================================
class VisionRequest(BaseModel):
    detections: list
    heading: float | None = None
    distance_to_next: float | None = None


@app.post("/vision")
async def vision(payload: VisionRequest):

    system_prompt = """
You are WALKR AR Vision — a real-time safety assistant for walking navigation.

You analyze:
- YOLO detections (object + bbox + confidences)
- User heading
- Distance to next navigation step

CRITICAL HAZARD LABEL RULES:
- The "hazards" array MUST contain ONLY raw object labels:
      ["person", "car", "bike", "truck", "bus", "dog"]
- DO NOT include descriptions in "hazards".
- DO NOT invent hazards not present in YOLO.
- "hazards" is used ONLY for AR overlay fusion.

SEMANTICS GO INTO:
- "path_status"
- "recommendation"

Examples:
    hazards: ["person"]
    path_status: "partially blocked"
    recommendation: "person ahead, slow down"

WARN ONLY IF:
- sidewalk blocked
- a moving bike or car is approaching
- a person is directly in walking path
- intersection or crossing ahead
- visibility or path clarity is poor

DO NOT WARN ABOUT:
- parked cars (unless blocking)
- people far away / not in path
- stationary vehicles not affecting user
- irrelevant objects like poles, signs, bags

NEVER infer gender, age, race, identity.

Respond ONLY in this JSON:

{
  "hazards": [],
  "path_status": "",
  "recommendation": ""
}

Where:
- hazards: ONLY the YOLO-style object labels at risk ("person", "car", etc.)
- path_status: "clear", "partially blocked", "obstructed", or "uncertain"
- recommendation: short guidance ("continue", "slow down", "shift right")
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": f"""
YOLO detections: {payload.detections}
Heading: {payload.heading}
Distance: {payload.distance_to_next}
"""
        }
    ]

    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=200,
            temperature=0.1,
        )
        text = resp.choices[0].message["content"]
        return {"ok": True, "analysis": text}

    except Exception as e:
        raise HTTPException(500, f"Vision failed: {e}")
