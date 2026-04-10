# backend/routing_ai.py

import math
import random
import polyline
from concurrent.futures import ThreadPoolExecutor, as_completed

from backend.valhalla_client import valhalla_route, valhalla_route_many
from backend.utils.common import (
    haversine,
    simplify_waypoints,
    compute_next_turn,
    parse_maneuvers,
    get_weather_and_night,
)


# ---------------------------------------------------------------------------
# Costing presets
# ---------------------------------------------------------------------------
COSTING_PRESETS: list[tuple[str, dict]] = [
    ("base",       {"pedestrian": {"use_roads": 0.5, "use_hills": 0.5, "use_lit": 0.5}}),
    ("scenic",     {"pedestrian": {"use_roads": 0.2, "use_hills": 0.4, "use_lit": 0.5}}),
    ("safe_day",   {"pedestrian": {"use_roads": 0.2, "use_hills": 0.3, "use_lit": 0.6}}),
    ("safe_night", {"pedestrian": {"use_roads": 0.1, "use_hills": 0.3, "use_lit": 1.5}}),
    ("explore",    {"pedestrian": {"use_roads": 0.3, "use_hills": 0.2, "use_lit": 0.4}}),
]

COSTING_WEATHER_EXTRAS: dict[str, tuple] = {
    "rain": ("rain_route", {"pedestrian": {"use_roads": 0.2, "use_hills": 0.1, "use_lit": 0.9}}),
    "snow": ("snow_route", {"pedestrian": {"use_roads": 0.2, "use_hills": 0.0, "use_lit": 1.0}}),
}

LOOP_THEME_COSTING: dict[str, tuple[str, dict]] = {
    "scenic":   ("scenic",    {"pedestrian": {"use_roads": 0.2, "use_hills": 0.4, "use_lit": 0.5}}),
    "explore":  ("explore",   {"pedestrian": {"use_roads": 0.3, "use_hills": 0.2, "use_lit": 0.4}}),
    "safe":     ("safe_day",  {"pedestrian": {"use_roads": 0.2, "use_hills": 0.3, "use_lit": 0.6}}),
    "coffee":   ("explore",   {"pedestrian": {"use_roads": 0.3, "use_hills": 0.2, "use_lit": 0.4}}),
    "food":     ("explore",   {"pedestrian": {"use_roads": 0.3, "use_hills": 0.2, "use_lit": 0.4}}),
    "landmark": ("scenic",    {"pedestrian": {"use_roads": 0.2, "use_hills": 0.4, "use_lit": 0.5}}),
    "history":  ("scenic",    {"pedestrian": {"use_roads": 0.2, "use_hills": 0.4, "use_lit": 0.5}}),
    "parks":    ("scenic",    {"pedestrian": {"use_roads": 0.2, "use_hills": 0.4, "use_lit": 0.5}}),
}


def _build_costing_list(weather: str) -> list[tuple[str, dict]]:
    presets = list(COSTING_PRESETS)
    if weather in COSTING_WEATHER_EXTRAS:
        presets.append(COSTING_WEATHER_EXTRAS[weather])
    return presets


def _score_route(label: str, weather: str, night: bool, length_km: float) -> float:
    score = {"base": 1, "scenic": 3, "explore": 2, "safe_day": 2,
             "safe_night": 4, "rain_route": 2, "snow_route": 3}.get(label, 1)
    if weather in ("rain", "snow", "hot"):
        score -= 1.0
    if night and "safe" in label:
        score += 2.0
    score -= length_km / 10.0
    return score


# ---------------------------------------------------------------------------
# get_ai_best_route — parallel Valhalla calls
# ---------------------------------------------------------------------------
def get_ai_best_route(start: tuple, end: tuple) -> dict:
    lat, lon = start
    weather, night = get_weather_and_night(lat, lon)
    presets = _build_costing_list(weather)

    jobs = [(label, start, end, "pedestrian", options) for label, options in presets]
    results = valhalla_route_many(jobs, max_workers=6)

    candidates = []
    for label, result in results:
        if "trip" not in result:
            continue
        leg = result["trip"]["legs"][0]
        summary = result["trip"]["summary"]
        coords = polyline.decode(leg["shape"], precision=6)
        steps = parse_maneuvers(leg)
        length_km = summary.get("length", 1)
        score = _score_route(label, weather, night, length_km)
        candidates.append({
            "label": label, "score": score,
            "coordinates": coords,
            "waypoints": simplify_waypoints(coords),
            "steps": steps,
            "next_turn": compute_next_turn(steps, coords),
            "distance_m": round(length_km * 1000),
            "duration_s": int(summary.get("time", 0)),
        })

    if not candidates:
        return {"error": "Could not generate any route candidates"}

    best = max(candidates, key=lambda c: c["score"])
    return {
        "mode": "best", "variant": best["label"],
        "weather": weather, "night": night,
        "coordinates": best["coordinates"],
        "waypoints": best["waypoints"],
        "steps": best["steps"],
        "next_turn": best["next_turn"],
        "distance_m": best["distance_m"],
        "duration_s": best["duration_s"],
    }


# ---------------------------------------------------------------------------
# Loop safety filter
# ---------------------------------------------------------------------------
_BAD_CLASSES = {"motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link"}
_BAD_USES = {"ferry", "rail", "construction", "bridleway"}
_BAD_SURFACES = {"metal", "grass", "gravel", "ground", "dirt", "clay"}


def _loop_is_acceptable(leg: dict) -> bool:
    for edge in leg.get("edges", []):
        if edge.get("road_class", "").lower() in _BAD_CLASSES:
            return False
        if edge.get("use", "").lower() in _BAD_USES:
            return False
        if edge.get("surface", "").lower() in _BAD_SURFACES:
            return False
    return True


# ---------------------------------------------------------------------------
# Midpoint generation — geometric fallback
# ---------------------------------------------------------------------------
def _geometric_midpoints(
    lat0: float, lon0: float, target_km: float, n: int = 5, seed: int = 42
) -> list[tuple]:
    rng = random.Random(seed)
    base_radius = max(0.4, target_km / (2 * math.pi))
    start_angle = rng.uniform(0, 360)
    midpoints = []
    for i in range(n):
        angle_deg = (start_angle + i * (360 / n) + rng.uniform(-15, 15)) % 360
        dist_km = rng.uniform(0.75 * base_radius, 1.25 * base_radius)
        theta = math.radians(angle_deg)
        d_lat = (dist_km / 111.0) * math.cos(theta)
        lon_scale = 111.0 * max(0.25, math.cos(math.radians(lat0)))
        d_lon = (dist_km / lon_scale) * math.sin(theta)
        midpoints.append((lat0 + d_lat, lon0 + d_lon))
    return midpoints


# ---------------------------------------------------------------------------
# Midpoint generation — POI seeded (the premium path)
# ---------------------------------------------------------------------------
def _poi_seeded_midpoints(
    lat0: float, lon0: float, target_km: float, theme: str, n: int = 4
) -> list[tuple]:
    """
    Find real POIs matching the loop theme, spread them around the compass,
    and return them as loop midpoints. Falls back to geometric if Overpass fails.
    """
    try:
        from backend.enrichment import get_pois_for_loop_theme

        radius_m = int(target_km * 600)   # generous search radius
        pois = get_pois_for_loop_theme(lat0, lon0, theme, radius_m=radius_m)

        if len(pois) < 2:
            return []

        # Spread POIs around the compass — pick ones in different directions
        # so the loop actually forms a circuit rather than clustering in one area
        def bearing_to(poi) -> float:
            return math.degrees(
                math.atan2(poi["lon"] - lon0, poi["lat"] - lat0)
            ) % 360

        # Sort by bearing, then greedily pick POIs at least 60° apart.
        # Rotate the sorted list by a random offset so each call starts the
        # greedy walk from a different POI — this varies which POIs get selected
        # while still guaranteeing directional spread around the compass.
        pois_with_bearing = [(p, bearing_to(p)) for p in pois]
        pois_with_bearing.sort(key=lambda x: x[1])
        if len(pois_with_bearing) > 1:
            offset = random.randint(0, len(pois_with_bearing) - 1)
            pois_with_bearing = pois_with_bearing[offset:] + pois_with_bearing[:offset]

        selected = []
        last_bearing = -999.0
        for poi, bearing in pois_with_bearing:
            dist_km = haversine(lat0, lon0, poi["lat"], poi["lon"])
            if dist_km < 0.15:          # too close to center
                continue
            if dist_km > target_km:     # too far for the loop
                continue
            if abs(bearing - last_bearing) < 60:  # too close in direction
                continue
            selected.append((poi["lat"], poi["lon"]))
            last_bearing = bearing
            if len(selected) >= n:
                break

        return selected if len(selected) >= 2 else []

    except Exception:
        return []


# ---------------------------------------------------------------------------
# Route one loop candidate
# ---------------------------------------------------------------------------
def _route_loop_candidate(
    center: tuple, midpoints: list, label: str, options: dict
) -> dict | None:
    all_coords: list[tuple] = []
    prev = center

    for mp in midpoints:
        seg = valhalla_route(prev, mp, "pedestrian", options)
        if "trip" not in seg:
            return None

        leg = seg["trip"]["legs"][0]
        if not _loop_is_acceptable(leg):
            return None

        coords = [
            (lat, lon)
            for lat, lon in polyline.decode(leg["shape"], precision=6)
            if -90 <= lat <= 90 and -180 <= lon <= 180
        ]
        if len(coords) < 2:
            return None

        for i in range(len(coords) - 1):
            if haversine(coords[i][0], coords[i][1], coords[i+1][0], coords[i+1][1]) > 0.5:
                return None

        all_coords.extend(coords)
        prev = mp

    back = valhalla_route(prev, center, "pedestrian", options)
    if "trip" not in back:
        return None

    leg_back = back["trip"]["legs"][0]
    if not _loop_is_acceptable(leg_back):
        return None

    back_coords = [
        (lat, lon)
        for lat, lon in polyline.decode(leg_back["shape"], precision=6)
        if -90 <= lat <= 90 and -180 <= lon <= 180
    ]
    all_coords.extend(back_coords)

    # Deduplicate
    seen: set = set()
    clean: list = []
    for pt in all_coords:
        key = (round(pt[0], 6), round(pt[1], 6))
        if key not in seen:
            seen.add(key)
            clean.append(pt)

    if len(clean) < 30:
        return None

    loop_km = sum(
        haversine(clean[i][0], clean[i][1], clean[i+1][0], clean[i+1][1])
        for i in range(len(clean) - 1)
        if haversine(clean[i][0], clean[i][1], clean[i+1][0], clean[i+1][1]) < 0.5
    )

    return {"label": label, "coordinates": clean, "loop_km": loop_km}


# ---------------------------------------------------------------------------
# get_ai_loop_route — POI-seeded with geometric fallback, parallel candidates
# ---------------------------------------------------------------------------
def get_ai_loop_route(
    center: tuple,
    target_km: float = 3.0,
    theme: str = "scenic",
    n_midpoints: int = 4,
) -> dict:
    if not center:
        return {"error": "Missing center coordinates"}

    lat0, lon0 = center
    weather, night = get_weather_and_night(lat0, lon0)

    # Night → force safe costing regardless of theme
    if night:
        label, options = LOOP_THEME_COSTING["safe"]
    else:
        label, options = LOOP_THEME_COSTING.get(theme, LOOP_THEME_COSTING["scenic"])

    # --- Try POI seeding first ---
    poi_midpoints = _poi_seeded_midpoints(lat0, lon0, target_km, theme, n=n_midpoints)

    # --- Build candidate midpoint sets ---
    # Candidate 0: POI-seeded (if available)
    # Candidates 1-2: geometric with different seeds (fallback / diversity)
    candidate_midpoints = []
    if poi_midpoints:
        candidate_midpoints.append(("poi_seeded", poi_midpoints))

    # Use a fresh random base each call so repeated requests return different routes.
    # Two seeds derived from the same base keep the candidates meaningfully different
    # from each other while varying across requests.
    _base = random.randint(0, 99_999)
    for seed in [_base, _base + 137]:
        candidate_midpoints.append(
            (f"geometric_{seed}", _geometric_midpoints(lat0, lon0, target_km, n=n_midpoints, seed=seed))
        )

    def try_candidate(tag_midpoints):
        tag, midpoints = tag_midpoints
        result = _route_loop_candidate(center, midpoints, label, options)
        if result:
            result["seeded"] = tag.startswith("poi")
        return result

    candidates = []
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(try_candidate, item): item for item in candidate_midpoints}
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                candidates.append(result)

    if not candidates:
        return {"error": "Could not generate a walking loop. Try a different location or distance."}

    # Prefer POI-seeded if it exists and is within 30% of target distance
    poi_candidates = [c for c in candidates if c.get("seeded")]
    geo_candidates = [c for c in candidates if not c.get("seeded")]

    if poi_candidates:
        best_poi = min(poi_candidates, key=lambda c: abs(c["loop_km"] - target_km))
        best_geo = min(geo_candidates, key=lambda c: abs(c["loop_km"] - target_km)) if geo_candidates else None
        # Use POI if it's within 40% of target; otherwise take closest geometric
        if best_geo and abs(best_poi["loop_km"] - target_km) > target_km * 0.4:
            best = best_geo
        else:
            best = best_poi
    else:
        best = min(candidates, key=lambda c: abs(c["loop_km"] - target_km))

    coords = best["coordinates"]
    return {
        "mode": "loop",
        "theme": theme,
        "variant": best["label"],
        "poi_seeded": best.get("seeded", False),
        "weather": weather,
        "night": night,
        "coordinates": coords,
        "waypoints": simplify_waypoints(coords, step=8),
        "loop_km": round(best["loop_km"], 2),
        "target_km": round(target_km, 2),
        "distance_m": round(best["loop_km"] * 1000),
        "duration_s": int((best["loop_km"] / 5.0) * 3600),
    }
