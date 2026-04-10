# backend/main.py

import math
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

import polyline
import rapidfuzz
import requests
from fastapi import FastAPI, HTTPException, Query, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from backend.config import GOOGLE_PLACES_API_KEY, OPENAI_API_KEY
from backend.routing import get_route, ALLOWED_MODES
from backend.gpx.import_gpx import import_gpx
from backend.elevation import analyze_route_elevation
from backend.enrichment import enrich_route, find_nearby
from backend.detours import compute_detours
from backend.personas import get_persona_for_location, get_persona
from backend.themes import get_all_themes, get_theme, get_themes_by_tag
from backend.walks import analyze_coverage, suggest_unexplored
from backend.cache import route_cache, route_key
from backend.utils.geo import parse_location, reverse_geocode

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("walkwithme")

app = FastAPI(title="WalkWithMe API", version="3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

HEADERS = {"User-Agent": "WalkWithMe/3.0"}

# Modes that produce deterministic results — safe to cache
_CACHEABLE_MODES = {"shortest", "scenic", "safe", "explore", "elevation"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(max(0.0, a)))


def _ip_bias(request: Request) -> tuple[float | None, float | None]:
    try:
        ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if not ip:
            ip = request.client.host
        r = requests.get(f"https://ipapi.co/{ip}/json/", timeout=2).json()
        return float(r["latitude"]), float(r["longitude"])
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------
@app.get("/")
def health():
    return {"status": "ok", "service": "WalkWithMe API", "version": "3.0"}


# ---------------------------------------------------------------------------
# GET /autocomplete
# ---------------------------------------------------------------------------
@app.get("/autocomplete")
def autocomplete(
    request: Request,
    q: str = Query(..., min_length=1),
    user_lat: float | None = None,
    user_lon: float | None = None,
    limit: int = Query(default=7, ge=1, le=20),
):
    q = q.strip()
    poi_kw = {"cafe","coffee","restaurant","food","pizza","thai","gym","park","museum",
              "mall","hotel","bar","burger","boba","bakery","dessert","ramen","sushi"}
    looks_like_poi = any(k in q.lower() for k in poi_kw) or "near me" in q.lower()

    if user_lat is None or user_lon is None:
        user_lat, user_lon = _ip_bias(request)
    geo_bias = user_lat is not None and user_lon is not None

    def fetch_photon():
        try:
            params = {"q": q, "limit": limit}
            if geo_bias:
                params.update({"lat": user_lat, "lon": user_lon})
            r = requests.get("https://photon.komoot.io/api/", params=params, timeout=4).json()
            out = []
            for f in r.get("features", []):
                props = f["properties"]
                label = ", ".join(x for x in [
                    props.get("name"), props.get("street"),
                    props.get("city"), props.get("state"), props.get("country"),
                ] if x)
                coords = f["geometry"]["coordinates"]
                out.append({"label": label, "lat": coords[1], "lon": coords[0], "source": "photon"})
            return out
        except Exception:
            return []

    def fetch_nominatim():
        try:
            r = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": q, "format": "json", "limit": limit, "addressdetails": 1},
                headers=HEADERS, timeout=4,
            ).json()
            return [{"label": i["display_name"], "lat": float(i["lat"]),
                     "lon": float(i["lon"]), "source": "nominatim"} for i in r]
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=2) as ex:
        photon = ex.submit(fetch_photon).result()
        nominatim = ex.submit(fetch_nominatim).result()

    osm = photon + nominatim
    logger.info("autocomplete: %d OSM results for '%s'", len(osm), q)

    google = []
    if len(q) >= 4 and GOOGLE_PLACES_API_KEY and (not osm or looks_like_poi):
        try:
            params = {"query": q, "key": GOOGLE_PLACES_API_KEY}
            if geo_bias:
                params.update({"location": f"{user_lat},{user_lon}", "radius": 1500})
            gr = requests.get(
                "https://maps.googleapis.com/maps/api/place/textsearch/json",
                params=params, timeout=4,
            ).json()
            for p in gr.get("results", []):
                google.append({"label": p.get("name"),
                               "lat": p["geometry"]["location"]["lat"],
                               "lon": p["geometry"]["location"]["lng"],
                               "source": "google"})
        except Exception as e:
            logger.warning("Google Places error: %s", e)

    ranked = []
    for o in osm + google:
        score = rapidfuzz.fuzz.ratio(q.lower(), o["label"].lower())
        if geo_bias:
            dist = _haversine(user_lat, user_lon, o["lat"], o["lon"])
            if dist > 50 and score < 85:
                continue
            score += max(0, 20 - dist)
            if dist < 10:
                score += 30
        if o["source"] == "photon":
            score += 10
        ranked.append({**o, "_score": score})

    ranked.sort(key=lambda x: x["_score"], reverse=True)
    return [{"label": o["label"], "lat": o["lat"], "lon": o["lon"]} for o in ranked[:limit]]


# ---------------------------------------------------------------------------
# GET /route
# ---------------------------------------------------------------------------
@app.get("/route")
def route(
    start: str,
    end: str = None,
    mode: str = Query(default="shortest"),
    duration: int = Query(default=30, ge=5, le=300),
    loop_theme: str = Query(default="scenic"),
    enrich: bool = Query(default=False, description="Attach landmarks and food along the route"),
    elevation: bool = Query(default=False, description="Attach full elevation profile"),
):
    if mode not in ALLOWED_MODES:
        raise HTTPException(400, f"Invalid mode. Allowed: {', '.join(sorted(ALLOWED_MODES))}")

    try:
        lat1, lon1 = parse_location(start)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"Could not parse start: {e}")

    end_tuple = None
    if end:
        try:
            lat2, lon2 = parse_location(end)
            end_tuple = (lat2, lon2)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400, f"Could not parse end: {e}")

    if mode != "loop" and end_tuple is None:
        raise HTTPException(400, "'end' is required for non-loop routes.")

    # Route cache for deterministic modes
    ckey = route_key((lat1, lon1), end_tuple, mode) if mode in _CACHEABLE_MODES else None
    if ckey:
        cached = route_cache.get(ckey)
        if cached is not None:
            logger.info("route cache hit: %s", ckey)
            result = cached
        else:
            result = _do_route(lat1, lon1, end_tuple, mode, duration, loop_theme)
            if "error" not in result:
                route_cache.set(ckey, result)
    else:
        result = _do_route(lat1, lon1, end_tuple, mode, duration, loop_theme)

    if "error" in result:
        raise HTTPException(404, result["error"])

    coords = result.get("coordinates", [])
    if not coords:
        raise HTTPException(404, "No route coordinates returned.")

    # Enrichment + elevation in parallel
    def do_enrich():
        return enrich_route(coords) if enrich else None

    def do_elev():
        return analyze_route_elevation(coords) if elevation else None

    with ThreadPoolExecutor(max_workers=2) as ex:
        enrichment_data = ex.submit(do_enrich).result()
        elevation_data = ex.submit(do_elev).result()

    if enrichment_data is not None:
        result["enrichment"] = enrichment_data
    if elevation_data is not None:
        result["elevation"] = elevation_data

    return result


def _do_route(lat1, lon1, end_tuple, mode, duration, loop_theme):
    try:
        return get_route(
            (lat1, lon1), end_tuple,
            mode=mode, duration_minutes=duration, loop_theme=loop_theme,
        )
    except Exception as e:
        logger.exception("Routing error")
        raise HTTPException(500, f"Routing failed: {e}")


# ---------------------------------------------------------------------------
# GET /detours — worthy detours along a route
# ---------------------------------------------------------------------------
@app.get("/detours")
def detours(
    start: str,
    end: str,
    mode: str = Query(default="shortest"),
    max_detour_m: int = Query(default=400, ge=50, le=1000),
    top_n: int = Query(default=3, ge=1, le=5),
):
    """
    Compute the most worthwhile detours along a route.
    Returns: [{name, emoji, extra_minutes, worth_it_score, label, ...}]

    label is ready-to-display: "+4 min · Brooklyn Bridge Park"
    """
    try:
        lat1, lon1 = parse_location(start)
        lat2, lon2 = parse_location(end)
    except Exception as e:
        raise HTTPException(400, str(e))

    result = get_route((lat1, lon1), (lat2, lon2), mode=mode)
    if "error" in result:
        raise HTTPException(404, result["error"])

    coords = result.get("coordinates", [])
    if not coords:
        raise HTTPException(404, "No coordinates.")

    detour_list = compute_detours(coords, max_detour_m=max_detour_m, top_n=top_n)

    return {
        "mode": mode,
        "distance_m": result.get("distance_m"),
        "duration_s": result.get("duration_s"),
        "detour_count": len(detour_list),
        "detours": detour_list,
    }


# ---------------------------------------------------------------------------
# GET /persona — time-aware walk persona for a location
# ---------------------------------------------------------------------------
@app.get("/persona")
def persona(lat: float, lon: float):
    """
    Returns the current walk persona for (lat, lon) based on time + weather.
    Use to set the mood of the home screen or route card.
    """
    p = get_persona_for_location(lat, lon)
    return p


# ---------------------------------------------------------------------------
# GET /themes — available themed walk types
# ---------------------------------------------------------------------------
@app.get("/themes")
def themes(tag: str | None = None):
    """
    Returns all available walk themes, optionally filtered by tag.
    Tags: morning, food, cultural, scenic, explore, nature, etc.
    """
    if tag:
        result = get_themes_by_tag(tag)
    else:
        result = get_all_themes()
    return {"count": len(result), "themes": result}


@app.get("/themes/{theme_id}")
def theme_detail(theme_id: str):
    t = get_theme(theme_id)
    if not t:
        raise HTTPException(404, f"Theme '{theme_id}' not found.")
    return t


# ---------------------------------------------------------------------------
# GET /nearby
# ---------------------------------------------------------------------------
@app.get("/nearby")
def nearby(
    lat: float,
    lon: float,
    radius_m: int = Query(default=400, ge=50, le=2000),
    category: str = Query(default="all"),
):
    allowed = {"all", "food", "landmark", "park"}
    if category not in allowed:
        raise HTTPException(400, f"category must be one of: {', '.join(sorted(allowed))}")
    pois = find_nearby(lat, lon, radius_m=radius_m, category=category)
    return {"lat": lat, "lon": lon, "radius_m": radius_m,
            "category": category, "count": len(pois), "results": pois}


# ---------------------------------------------------------------------------
# POST /walks/analyze — unexplored city coverage
# ---------------------------------------------------------------------------
class WalkHistoryRequest(BaseModel):
    routes: list[list[list[float]]]   # list of routes, each a list of [lat, lon]
    center_lat: float | None = None
    center_lon: float | None = None
    city_bbox: dict | None = None
    suggest_unexplored: bool = True
    radius_m: int = 1500


@app.post("/walks/analyze")
def analyze_walks(payload: WalkHistoryRequest):
    """
    Client sends walked route history → backend returns coverage stats + unexplored suggestions.

    No server-side storage — the iOS app holds the walked routes and sends them each time.
    When you add user accounts, this endpoint becomes stateful.

    routes: [[[lat, lon], [lat, lon], ...], ...]  — each route is a list of coordinates
    """
    # Convert [[lat, lon], ...] → [(lat, lon), ...]
    walked = [
        [(pt[0], pt[1]) for pt in route if len(pt) >= 2]
        for route in payload.routes
        if len(route) >= 2
    ]

    coverage = analyze_coverage(walked, city_bbox=payload.city_bbox)

    suggestions = []
    if payload.suggest_unexplored and payload.center_lat and payload.center_lon:
        suggestions = suggest_unexplored(
            walked,
            center_lat=payload.center_lat,
            center_lon=payload.center_lon,
            radius_m=payload.radius_m,
        )

    insight = _coverage_insight(coverage["coverage_pct"], coverage["route_count"])

    return {
        "coverage": coverage,
        "insight": insight,
        "unexplored_suggestions": suggestions,
    }


def _coverage_insight(pct: float, route_count: int) -> str:
    if route_count == 0:
        return "Start your first walk to begin mapping your city."
    if pct < 1:
        return f"You've scratched the surface — {pct}% of the area explored. There's a whole city out there."
    if pct < 5:
        return f"{pct}% explored. You're becoming a regular. Keep going."
    if pct < 15:
        return f"{pct}% of this area is yours. Most people never walk this much of their city."
    if pct < 30:
        return f"{pct}% explored. You know these streets better than most people ever will."
    return f"{pct}% covered. You basically live outside."


# ---------------------------------------------------------------------------
# GET /places_search
# ---------------------------------------------------------------------------
@app.get("/places_search")
def places_search(
    request: Request,
    q: str = Query(..., min_length=1),
    user_lat: float | None = None,
    user_lon: float | None = None,
):
    if not GOOGLE_PLACES_API_KEY:
        raise HTTPException(503, "Google Places not configured.")
    if user_lat is None or user_lon is None:
        user_lat, user_lon = _ip_bias(request)
    if user_lat is None or user_lon is None:
        raise HTTPException(400, "Missing user location.")

    try:
        r = requests.get(
            "https://maps.googleapis.com/maps/api/place/textsearch/json",
            params={"query": q, "location": f"{user_lat},{user_lon}",
                    "radius": 3000, "key": GOOGLE_PLACES_API_KEY},
            timeout=5,
        ).json()
    except Exception as e:
        raise HTTPException(500, f"Google Places failed: {e}")

    results = []
    for place in r.get("results", []):
        loc = place["geometry"]["location"]
        p_lat, p_lon = loc["lat"], loc["lng"]
        results.append({
            "name": place.get("name"),
            "address": place.get("formatted_address"),
            "rating": place.get("rating"),
            "review_count": place.get("user_ratings_total"),
            "lat": p_lat, "lon": p_lon,
            "open_now": place.get("opening_hours", {}).get("open_now"),
            "distance_km": round(_haversine(user_lat, user_lon, p_lat, p_lon), 3),
        })
    return {"query": q, "count": len(results), "results": results}


# ---------------------------------------------------------------------------
# GET /reverse_geocode
# ---------------------------------------------------------------------------
@app.get("/reverse_geocode")
def reverse_geocode_endpoint(coords: str):
    try:
        lat, lon = map(float, coords.split(","))
    except Exception:
        raise HTTPException(400, "Invalid format. Use 'lat,lon'.")
    return {"address": reverse_geocode(lat, lon)}


# ---------------------------------------------------------------------------
# POST /import_gpx
# ---------------------------------------------------------------------------
@app.post("/import_gpx")
async def import_gpx_endpoint(file: UploadFile = File(...)):
    coords = await import_gpx(file)
    if not coords:
        raise HTTPException(400, "No coordinates found in GPX file.")
    elev = analyze_route_elevation(coords)
    return {"points": len(coords), "coordinates": coords, "elevation": elev}


# ---------------------------------------------------------------------------
# GET /export_gpx — works for A→B routes AND loop mode
# ---------------------------------------------------------------------------
@app.get("/export_gpx")
def export_gpx(
    start: str,
    end: str | None = None,
    mode: str = Query(default="shortest"),
    duration: int = Query(default=30, ge=5, le=300),
    loop_theme: str = Query(default="scenic"),
    name: str = Query(default="WalkWithMe Route"),
):
    """
    Export any route as a GPX 1.1 file.
    For loop mode, `end` is not required — pass `duration` and `loop_theme` instead.
    """
    if mode != "loop" and end is None:
        raise HTTPException(400, "'end' is required for non-loop modes.")

    try:
        lat1, lon1 = parse_location(start)
    except Exception as e:
        raise HTTPException(400, str(e))

    end_tuple = None
    if end:
        try:
            lat2, lon2 = parse_location(end)
            end_tuple = (lat2, lon2)
        except Exception as e:
            raise HTTPException(400, str(e))

    result = get_route(
        (lat1, lon1), end_tuple, mode=mode,
        duration_minutes=duration, loop_theme=loop_theme,
    )
    if "error" in result:
        raise HTTPException(404, result["error"])

    coords = result.get("coordinates", [])
    if not coords:
        raise HTTPException(404, "No route coordinates.")

    trkpts = "\n".join(
        f'    <trkpt lat="{lat}" lon="{lon}"></trkpt>' for lat, lon in coords
    )
    gpx = f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="WalkWithMe"
     xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <name>{name}</name>
    <trkseg>
{trkpts}
    </trkseg>
  </trk>
</gpx>"""

    return Response(
        content=gpx,
        media_type="application/gpx+xml",
        headers={"Content-Disposition": f'attachment; filename="route.gpx"'},
    )


# ---------------------------------------------------------------------------
# POST /vision
# ---------------------------------------------------------------------------
class VisionRequest(BaseModel):
    detections: list
    heading: float | None = None
    distance_to_next: float | None = None


@app.post("/vision")
async def vision(payload: VisionRequest):
    if not OPENAI_API_KEY:
        raise HTTPException(503, "Vision service not configured.")

    import openai
    openai.api_key = OPENAI_API_KEY

    system_prompt = (
        "You are WALKR AR Vision — pedestrian safety assistant.\n"
        "Analyze YOLO detections, heading, and distance to next turn.\n"
        "Only warn about hazards directly in the walking path.\n"
        "Respond ONLY in JSON: {\"hazards\": [], \"path_status\": \"\", \"recommendation\": \"\"}\n"
        "hazards: raw YOLO labels (\"person\", \"car\", \"bike\").\n"
        "path_status: \"clear\" | \"partially blocked\" | \"obstructed\" | \"uncertain\"\n"
        "recommendation: short phrase (\"continue\", \"slow down\", \"shift right\")"
    )

    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": (
                    f"Detections: {payload.detections}\n"
                    f"Heading: {payload.heading}\n"
                    f"Distance to next: {payload.distance_to_next}"
                )},
            ],
            max_tokens=150, temperature=0.1,
        )
        return {"ok": True, "analysis": resp.choices[0].message["content"]}
    except Exception as e:
        raise HTTPException(500, f"Vision failed: {e}")
