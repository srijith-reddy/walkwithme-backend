# backend/detours.py
#
# Detour economy — finds things worth stepping off your route for.
#
# For every notable POI near a route, computes:
#   - How far off the route it is
#   - How many extra minutes it costs (approximated from walking speed)
#   - A "worth it" score based on category importance vs time cost
#
# Returns the top 2-3 detours with enough context for the iOS app to show:
#   "+4 min · Brooklyn Bridge Park overlook"
#   "+6 min · Russ & Daughters — NYC institution since 1914"
#
# Approximate detour cost is used instead of exact Valhalla calls to keep
# this endpoint fast. Valhalla-exact cost can be added as a premium option.

import math
from backend.utils.common import haversine, point_to_route_distance_m, coords_bbox
from backend.enrichment import _fetch_overpass_raw, _build_pois, _EMOJI


# ---------------------------------------------------------------------------
# Category importance weights (higher = more worth a detour)
# ---------------------------------------------------------------------------
_IMPORTANCE = {
    "landmark": 10,
    "historic": 9,
    "museum":   8,
    "nature":   7,
    "park":     5,
    "cafe":     6,
    "restaurant": 5,
    "bar":      4,
    "other":    2,
}

# Max acceptable extra time per category (minutes)
_MAX_DETOUR_MINUTES = {
    "landmark": 10,
    "historic": 10,
    "museum":   8,
    "nature":   8,
    "park":     6,
    "cafe":     6,
    "restaurant": 5,
    "bar":      4,
    "other":    3,
}

WALK_SPEED_M_PER_MIN = 83.0   # 5 km/h ≈ 83 m/min


def _detour_minutes(distance_from_route_m: float) -> float:
    """
    Approximate extra time for an out-and-back detour.
    2 × distance / walk speed, rounded to nearest 0.5 min.
    """
    raw = (2 * distance_from_route_m) / WALK_SPEED_M_PER_MIN
    return round(raw * 2) / 2  # round to nearest 0.5


def _worth_it_score(category: str, distance_m: float) -> float:
    """
    Score = importance / extra_minutes
    Higher = better return on detour time investment.
    """
    extra_min = _detour_minutes(distance_m)
    if extra_min <= 0:
        return 0.0
    importance = _IMPORTANCE.get(category, 2)
    return round(importance / extra_min, 3)


# ---------------------------------------------------------------------------
# Find the nearest route point to a POI (returns index)
# ---------------------------------------------------------------------------
def _nearest_route_index(lat: float, lon: float, coords: list[tuple], sample: int = 3) -> int:
    best_idx, best_dist = 0, float("inf")
    for i in range(0, len(coords), sample):
        d = haversine(lat, lon, coords[i][0], coords[i][1])
        if d < best_dist:
            best_dist = d
            best_idx = i
    return best_idx


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def compute_detours(
    coords: list[tuple],
    max_detour_m: int = 500,
    top_n: int = 3,
) -> list[dict]:
    """
    Find the most worthwhile detours along a route.

    coords:       decoded route coordinates [(lat, lon), ...]
    max_detour_m: only consider POIs within this distance of the route
    top_n:        return at most this many detours

    Returns list of detour dicts, sorted by worth_it_score descending.
    """
    if not coords or len(coords) < 2:
        return []

    # Slightly wider bbox than enrichment corridor — we're looking further off path
    bbox = coords_bbox(coords, buffer_deg=max_detour_m / 111_000 + 0.002)
    elements = _fetch_overpass_raw(bbox)

    if not elements:
        return []

    pois = _build_pois(elements, coords, corridor_m=max_detour_m)

    # Exclude things that are too close (already on-route, not a detour)
    MIN_DETOUR_M = 30
    pois = [p for p in pois if p["distance_from_route_m"] >= MIN_DETOUR_M]

    # Exclude categories that aren't worth a detour
    WORTHWHILE_CATEGORIES = {"landmark", "historic", "museum", "nature", "cafe", "park"}
    pois = [p for p in pois if p["category"] in WORTHWHILE_CATEGORIES]

    # Score and filter
    scored = []
    for poi in pois:
        dist_m = poi["distance_from_route_m"]
        category = poi["category"]
        extra_min = _detour_minutes(dist_m)
        max_ok = _MAX_DETOUR_MINUTES.get(category, 5)

        if extra_min > max_ok:
            continue

        score = _worth_it_score(category, dist_m)
        if score <= 0:
            continue

        # Find where on the route this detour branches from
        route_idx = _nearest_route_index(poi["lat"], poi["lon"], coords)
        # Rough progress % along the route
        progress_pct = round(route_idx / max(len(coords) - 1, 1) * 100)

        scored.append({
            "name": poi["name"],
            "category": poi["category"],
            "emoji": poi["emoji"],
            "lat": poi["lat"],
            "lon": poi["lon"],
            "distance_from_route_m": dist_m,
            "extra_minutes": extra_min,
            "worth_it_score": score,
            "route_progress_pct": progress_pct,
            "label": f"+{extra_min:.0f} min · {poi['name']}",
            **({"cuisine": poi["cuisine"]} if "cuisine" in poi else {}),
        })

    scored.sort(key=lambda x: x["worth_it_score"], reverse=True)
    return scored[:top_n]
