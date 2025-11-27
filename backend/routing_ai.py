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
    costings, weather, night = build_costings(center)

    loops = []
    radius_km = max(0.8, target_km / 2.0)
    angles = [45, 120, 210, 300]

    for label, options in costings:
        for angle in angles:
            theta = math.radians(angle)

            # compute midpoint
            d = radius_km
            d_lat = (d / 111.0) * math.cos(theta)
            lon_scale = 111.0 * max(0.1, math.cos(math.radians(lat0)))
            d_lon = (d / lon_scale) * math.sin(theta)

            mid = (lat0 + d_lat, lon0 + d_lon)

            out_r = valhalla_route(center, mid, "pedestrian", options)
            back_r = valhalla_route(mid, center, "pedestrian", options)

            if "trip" not in out_r or "trip" not in back_r:
                continue

            out_leg = out_r["trip"]["legs"][0]
            back_leg = back_r["trip"]["legs"][0]

            out_coords = polyline.decode(out_leg["shape"], precision=6)
            back_coords = polyline.decode(back_leg["shape"], precision=6)

            loop_coords = out_coords + back_coords[1:]

            total_km = (
                out_r["trip"]["summary"]["length"] +
                back_r["trip"]["summary"]["length"]
            ) / 1000.0

            combined_summary = {
                "time": out_r["trip"]["summary"]["time"] +
                        back_r["trip"]["summary"]["time"],
                "length": total_km * 1000,
                "max_up_slope": max(
                    out_r["trip"]["summary"].get("max_up_slope", 0),
                    back_r["trip"]["summary"].get("max_up_slope", 0),
                ),
            }

            base_score = score_route(
                label, weather, night,
                {"length": combined_summary["length"],
                 "time": combined_summary["time"],
                 "max_up_slope": combined_summary["max_up_slope"]}
            )

            penalty = abs(total_km - target_km)
            final_score = base_score - penalty

            loops.append({
                "label": label,
                "angle": angle,
                "score": final_score,
                "coordinates": loop_coords,
                "waypoints": simplify_waypoints(loop_coords),
                "summary": combined_summary,
            })

    if not loops:
        return {"error": "AI could not build any loop"}

    best = max(loops, key=lambda x: x["score"])

    return {
        "mode": "loop",
        "variant": best["label"],
        "weather": weather,
        "night": night,
        "score": best["score"],
        "angle": best["angle"],
        "target_km": target_km,
        "coordinates": best["coordinates"],
        "waypoints": best["waypoints"],
        "summary": best["summary"],
    }
