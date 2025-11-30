# backend/routing/routing_ai.py

import requests
import math
import polyline
from datetime import datetime
from backend.valhalla_client import valhalla_route


# ============================================================
# HELPERS (waypoints + next turn)
# ============================================================
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
def get_ai_loop_route(center, target_km=5.0):
    if not center:
        return {"error": "Missing center coordinates"}

    lat0, lon0 = center
    radius_km = max(0.6, target_km / (2 * math.pi))  # adjust radius based on full circle

    # Produce 8-point smooth circle
    angles = [0, 45, 90, 135, 180, 225, 270, 315]

    # circle midpoints
    midpoints = []
    for ang in angles:
        theta = math.radians(ang)
        d_lat = (radius_km / 111.0) * math.cos(theta)
        lon_scale = 111.0 * max(0.1, math.cos(math.radians(lat0)))
        d_lon = (radius_km / lon_scale) * math.sin(theta)

        midpoints.append((lat0 + d_lat, lon0 + d_lon))

    # Build costings
    costings, weather, night = build_costings(center)

    candidates = []

    # Try all safety/scenic/weather presets
    for label, options in costings:

        all_coords = []
        failed = False

        # Start = center
        prev = center

        # Connect each midpoint in order
        for mp in midpoints:
            seg = valhalla_route(prev, mp, "pedestrian", options)
            if "trip" not in seg:
                failed = True
                break

            coords = polyline.decode(seg["trip"]["legs"][0]["shape"], precision=6)
            all_coords += coords
            prev = mp

        # Connect final midpoint back to start
        back = valhalla_route(prev, center, "pedestrian", options)
        if "trip" not in back:
            continue

        coords_back = polyline.decode(back["trip"]["legs"][0]["shape"], precision=6)
        all_coords += coords_back

        if failed or len(all_coords) < 20:
            continue

        # Compute total length
        summary = {
            "length": sum(
                seg["trip"]["summary"]["length"]
                for seg in [valhalla_route(center, midpoints[0], "pedestrian", options)]
            )
        }

        # Predict final loop distance
        loop_dist_km = 0
        for i in range(len(all_coords) - 1):
            lat1, lon1 = all_coords[i]
            lat2, lon2 = all_coords[i + 1]
            loop_dist_km += haversine(lat1, lon1, lat2, lon2)

        summary["length"] = loop_dist_km * 1000

        # Score using your AI scoring
        score = score_route(label, weather, night, summary)
        penalty = abs(loop_dist_km - target_km)
        final_score = score - penalty

        candidates.append({
            "label": label,
            "score": final_score,
            "coordinates": all_coords,
            "summary": summary,
            "target_km": target_km,
            "night": night,
            "weather": weather
        })

    if not candidates:
        return {"error": "Could not generate loop"}

    best = max(candidates, key=lambda x: x["score"])

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
