# backend/routing/routing_ai.py

import requests
import random
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

        if code in [61, 63, 65]:
            return "rain"
        if code in [71, 73, 75]:
            return "snow"
        if temp > 30:
            return "hot"
        if temp < 5:
            return "cold"
        return "clear"
    except Exception:
        return "clear"


# ============================================================
# NIGHT CHECK
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
    except Exception:
        return False


# ============================================================
# AI SUPER ROUTER — COSTING PRESETS
# ============================================================
def build_costings(start):
    lat, lon = start
    weather = get_weather(lat, lon)
    night = is_night(lat, lon)

    presets = []

    # 1. BASE PEDESTRIAN ROUTE
    presets.append((
        "base",
        {
            "pedestrian": {
                "use_roads": 0.5,
                "use_hills": 0.5,
                "use_lit": 0.5,
            }
        }
    ))

    # 2. SCENIC — parks, paths, water
    presets.append((
        "scenic",
        {
            "pedestrian": {
                "use_roads": 0.2,
                "use_tracks": 0.0,
                "use_hills": 0.4,
                "use_lit": 0.5,
                "use_uphill": 0.5,
            }
        }
    ))

    # 3. SAFE DAY
    presets.append((
        "safe_day",
        {
            "pedestrian": {
                "use_roads": 0.2,
                "use_tracks": 0.2,
                "use_hills": 0.3,
                "use_lit": 0.6,
                "safety_factor": 0.7,
            }
        }
    ))

    # 4. SAFE NIGHT (AI strongest)
    presets.append((
        "safe_night",
        {
            "pedestrian": {
                "use_lit": 1.5,
                "alley_factor": 8.0,
                "use_roads": 0.1,
                "use_tracks": 0.0,
                "safety_factor": 1.5,
            }
        }
    ))

    # 5. EXPLORE — quiet streets, food, footways
    presets.append((
        "explore",
        {
            "pedestrian": {
                "use_roads": 0.3,
                "use_tracks": 0.1,
                "use_hills": 0.2,
                "use_lit": 0.4,
                "safety_factor": 0.8,
            }
        }
    ))

    # Weather-specific bonus presets
    if weather == "rain":
        presets.append((
            "rain_route",
            {
                "pedestrian": {
                    "use_hills": 0.1,
                    "use_lit": 0.9,
                    "use_roads": 0.2,
                }
            }
        ))

    if weather == "snow":
        presets.append((
            "snow_route",
            {
                "pedestrian": {
                    "use_hills": 0.0,
                    "use_lit": 1.0,
                    "use_roads": 0.2,
                    "safety_factor": 1.3,
                }
            }
        ))

    return presets, weather, night


# ============================================================
# SCORING FUNCTION — AI chooses the best route
# ============================================================
def score_route(label, weather, night, trip_summary):
    """
    Higher score = better
    AI rewards:
      - safety at night
      - scenic when clear weather
      - minimize hills in heat/rain/snow
    """

    length = trip_summary.get("length", 1)
    time = trip_summary.get("time", 1)

    score = 0

    # Base weighting
    if label == "base":
        score += 1
    if label == "scenic":
        score += 3
    if label == "explore":
        score += 2
    if label == "safe_day":
        score += 2
    if label == "safe_night":
        score += 4  # highest weight
    if label == "rain_route":
        score += 2
    if label == "snow_route":
        score += 3

    # Weather penalties for hills
    if weather in ["rain", "snow", "hot"]:
        score -= (trip_summary.get("max_up_slope", 0) * 2)

    # Night bonus for lit-heavy variants
    if night and "safe" in label:
        score += 2

    # Prefer shorter but not too short
    score -= (length / 5000)  # soft penalty for distance

    return score


# ============================================================
# MAIN — AI SUPER ROUTER (A → B)
# ============================================================
def get_ai_best_route(start, end):
    # 1. Build candidate costings
    costings, weather, night = build_costings(start)

    candidates = []

    # 2. Compute routes for each costing preset
    for label, costing_options in costings:
        result = valhalla_route(
            start,
            end,
            costing="pedestrian",
            costing_options=costing_options,
        )

        if "trip" not in result:
            continue

        trip = result["trip"]
        leg = trip["legs"][0]
        poly = leg["shape"]
        coords = polyline.decode(poly)

        score = score_route(label, weather, night, trip["summary"])

        candidates.append({
            "label": label,
            "score": score,
            "polyline": poly,
            "coordinates": coords,
            "summary": trip["summary"],
        })

    if not candidates:
        return {"error": "AI could not generate any route"}

    # 3. Pick highest-scoring route
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
# AI LOOP ROUTER — START AND END AT SAME POINT
# ============================================================
def get_ai_loop_route(center, target_km=5.0):
    """
    Build an AI-chosen loop that:
      - starts and ends at `center` (lat, lon)
      - tries to be close to `target_km` total distance
      - reuses the AI safety/scenic presets + scoring

    Returns a single polyline + coords for the full loop.
    """

    if not center:
        return {"error": "Missing center coordinates for loop"}

    lat0, lon0 = center

    # 1. Build costings + context
    costings, weather, night = build_costings(center)
    loops = []

    # Halfway-point distance ~ half the target loop
    # (out-and-back style loop)
    radius_km = max(0.8, target_km / 2.0)

    # Try a few different directions for the "turnaround" point
    candidate_angles = [45, 120, 210, 300]

    for label, costing_options in costings:
        for angle_deg in candidate_angles:
            theta = math.radians(angle_deg)

            # Approximate lat/lon offsets for small distances
            d = radius_km
            d_lat = (d / 111.0) * math.cos(theta)
            lon_scale = 111.0 * max(0.1, math.cos(math.radians(lat0)))
            d_lon = (d / lon_scale) * math.sin(theta)

            mid = (lat0 + d_lat, lon0 + d_lon)

            # 2. Route out (center -> mid) and back (mid -> center)
            out_res = valhalla_route(
                center,
                mid,
                costing="pedestrian",
                costing_options=costing_options,
            )
            back_res = valhalla_route(
                mid,
                center,
                costing="pedestrian",
                costing_options=costing_options,
            )

            if "trip" not in out_res or "trip" not in back_res:
                continue

            out_trip = out_res["trip"]
            back_trip = back_res["trip"]

            out_leg = out_trip["legs"][0]
            back_leg = back_trip["legs"][0]

            out_coords = polyline.decode(out_leg["shape"])
            back_coords = polyline.decode(back_leg["shape"])

            # Build full loop coords (avoid duplicating the mid start)
            loop_coords = out_coords + back_coords[1:]

            # Combine summaries
            total_summary = {
                "time": out_trip["summary"].get("time", 0)
                        + back_trip["summary"].get("time", 0),
                "length": out_trip["summary"].get("length", 0)
                          + back_trip["summary"].get("length", 0),
                "max_up_slope": max(
                    out_trip["summary"].get("max_up_slope", 0),
                    back_trip["summary"].get("max_up_slope", 0),
                ),
            }

            # 3. Use same scoring logic + small penalty for being far from target_km
            base_score = score_route(label, weather, night, total_summary)
            distance_km = total_summary["length"]   # Valhalla summary length is in km
            target_penalty = abs(distance_km - target_km)  # 1 point per km off target

            score = base_score - target_penalty

            loops.append({
                "label": label,
                "angle": angle_deg,
                "score": score,
                "coordinates": loop_coords,
                "polyline": polyline.encode(loop_coords),
                "summary": total_summary,
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

