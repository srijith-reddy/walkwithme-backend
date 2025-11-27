# backend/routing/routing_ai.py

import requests
import math
import polyline
from datetime import datetime
from backend.valhalla_client import valhalla_route


# ============================================================
# WEATHER (Open-Meteo – keyless)
# ============================================================
def get_weather(lat, lon):
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}&current_weather=true"
        )
        j = requests.get(url, timeout=5).json()
        w = j["current_weather"]

        code = int(w["weathercode"])
        temp = float(w["temperature"])

        if code in [61, 63, 65]: return "rain"
        if code in [71, 73, 75]: return "snow"
        if temp > 30: return "hot"
        if temp < 5:  return "cold"
        return "clear"

    except Exception:
        return "clear"


# ============================================================
# DAY/NIGHT CHECK
# ============================================================
def is_night(lat, lon):
    try:
        r = requests.get(
            f"https://api.sunrise-sunset.org/json?lat={lat}&lng={lon}&formatted=0",
            timeout=5
        ).json()["results"]

        sunrise = datetime.fromisoformat(r["sunrise"])
        sunset  = datetime.fromisoformat(r["sunset"])
        now = datetime.utcnow()

        return not (sunrise <= now <= sunset)
    except Exception:
        return False


# ============================================================
# COSTING PRESETS (ONLY VALID VALHALLA KEYS)
# ============================================================
def build_costings(start):
    lat, lon = start
    weather = get_weather(lat, lon)
    night = is_night(lat, lon)

    presets = []

    # 1. BASE
    presets.append((
        "base",
        {"pedestrian": {
            "use_roads": 0.5,
            "use_hills": 0.5,
            "use_lit": 0.5,
        }}
    ))

    # 2. SCENIC
    presets.append((
        "scenic",
        {"pedestrian": {
            "use_roads": 0.2,
            "use_hills": 0.4,
            "use_lit": 0.5,
        }}
    ))

    # 3. SAFE DAY
    presets.append((
        "safe_day",
        {"pedestrian": {
            "use_roads": 0.2,
            "use_hills": 0.3,
            "use_lit": 0.6,
            "safety_factor": 0.7,
        }}
    ))

    # 4. SAFE NIGHT
    presets.append((
        "safe_night",
        {"pedestrian": {
            "use_roads": 0.1,
            "use_hills": 0.3,
            "use_lit": 1.5,
            "safety_factor": 1.5,
        }}
    ))

    # 5. EXPLORE
    presets.append((
        "explore",
        {"pedestrian": {
            "use_roads": 0.3,
            "use_hills": 0.2,
            "use_lit": 0.4,
            "safety_factor": 0.8,
        }}
    ))

    # Weather-specific
    if weather == "rain":
        presets.append((
            "rain_route",
            {"pedestrian": {
                "use_roads": 0.2,
                "use_hills": 0.1,
                "use_lit": 0.9,
            }}
        ))

    if weather == "snow":
        presets.append((
            "snow_route",
            {"pedestrian": {
                "use_roads": 0.2,
                "use_hills": 0.0,
                "use_lit": 1.0,
                "safety_factor": 1.3,
            }}
        ))

    return presets, weather, night


# ============================================================
# SCORING FUNCTION (AI chooses best)
# ============================================================
def score_route(label, weather, night, trip_summary):
    length = trip_summary.get("length", 1) / 1000.0  # convert meters → km
    time   = trip_summary.get("time", 1)

    score = 0

    if label == "base": score += 1
    if label == "scenic": score += 3
    if label == "explore": score += 2
    if label == "safe_day": score += 2
    if label == "safe_night": score += 4
    if label == "rain_route": score += 2
    if label == "snow_route": score += 3

    # Hills bad for rain/snow/heat
    if weather in ["rain", "snow", "hot"]:
        score -= (trip_summary.get("max_up_slope", 0) * 2)

    if night and "safe" in label:
        score += 2

    # Soft penalty for long distances
    score -= (length / 5.0)

    return score


# ============================================================
# AI BEST ROUTE (A → B)
# ============================================================
def get_ai_best_route(start, end):
    costings, weather, night = build_costings(start)

    candidates = []

    for label, options in costings:
        result = valhalla_route(start, end, "pedestrian", options)

        if "trip" not in result:
            continue

        leg = result["trip"]["legs"][0]
        poly = leg["shape"]
        coords = polyline.decode(poly)
        summary = result["trip"]["summary"]

        score = score_route(label, weather, night, summary)

        candidates.append({
            "label": label,
            "score": score,
            "polyline": poly,
            "coordinates": coords,
            "summary": summary,
        })

    if not candidates:
        return {"error": "AI could not generate any route"}

    best = max(candidates, key=lambda x: x["score"])

    return {
        "mode": "best",
        "weather": weather,
        "night": night,
        "variant": best["label"],
        "score": best["score"],
        "start": start,
        "end": end,
        "coordinates": best["coordinates"],
        "polyline": best["polyline"],
        "summary": best["summary"],
    }


# ============================================================
# AI LOOP ROUTE (start → loop → start)
# ============================================================
def get_ai_loop_route(center, target_km=5.0):
    if not center:
        return {"error": "Missing center coordinates"}

    lat0, lon0 = center

    costings, weather, night = build_costings(center)
    loops = []

    radius_km = max(0.8, target_km / 2.0)

    angles = [45, 120, 210, 300]

    for label, opt in costings:
        for angle in angles:
            theta = math.radians(angle)

            d = radius_km
            d_lat = (d / 111.0) * math.cos(theta)
            lon_scale = 111.0 * max(0.1, math.cos(math.radians(lat0)))
            d_lon = (d / lon_scale) * math.sin(theta)

            mid = (lat0 + d_lat, lon0 + d_lon)

            out_res = valhalla_route(center, mid, "pedestrian", opt)
            back_res = valhalla_route(mid, center, "pedestrian", opt)

            if "trip" not in out_res or "trip" not in back_res:
                continue

            out_leg = out_res["trip"]["legs"][0]
            back_leg = back_res["trip"]["legs"][0]

            out_coords = polyline.decode(out_leg["shape"])
            back_coords = polyline.decode(back_leg["shape"])

            loop_coords = out_coords + back_coords[1:]

            length_km = (
                out_res["trip"]["summary"]["length"] +
                back_res["trip"]["summary"]["length"]
            ) / 1000.0  # meters → km

            combined_summary = {
                "time": out_res["trip"]["summary"]["time"] +
                        back_res["trip"]["summary"]["time"],
                "length": length_km,
                "max_up_slope": max(
                    out_res["trip"]["summary"].get("max_up_slope", 0),
                    back_res["trip"]["summary"].get("max_up_slope", 0),
                ),
            }

            base_score = score_route(label, weather, night, {
                "length": length_km * 1000,
                "time": combined_summary["time"],
                "max_up_slope": combined_summary["max_up_slope"]
            })

            penalty = abs(length_km - target_km)

            final_score = base_score - penalty

            loops.append({
                "label": label,
                "angle": angle,
                "score": final_score,
                "coordinates": loop_coords,
                "polyline": polyline.encode(loop_coords),
                "summary": combined_summary,
            })

    if not loops:
        return {"error": "AI could not build any loop"}

    best = max(loops, key=lambda x: x["score"])

    return {
        "mode": "loop",
        "weather": weather,
        "night": night,
        "variant": best["label"],
        "angle": best["angle"],
        "score": best["score"],
        "center": center,
        "target_km": target_km,
        "coordinates": best["coordinates"],
        "polyline": best["polyline"],
        "summary": best["summary"],
    }
