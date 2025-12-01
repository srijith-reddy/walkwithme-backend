# backend/routing/routing_ai.py

import requests
import math
import polyline
from datetime import datetime
from backend.valhalla_client import valhalla_route


# ============================================================
# HELPERS (waypoints + next turn)
# ============================================================

def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2 +
        math.cos(math.radians(lat1)) *
        math.cos(math.radians(lat2)) *
        math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


def simplify_waypoints(coords, step=5):
    return coords[::step] if len(coords) > step else coords


def compute_next_turn(steps, coords):
    if steps:
        m = steps[0]
        return {
            "type": m.get("type", ""),
            "instruction": m.get("instruction", ""),
            "distance_m": m.get("length", 0),
            "lat": m.get("begin_shape_index", None),
            "lon": m.get("end_shape_index", None),
        }

    # fallback bearing
    if len(coords) >= 2:
        lat1, lon1 = coords[0]
        lat2, lon2 = coords[1]
        bearing = math.degrees(math.atan2(lon2 - lon1, lat2 - lat1))
        return {
            "type": "straight",
            "instruction": "Continue straight",
            "degrees": bearing,
            "distance_m": 5,
        }

    return None


# ============================================================
# WEATHER (Open-Meteo)
# ============================================================
def get_weather(lat, lon):
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}&current_weather=true"
        )
        w = requests.get(url, timeout=5).json()["current_weather"]

        code = int(w["weathercode"])
        temp = float(w["temperature"])

        if code in [61, 63, 65]: return "rain"
        if code in [71, 73, 75]: return "snow"
        if temp > 30: return "hot"
        if temp < 5: return "cold"
        return "clear"

    except:
        return "clear"


# ============================================================
# DAY/NIGHT
# ============================================================
def is_night(lat, lon):
    try:
        r = requests.get(
            f"https://api.sunrise-sunset.org/json?lat={lat}&lng={lon}&formatted=0",
            timeout=5
        ).json()["results"]

        sunrise = datetime.fromisoformat(r["sunrise"])
        sunset = datetime.fromisoformat(r["sunset"])
        now = datetime.utcnow()

        return not (sunrise <= now <= sunset)
    except:
        return False


# ============================================================
# COSTING PRESETS
# ============================================================
def build_costings(start):
    lat, lon = start
    weather = get_weather(lat, lon)
    night = is_night(lat, lon)

    presets = []

    presets.append(("base",      {"pedestrian": {"use_roads": 0.5, "use_hills": 0.5, "use_lit": 0.5}}))
    presets.append(("scenic",    {"pedestrian": {"use_roads": 0.2, "use_hills": 0.4, "use_lit": 0.5}}))
    presets.append(("safe_day",  {"pedestrian": {"use_roads": 0.2, "use_hills": 0.3, "use_lit": 0.6, "safety_factor": 0.7}}))
    presets.append(("safe_night",{"pedestrian": {"use_roads": 0.1, "use_hills": 0.3, "use_lit": 1.5, "safety_factor": 1.5}}))
    presets.append(("explore",   {"pedestrian": {"use_roads": 0.3, "use_hills": 0.2, "use_lit": 0.4, "safety_factor": 0.8}}))

    if weather == "rain":
        presets.append(("rain_route",
            {"pedestrian": {"use_roads": 0.2, "use_hills": 0.1, "use_lit": 0.9}}
        ))

    if weather == "snow":
        presets.append(("snow_route",
            {"pedestrian": {"use_roads": 0.2, "use_hills": 0.0, "use_lit": 1.0, "safety_factor": 1.3}}
        ))

    return presets, weather, night


# ============================================================
# AI SCORING
# ============================================================
def score_route(label, weather, night, summary):
    length_km = summary.get("length", 1) / 1000.0
    time = summary.get("time", 1)
    max_up = summary.get("max_up_slope", 0)

    score = 0

    if label == "base": score += 1
    if label == "scenic": score += 3
    if label == "explore": score += 2
    if label == "safe_day": score += 2
    if label == "safe_night": score += 4
    if label == "rain_route": score += 2
    if label == "snow_route": score += 3

    # weather penalties
    if weather in ["rain", "snow", "hot"]:
        score -= (max_up * 2)

    if night and "safe" in label:
        score += 2

    score -= (length_km / 5.0)

    return score


# ============================================================
# AI BEST ROUTE
# ============================================================
def get_ai_best_route(start, end):
    costings, weather, night = build_costings(start)
    candidates = []
    for label, options in costings:
        result = valhalla_route(start, end, "pedestrian", options)
        if "trip" not in result:
            continue

        leg = result["trip"]["legs"][0]
        summary = result["trip"]["summary"]

        # decode polyline6
        coords = polyline.decode(leg["shape"], precision=6)

        # steps
        maneuvers = leg.get("maneuvers", [])
        steps = [{
            "instruction": m.get("instruction", ""),
            "type": m.get("type", ""),
            "length": m.get("length", 0),
            "begin_lat": m.get("begin_shape_index", None),
            "end_lat": m.get("end_shape_index", None),
        } for m in maneuvers]

        waypoints = simplify_waypoints(coords)
        next_turn = compute_next_turn(steps, coords)

        score = score_route(label, weather, night, summary)

        candidates.append({
            "label": label,
            "score": score,
            "coords": coords,
            "waypoints": waypoints,
            "steps": steps,
            "next_turn": next_turn,
            "summary": summary,
        })

    if not candidates:
        return {"error": "AI could not generate any route"}

    best = max(candidates, key=lambda x: x["score"])

    return {
        "mode": "best",
        "variant": best["label"],
        "weather": weather,
        "night": night,
        "score": best["score"],
        "coordinates": best["coords"],
        "waypoints": best["waypoints"],
        "steps": best["steps"],
        "next_turn": best["next_turn"],
        "summary": best["summary"],
    }


# ============================================================
# AI LOOP ROUTE
# ============================================================

def valhalla_locate(point):
    """
    Snap a single (lat, lon) point to nearest real road edge using Valhalla /locate.
    Returns the raw JSON result from Valhalla.
    """
    lat, lon = point
    body = {
        "locations": [
            {"lat": lat, "lon": lon}
        ]
    }

    try:
        res = requests.post(
            f"{VALHALLA_URL}/locate",
            json=body,
            timeout=5
        )
        return res.json()
    except Exception as e:
        return {"error": f"Valhalla locate failed: {e}"}


def get_ai_loop_route(center, target_km=3.0):
    import random

    if not center:
        return {"error": "Missing center coordinates"}

    lat0, lon0 = center

    # =========================================================
    # ROAD SAFETY FILTERS
    # =========================================================
    BAD_CLASSES = {
        "motorway", "motorway_link",
        "trunk", "trunk_link",
        "primary", "primary_link",
        "construction",
        "private"
    }

    BAD_USES = {
        "ferry",
        "rail",
        "construction",
        "steps",
        "sidepath",
        "bridleway",
        "piers", "pier",
        "path"     # often waterwalk/boardwalk/pier segments
    }

    BAD_SURFACES = {
        "wood",       # boardwalk
        "metal",
        "gravel",
        "ground",
        "dirt",
        "clay",
        "grass",
        "unknown"
    }

    def route_is_safe(leg):
        """Reject routes that contain bad road classes, uses, or surfaces."""
        if "edges" not in leg:
            return True

        for edge in leg["edges"]:
            cls = edge.get("class", "").lower()
            use = edge.get("use", "").lower()
            surf = edge.get("surface", "").lower()

            if cls in BAD_CLASSES:
                return False
            if use in BAD_USES:
                return False
            if surf in BAD_SURFACES:
                return False

        return True

    # =========================================================
    # 1) Generate GOOD bearings (5–10 random)
    # =========================================================
    bearings = []
    angle = random.uniform(0, 360)
    max_span = random.uniform(380, 460)

    while angle < max_span:
        bearings.append(angle % 360)
        angle += random.uniform(40, 70)

    if len(bearings) < 5:
        bearings = [(i * 60) + random.uniform(-15, 15) for i in range(6)]

    # =========================================================
    # 2) Random distances around base radius
    # =========================================================
    base_radius = max(0.6, target_km / (2 * math.pi))
    distances = [
        random.uniform(0.75 * base_radius, 1.3 * base_radius)
        for _ in bearings
    ]

    # =========================================================
    # 3) Convert (bearing, distance) → midpoints (OFFSET ONLY)
    # =========================================================
    midpoints = []
    for ang, dist_km in zip(bearings, distances):
        theta = math.radians(ang)

        d_lat = (dist_km / 111.0) * math.cos(theta)
        lon_scale = 111.0 * max(0.25, math.cos(math.radians(lat0)))
        d_lon = (dist_km / lon_scale) * math.sin(theta)

        midpoints.append((lat0 + d_lat, lon0 + d_lon))

    # =========================================================
    # 4) Try all AI costings
    # =========================================================
    costings, weather, night = build_costings(center)
    candidates = []

    def valid_coord(pt):
        lat, lon = pt
        return -90 <= lat <= 90 and -180 <= lon <= 180

    for label, options in costings:

        all_coords = []
        prev = center
        failed = False

        # -----------------------------------------------------
        # Route through each midpoint
        # -----------------------------------------------------
        for mp in midpoints:
            seg = valhalla_route(prev, mp, "pedestrian", options)
            if "trip" not in seg:
                failed = True
                break

            leg = seg["trip"]["legs"][0]

            # SAFETY FILTER
            if not route_is_safe(leg):
                failed = True
                break

            # Decode shape safely
            coords = [
                (lat, lon)
                for (lat, lon) in polyline.decode(leg["shape"], precision=6)
                if valid_coord((lat, lon))
            ]

            if len(coords) < 2:
                failed = True
                break

            # TELEPORT JUMP PROTECTION
            seg_len = 0.0
            for i in range(len(coords) - 1):
                lat1, lon1 = coords[i]
                lat2, lon2 = coords[i+1]

                step = haversine(lat1, lon1, lat2, lon2)
                if step > 0.5:     # >500m = invalid
                    failed = True
                    break

                seg_len += step

            if failed or seg_len > 2.0:  # midpoint spacing sanity
                failed = True
                break

            all_coords.extend(coords)
            prev = mp

        if failed:
            continue

        # -----------------------------------------------------
        # Final segment back to start
        # -----------------------------------------------------
        back = valhalla_route(prev, center, "pedestrian", options)
        if "trip" not in back:
            continue

        leg_back = back["trip"]["legs"][0]

        if not route_is_safe(leg_back):
            continue

        coords_back = [
            (lat, lon)
            for (lat, lon) in polyline.decode(leg_back["shape"], precision=6)
            if valid_coord((lat, lon))
        ]

        all_coords.extend(coords_back)

        # -----------------------------------------------------
        # DEDUPE COORDS
        # -----------------------------------------------------
        clean = []
        seen = set()
        for lat, lon in all_coords:
            key = (round(lat, 6), round(lon, 6))
            if key not in seen:
                seen.add(key)
                clean.append((lat, lon))

        all_coords = clean

        if len(all_coords) < 50:
            continue

        # =========================================================
        # 5) Compute actual loop distance
        # =========================================================
        loop_km = 0.0
        for i in range(len(all_coords) - 1):
            lat1, lon1 = all_coords[i]
            lat2, lon2 = all_coords[i+1]

            if not valid_coord((lat1, lon1)) or not valid_coord((lat2, lon2)):
                continue

            step = haversine(lat1, lon1, lat2, lon2)
            if step > 0.5:  # teleport
                continue

            loop_km += step

        summary = {"length": loop_km}

        # =========================================================
        # 6) AI SCORING
        # =========================================================
        ai_score = score_route(label, weather, night, summary)
        final_score = ai_score - abs(loop_km - target_km)

        candidates.append({
            "label": label,
            "score": final_score,
            "coordinates": all_coords,
            "summary": summary,
            "target_km": target_km,
            "weather": weather,
            "night": night
        })

    if not candidates:
        return {"error": "Could not generate loop"}

    best = max(candidates, key=lambda c: c["score"])

    return {
        "mode": "loop",
        "variant": best["label"],
        "coordinates": best["coordinates"],
        "summary": best["summary"],
        "score": best["score"],
        "target_km": best["target_km"],
        "weather": best["weather"],
        "night": best["night"]
    }
