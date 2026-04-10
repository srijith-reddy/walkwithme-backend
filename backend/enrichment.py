# backend/enrichment.py
#
# Route enrichment pipeline — Overpass API (free, OSM-backed, no key required).
#
# Returns landmarks, food, parks, neighborhood flavor, highlights, and summary
# for a given route or location.

import requests
from backend.config import (
    OVERPASS_URL,
    OVERPASS_TIMEOUT,
    ENRICHMENT_CORRIDOR_M,
    ENRICHMENT_MAX_LANDMARKS,
    ENRICHMENT_MAX_FOOD,
)
from backend.utils.common import coords_bbox, point_to_route_distance_m, haversine
from backend.cache import overpass_cache, overpass_key


# ---------------------------------------------------------------------------
# Overpass query
# ---------------------------------------------------------------------------
def _build_overpass_query(bbox: dict) -> str:
    s, n = bbox["min_lat"], bbox["max_lat"]
    w, e = bbox["min_lon"], bbox["max_lon"]
    bb = f"{s},{w},{n},{e}"
    return f"""
[out:json][timeout:{OVERPASS_TIMEOUT}];
(
  node["tourism"~"^(attraction|museum|viewpoint|artwork|monument|gallery|theme_park|zoo|aquarium)$"]({bb});
  node["historic"~"^(monument|memorial|building|ruins|castle|church|site|fort|manor|palace|tower)$"]({bb});
  node["amenity"~"^(cafe|bakery|restaurant|ice_cream|fast_food|bar|pub)$"]["name"]({bb});
  node["leisure"~"^(park|garden|nature_reserve|marina|beach_resort)$"]["name"]({bb});
  node["natural"~"^(peak|viewpoint|beach|bay|spring)$"]["name"]({bb});
);
out body;
""".strip()


def _fetch_overpass_raw(bbox: dict) -> list[dict]:
    """Fetch from Overpass with cache layer."""
    key = overpass_key(bbox)
    cached = overpass_cache.get(key)
    if cached is not None:
        return cached

    query = _build_overpass_query(bbox)
    try:
        r = requests.post(
            OVERPASS_URL,
            data={"data": query},
            timeout=OVERPASS_TIMEOUT + 2,
            headers={"User-Agent": "WalkWithMe/2.0"},
        )
        if r.status_code != 200:
            return []
        elements = r.json().get("elements", [])
    except Exception:
        elements = []

    overpass_cache.set(key, elements)
    return elements


# ---------------------------------------------------------------------------
# Categorization
# ---------------------------------------------------------------------------
def _categorize(tags: dict) -> str:
    amenity = tags.get("amenity", "")
    tourism = tags.get("tourism", "")
    historic = tags.get("historic", "")
    leisure = tags.get("leisure", "")
    natural = tags.get("natural", "")

    if amenity in ("cafe", "bakery", "ice_cream"):
        return "cafe"
    if amenity in ("restaurant", "fast_food"):
        return "restaurant"
    if amenity in ("bar", "pub"):
        return "bar"
    if tourism in ("museum", "gallery", "aquarium", "zoo", "theme_park"):
        return "museum"
    if tourism in ("attraction", "monument", "artwork", "viewpoint"):
        return "landmark"
    if historic:
        return "historic"
    if leisure in ("park", "garden", "nature_reserve"):
        return "park"
    if natural in ("peak", "beach", "bay", "viewpoint"):
        return "nature"
    return "other"


_EMOJI = {
    "cafe": "☕", "restaurant": "🍽️", "bar": "🍺",
    "museum": "🏛️", "landmark": "📍", "historic": "🏛️",
    "park": "🌳", "nature": "⛰️", "other": "📌",
}


# ---------------------------------------------------------------------------
# Build POI list from Overpass elements
# ---------------------------------------------------------------------------
def _build_pois(elements: list[dict], coords: list[tuple], corridor_m: int) -> list[dict]:
    pois = []
    seen: set = set()

    for el in elements:
        if el.get("type") != "node":
            continue
        osm_id = el.get("id")
        if osm_id in seen:
            continue

        tags = el.get("tags", {})
        name = tags.get("name") or tags.get("name:en") or tags.get("brand")
        if not name:
            continue

        lat, lon = el.get("lat"), el.get("lon")
        if lat is None or lon is None:
            continue

        dist_m = point_to_route_distance_m(lat, lon, coords, sample_every=4)
        if dist_m > corridor_m:
            continue

        seen.add(osm_id)
        category = _categorize(tags)
        poi: dict = {
            "name": name,
            "category": category,
            "emoji": _EMOJI.get(category, "📌"),
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "distance_from_route_m": int(dist_m),
        }
        if tags.get("cuisine"):
            poi["cuisine"] = tags["cuisine"]
        if tags.get("opening_hours"):
            poi["opening_hours"] = tags["opening_hours"]
        if tags.get("website"):
            poi["website"] = tags["website"]
        pois.append(poi)

    return pois


# ---------------------------------------------------------------------------
# Neighborhood flavor
# ---------------------------------------------------------------------------
_FLAVOR_MAP = [
    (lambda l, f, p: len(f) >= 5,                       "Foodie",        "🍽️", "A walk with serious eating potential."),
    (lambda l, f, p: len([x for x in f if x["category"] == "cafe"]) >= 3,
                                                          "Coffee Culture", "☕", "Independent cafes and bakeries around every corner."),
    (lambda l, f, p: len(p) >= 3,                        "Green & Scenic", "🌳", "Parks and green spaces all along the route."),
    (lambda l, f, p: len([x for x in l if x["category"] in ("historic", "museum")]) >= 3,
                                                          "Historic",       "🏛️", "Rich in history — architecture, monuments, and heritage sites."),
    (lambda l, f, p: len(l) >= 3,                        "Cultural",       "📍", "Landmarks and cultural touchpoints throughout."),
]

_DEFAULT_FLAVOR = ("Urban Walk", "🏙️", "A city walk through the neighbourhood.")


def _get_neighborhood_flavor(landmarks: list, food: list, parks: list) -> dict:
    for condition, label, emoji, description in _FLAVOR_MAP:
        if condition(landmarks, food, parks):
            return {"label": label, "emoji": emoji, "description": description}
    label, emoji, description = _DEFAULT_FLAVOR
    return {"label": label, "emoji": emoji, "description": description}


# ---------------------------------------------------------------------------
# Narrative summary (template-based — deterministic, no LLM)
# ---------------------------------------------------------------------------
def _build_summary(landmarks: list, food: list, parks: list) -> str:
    parts = []
    if landmarks:
        names = [p["name"] for p in landmarks[:3]]
        if len(names) == 1:
            parts.append(f"You'll pass {names[0]}")
        elif len(names) == 2:
            parts.append(f"You'll pass {names[0]} and {names[1]}")
        else:
            parts.append(f"You'll pass {names[0]}, {names[1]}, and {names[2]}")
    if food:
        names = [p["name"] for p in food[:2]]
        verb = "are" if len(names) > 1 else "is"
        parts.append(f"{' and '.join(names)} {verb} right along the route")
    if parks:
        parts.append(f"passes through {parks[0]['name']}")
    if not parts:
        return "An urban walk through the area."
    return ". ".join(parts).capitalize() + "."


def _build_highlights(landmarks: list, food: list, parks: list) -> list[str]:
    highlights = []
    for p in landmarks[:3]:
        highlights.append(f"{p['emoji']} {p['name']}")
    for p in food[:2]:
        highlights.append(f"{p['emoji']} {p['name']}")
    for p in parks[:1]:
        highlights.append(f"{p['emoji']} {p['name']}")
    return highlights


# ---------------------------------------------------------------------------
# Public: route enrichment
# ---------------------------------------------------------------------------
def enrich_route(coords: list[tuple]) -> dict:
    """Enrich a route with POIs, flavor, highlights, and summary."""
    if not coords or len(coords) < 2:
        return _empty()

    bbox = coords_bbox(coords, buffer_deg=0.003)
    elements = _fetch_overpass_raw(bbox)

    if not elements:
        return _empty()

    pois = _build_pois(elements, coords, ENRICHMENT_CORRIDOR_M)

    landmarks = sorted(
        [p for p in pois if p["category"] in ("landmark", "historic", "museum", "nature")],
        key=lambda p: p["distance_from_route_m"],
    )[:ENRICHMENT_MAX_LANDMARKS]

    food = sorted(
        [p for p in pois if p["category"] in ("cafe", "restaurant", "bar")],
        key=lambda p: p["distance_from_route_m"],
    )[:ENRICHMENT_MAX_FOOD]

    parks = sorted(
        [p for p in pois if p["category"] == "park"],
        key=lambda p: p["distance_from_route_m"],
    )[:4]

    flavor = _get_neighborhood_flavor(landmarks, food, parks)
    summary = _build_summary(landmarks, food, parks)
    highlights = _build_highlights(landmarks, food, parks)

    return {
        "landmarks": landmarks,
        "food": food,
        "parks": parks,
        "highlights": highlights,
        "summary": summary,
        "neighborhood_flavor": flavor,
        "poi_count": len(landmarks) + len(food) + len(parks),
    }


def _empty() -> dict:
    return {
        "landmarks": [], "food": [], "parks": [],
        "highlights": [], "summary": "",
        "neighborhood_flavor": {"label": "Urban Walk", "emoji": "🏙️", "description": ""},
        "poi_count": 0,
    }


# ---------------------------------------------------------------------------
# Public: nearby discovery
# ---------------------------------------------------------------------------
def find_nearby(
    lat: float, lon: float, radius_m: int = 500, category: str = "all"
) -> list[dict]:
    buffer_deg = radius_m / 111_000
    bbox = {
        "min_lat": lat - buffer_deg, "max_lat": lat + buffer_deg,
        "min_lon": lon - buffer_deg, "max_lon": lon + buffer_deg,
    }
    elements = _fetch_overpass_raw(bbox)
    if not elements:
        return []

    pois = _build_pois(elements, [(lat, lon)], corridor_m=radius_m)

    if category == "food":
        pois = [p for p in pois if p["category"] in ("cafe", "restaurant", "bar")]
    elif category == "landmark":
        pois = [p for p in pois if p["category"] in ("landmark", "historic", "museum")]
    elif category == "park":
        pois = [p for p in pois if p["category"] in ("park", "nature")]

    return sorted(pois, key=lambda p: p["distance_from_route_m"])[:20]


# ---------------------------------------------------------------------------
# Public: POI seeding for loop generation
# ---------------------------------------------------------------------------
def get_pois_for_loop_theme(
    lat: float, lon: float, theme: str, radius_m: int = 900
) -> list[dict]:
    """
    Return POIs near (lat, lon) that match the given loop theme.
    Used by routing_ai.py to seed loop midpoints with real destinations.
    """
    _THEME_CATEGORIES = {
        "coffee":   lambda p: p["category"] == "cafe",
        "food":     lambda p: p["category"] in ("cafe", "restaurant"),
        "landmark": lambda p: p["category"] in ("landmark", "historic", "museum"),
        "history":  lambda p: p["category"] in ("historic", "museum", "landmark"),
        "scenic":   lambda p: p["category"] in ("park", "nature", "landmark"),
        "parks":    lambda p: p["category"] in ("park", "nature"),
        "art":      lambda p: p["category"] in ("museum", "landmark"),
        "explore":  lambda p: True,
    }

    filter_fn = _THEME_CATEGORIES.get(theme, lambda p: True)
    pois = find_nearby(lat, lon, radius_m=radius_m, category="all")
    return [p for p in pois if filter_fn(p)]
