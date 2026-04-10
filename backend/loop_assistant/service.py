# backend/loop_assistant/service.py
#
# Loop Assistant orchestration layer.
#
# Flow:
#   1. Parse query → ParsedIntent
#   2. Resolve origin (geocode or use user GPS)
#   3. Build candidate specs (theme × duration variations)
#   4. Generate loop candidates in parallel via existing routing stack
#   5. Enrich each candidate in parallel via existing enrichment pipeline
#   6. Deduplicate near-identical routes
#   7. Score and rank remaining candidates
#   8. Build structured LoopAssistantResponse

import uuid
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from backend.routing import get_route
from backend.enrichment import enrich_route
from backend.utils.geo import parse_location, reverse_geocode
from backend.utils.common import haversine
from backend.loop_assistant.intent_parser import ParsedIntent, parse_intent
from backend.loop_assistant.models import (
    LoopAssistantRequest,
    LoopAssistantResponse,
    LoopOption,
    OriginInfo,
    RoutePreview,
)

logger = logging.getLogger("walkwithme.loop_assistant")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Fallback origin used when the query provides no location and user GPS is absent.
# Pick a well-connected, walkable area that works as a demo default.
_OPEN_ENDED_DEFAULT = ("New York City, NY", 40.7549, -73.9840)

# For each inferred duration bucket, the set of actual durations to try.
# Generating candidates at slightly different lengths creates useful diversity.
_DURATION_VARIATIONS: dict[int, list[int]] = {
    15: [15, 20],
    20: [20, 25],
    25: [25, 30],
    30: [25, 35],
    35: [30, 40],
    40: [35, 45],
    45: [40, 50],
    50: [45, 55],
    60: [50, 60],
}

# Complementary themes to inject for variety beyond the primary intent theme.
_COMPLEMENTARY_THEMES: dict[str, list[str]] = {
    "food":     ["coffee", "explore"],
    "coffee":   ["food", "explore"],
    "scenic":   ["parks", "landmark"],
    "landmark": ["scenic", "history"],
    "history":  ["landmark", "scenic"],
    "parks":    ["scenic", "explore"],
    "explore":  ["scenic", "food"],
}

# Scoring weights for each ranked dimension
_W_THEME_MATCH     = 20.0
_W_THEME_ADJACENT  = 10.0
_W_POI_RICHNESS    = 1.5     # per POI, capped at 15
_W_POI_SEEDED      = 5.0
_W_CATEGORY_BONUS  = 2.0     # per matching-category POI
_W_CAFE_BONUS      = 3.0     # stronger signal for coffee theme
_W_DURATION_PENALTY = 0.5   # per minute off target
_W_DIST_ACCURACY   = 5.0     # full score when loop hits target distance exactly

# Deduplication thresholds
_DEDUP_CENTROID_M  = 300     # max metres between midpoints to be considered a dupe
_DEDUP_LENGTH_RATIO = 0.25   # max fractional length difference to be considered a dupe

# Theme → human-readable title
_THEME_TITLES: dict[str, str] = {
    "food":     "Food Discovery Loop",
    "coffee":   "Coffee Shop Loop",
    "scenic":   "Scenic Loop",
    "landmark": "Landmark Loop",
    "history":  "Historic Walk",
    "parks":    "Green Loop",
    "explore":  "Explore Loop",
}

# Theme → boilerplate "why this" sentence
_THEME_WHY_BASE: dict[str, str] = {
    "food":     "Routes through the best restaurants and local food spots nearby.",
    "coffee":   "Passes independent cafes and bakeries along the way.",
    "scenic":   "Chosen for scenery — waterfronts, parks, and beautiful streets.",
    "landmark": "Takes in the iconic spots and views that define this area.",
    "history":  "Passes monuments, heritage buildings, and historic sites.",
    "parks":    "Routes through green spaces and parks for a restorative walk.",
    "explore":  "A discovery route through lively streets and interesting corners.",
}


# ---------------------------------------------------------------------------
# Candidate spec
# ---------------------------------------------------------------------------

@dataclass
class _CandidateSpec:
    theme: str
    duration_min: int
    label: str   # debug / tracing label only


def _build_candidate_specs(intent: ParsedIntent, max_options: int) -> list[_CandidateSpec]:
    """
    Build a list of candidate specs for parallel generation.

    Strategy:
      - Primary theme × 2 duration variants  (ensures we have at least 2 options on theme)
      - Up to 2 complementary themes × primary duration  (diversity)
      - 1 wildcard at a longer duration  (range variety)

    We generate max_options + 2 specs to account for routing failures and dedup drops.
    """
    budget = max_options + 2
    specs: list[_CandidateSpec] = []

    durations = _DURATION_VARIATIONS.get(intent.duration_min, [intent.duration_min, intent.duration_min + 10])

    # Primary theme at two durations
    for dur in durations[:2]:
        specs.append(_CandidateSpec(
            theme=intent.theme,
            duration_min=dur,
            label=f"{intent.theme}_{dur}min",
        ))

    # Complementary themes
    for comp_theme in _COMPLEMENTARY_THEMES.get(intent.theme, ["explore", "scenic"])[:2]:
        if len(specs) >= budget:
            break
        specs.append(_CandidateSpec(
            theme=comp_theme,
            duration_min=durations[0],
            label=f"{comp_theme}_{durations[0]}min",
        ))

    # Wildcard: different theme at a longer duration for range variety
    if len(specs) < budget:
        wildcard_theme = "scenic" if intent.theme != "scenic" else "explore"
        wildcard_dur = durations[-1] + 10 if durations else intent.duration_min + 15
        specs.append(_CandidateSpec(
            theme=wildcard_theme,
            duration_min=wildcard_dur,
            label=f"{wildcard_theme}_{wildcard_dur}min_wildcard",
        ))

    return specs


# ---------------------------------------------------------------------------
# Origin resolution
# ---------------------------------------------------------------------------

def _resolve_origin(
    intent: ParsedIntent,
    user_lat: float | None,
    user_lon: float | None,
) -> tuple[float, float, str, str]:
    """
    Returns (lat, lon, display_label, origin_type).

    Priority:
      1. Location extracted from query (station or area)
      2. User GPS coordinates
      3. Open-ended walkable default
    """
    if intent.location_hint:
        try:
            lat, lon = parse_location(intent.location_hint)
            label = _short_label(intent.location_hint)
            return lat, lon, label, intent.query_type
        except Exception:
            logger.warning("Failed to geocode '%s', falling back", intent.location_hint)

    if user_lat is not None and user_lon is not None:
        label = _reverse_label(user_lat, user_lon)
        return user_lat, user_lon, label, "user_location"

    default_label, default_lat, default_lon = _OPEN_ENDED_DEFAULT
    return default_lat, default_lon, default_label, "default"


def _short_label(hint: str) -> str:
    """Title-case the raw hint as the display label."""
    return hint.title()


def _reverse_label(lat: float, lon: float) -> str:
    """Reverse geocode + extract first two address components."""
    try:
        full = reverse_geocode(lat, lon)
        parts = [p.strip() for p in full.split(",")]
        return ", ".join(parts[:2])
    except Exception:
        return f"{round(lat, 4)}, {round(lon, 4)}"


# ---------------------------------------------------------------------------
# Candidate generation
# ---------------------------------------------------------------------------

def _generate_one(lat: float, lon: float, spec: _CandidateSpec) -> dict | None:
    """Call existing loop routing for one spec. Returns None on failure."""
    try:
        result = get_route(
            (lat, lon),
            None,
            mode="loop",
            duration_minutes=spec.duration_min,
            loop_theme=spec.theme,
        )
        if "error" in result or not result.get("coordinates"):
            return None
        result["_spec_theme"] = spec.theme
        result["_spec_duration"] = spec.duration_min
        return result
    except Exception:
        logger.exception("Candidate generation failed for spec %s", spec.label)
        return None


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

_EMPTY_ENRICHMENT: dict = {
    "landmarks": [],
    "food":      [],
    "parks":     [],
    "highlights": [],
    "summary": "",
    "neighborhood_flavor": {"label": "Urban Walk", "emoji": "🏙️", "description": ""},
    "poi_count": 0,
}


def _enrich_one(candidate: dict) -> dict:
    """Attach enrichment to a candidate. Returns candidate (enrichment may be empty on failure)."""
    coords = candidate.get("coordinates", [])
    if not coords:
        candidate["enrichment"] = dict(_EMPTY_ENRICHMENT)
        return candidate
    try:
        candidate["enrichment"] = enrich_route(coords)
    except Exception:
        logger.warning("Enrichment failed for candidate; continuing without POIs")
        candidate["enrichment"] = dict(_EMPTY_ENRICHMENT)
    return candidate


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _midpoint(coords: list) -> tuple[float, float]:
    mid = coords[len(coords) // 2]
    return mid[0], mid[1]


def _deduplicate(candidates: list[dict]) -> list[dict]:
    """
    Remove near-duplicate loops.

    Two routes are duplicates if:
      - Their geometric midpoints are within _DEDUP_CENTROID_M metres, AND
      - Their loop lengths differ by less than _DEDUP_LENGTH_RATIO fraction.
    """
    unique: list[dict] = []

    for candidate in candidates:
        coords = candidate.get("coordinates", [])
        if not coords:
            continue

        c_lat, c_lon = _midpoint(coords)
        c_km = candidate.get("loop_km", 0.0)

        is_dup = False
        for existing in unique:
            e_coords = existing.get("coordinates", [])
            if not e_coords:
                continue
            e_lat, e_lon = _midpoint(e_coords)
            e_km = existing.get("loop_km", 0.0)

            dist_m = haversine(c_lat, c_lon, e_lat, e_lon) * 1000
            len_ratio = abs(c_km - e_km) / max(c_km, e_km, 0.1)

            if dist_m < _DEDUP_CENTROID_M and len_ratio < _DEDUP_LENGTH_RATIO:
                is_dup = True
                break

        if not is_dup:
            unique.append(candidate)

    return unique


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score(candidate: dict, intent: ParsedIntent) -> float:
    """Score a candidate route for ranking. Higher is better."""
    score = 0.0
    enrichment = candidate.get("enrichment", _EMPTY_ENRICHMENT)
    theme = candidate.get("_spec_theme", "")

    # --- Theme alignment ---
    if theme == intent.theme:
        score += _W_THEME_MATCH
    elif theme in _COMPLEMENTARY_THEMES.get(intent.theme, []):
        score += _W_THEME_ADJACENT

    # --- POI richness ---
    poi_count = enrichment.get("poi_count", 0)
    score += min(poi_count * _W_POI_RICHNESS, 15.0)

    # --- Category-specific bonus based on intent theme ---
    if intent.theme == "food":
        food_pois = len(enrichment.get("food", []))
        score += food_pois * _W_CATEGORY_BONUS
    elif intent.theme == "coffee":
        cafe_pois = sum(1 for p in enrichment.get("food", []) if p.get("category") == "cafe")
        score += cafe_pois * _W_CAFE_BONUS
    elif intent.theme in ("scenic", "parks"):
        park_pois = len(enrichment.get("parks", []))
        score += park_pois * _W_CATEGORY_BONUS
    elif intent.theme in ("landmark", "history"):
        landmark_pois = len(enrichment.get("landmarks", []))
        score += landmark_pois * _W_CATEGORY_BONUS

    # --- POI-seeded quality bonus ---
    if candidate.get("poi_seeded", False):
        score += _W_POI_SEEDED

    # --- Duration match ---
    spec_dur = candidate.get("_spec_duration", intent.duration_min)
    score -= abs(spec_dur - intent.duration_min) * _W_DURATION_PENALTY

    # --- Target distance accuracy ---
    loop_km = candidate.get("loop_km", 0.0)
    target_km = candidate.get("target_km", loop_km)
    if target_km > 0:
        accuracy = 1.0 - min(abs(loop_km - target_km) / target_km, 1.0)
        score += accuracy * _W_DIST_ACCURACY

    return score


# ---------------------------------------------------------------------------
# Response construction
# ---------------------------------------------------------------------------

def _km_to_miles(km: float) -> float:
    return round(km * 0.621371, 2)


def _build_subtitle(candidate: dict, enrichment: dict) -> str:
    """Short, scannable subtitle derived from highlights or route stats."""
    highlights = enrichment.get("highlights", [])
    if len(highlights) >= 2:
        # Strip emoji prefix to get clean names: "☕ Joe's Coffee" → "Joe's Coffee"
        names = [h.split(" ", 1)[1] if " " in h else h for h in highlights[:2]]
        return " → ".join(names) + " → back"
    if len(highlights) == 1:
        name = highlights[0].split(" ", 1)[1] if " " in highlights[0] else highlights[0]
        return f"via {name}"

    dur_min = round(candidate.get("duration_s", 0) / 60) or candidate.get("_spec_duration", "?")
    km = candidate.get("loop_km", 0)
    return f"{dur_min} min · {km:.1f} km loop"


def _build_why_this(candidate: dict, intent: ParsedIntent, enrichment: dict) -> str:
    """Single-paragraph explanation of why this option was chosen."""
    parts: list[str] = []

    base = _THEME_WHY_BASE.get(candidate.get("_spec_theme", ""), "A solid walking loop.")
    parts.append(base)

    flavor = enrichment.get("neighborhood_flavor", {})
    flavor_label = flavor.get("label", "")
    if flavor_label and flavor_label not in ("Urban Walk",):
        parts.append(f"Neighborhood character: {flavor_label}.")

    poi_count = enrichment.get("poi_count", 0)
    if poi_count > 0:
        parts.append(f"{poi_count} point{'s' if poi_count != 1 else ''} of interest along the route.")

    if candidate.get("poi_seeded", False):
        parts.append("Route passes real landmarks found in this area.")

    return " ".join(parts)


def _build_option(candidate: dict, intent: ParsedIntent) -> LoopOption:
    enrichment = candidate.get("enrichment", dict(_EMPTY_ENRICHMENT))
    theme = candidate.get("_spec_theme", "explore")

    duration_s = candidate.get("duration_s", candidate.get("_spec_duration", 35) * 60)
    duration_min = max(1, round(duration_s / 60))
    loop_km = candidate.get("loop_km", 0.0)

    # Suggested stops: up to 4 closest POIs across all categories
    all_pois = (
        enrichment.get("landmarks", [])
        + enrichment.get("food", [])
        + enrichment.get("parks", [])
    )
    all_pois.sort(key=lambda p: p.get("distance_from_route_m", 999))
    suggested_stops = [
        {
            "name": p["name"],
            "category": p["category"],
            "emoji": p.get("emoji", "📌"),
            "lat": p["lat"],
            "lon": p["lon"],
        }
        for p in all_pois[:4]
    ]

    flavor = enrichment.get("neighborhood_flavor", {})
    neighborhood_character = (
        flavor.get("description")
        or flavor.get("label")
        or ""
    )

    coords = candidate.get("coordinates", [])
    # Waypoints: existing simplified set (every 8th point) — AR anchor resolution
    waypoints = candidate.get("waypoints", coords[::8] if len(coords) > 8 else coords)
    # Geometry preview: every 4th point is sufficient for a map polyline
    preview_geometry = coords[::4] if len(coords) > 4 else coords

    return LoopOption(
        id=uuid.uuid4().hex[:8],
        title=_THEME_TITLES.get(theme, "Walking Loop"),
        subtitle=_build_subtitle(candidate, enrichment),
        theme=theme,
        route_style=candidate.get("_spec_route_style", intent.route_style),
        duration_min=duration_min,
        distance_miles=_km_to_miles(loop_km),
        why_this=_build_why_this(candidate, intent, enrichment),
        highlights=enrichment.get("highlights", []),
        neighborhood_character=neighborhood_character,
        suggested_stops=suggested_stops,
        route_preview=RoutePreview(
            geometry=preview_geometry,
            waypoints=waypoints,
        ),
    )


def _build_summary(options: list[LoopOption], intent: ParsedIntent, origin_label: str) -> str:
    if not options:
        return (
            f"No loops could be generated near {origin_label}. "
            "Try a different location or a shorter duration."
        )

    count = len(options)
    # Unique themes in result order (preserve first occurrence)
    seen_themes: list[str] = []
    for o in options:
        if o.theme not in seen_themes:
            seen_themes.append(o.theme)

    dur_min = min(o.duration_min for o in options)
    dur_max = max(o.duration_min for o in options)
    dur_str = f"{dur_min}–{dur_max} min" if dur_min != dur_max else f"{dur_min} min"

    theme_names = [_THEME_TITLES.get(t, t) for t in seen_themes[:2]]
    theme_str = " and ".join(theme_names)

    return (
        f"{count} loop{'s' if count > 1 else ''} near {origin_label} — "
        f"{theme_str}, {dur_str} each. "
        "All start and end at the same point."
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_loop_assistant(request: LoopAssistantRequest) -> dict:
    """
    Main entry point called by the /loop_assistant endpoint.
    Returns a plain dict suitable for FastAPI JSON serialization.
    """
    intent = parse_intent(request.query)

    logger.info(
        "loop_assistant: query=%r type=%s theme=%s dur=%d location=%r",
        request.query, intent.query_type, intent.theme,
        intent.duration_min, intent.location_hint,
    )

    # 1. Resolve origin
    lat, lon, label, origin_type = _resolve_origin(intent, request.user_lat, request.user_lon)
    logger.info("loop_assistant: origin=%s (%.4f, %.4f) type=%s", label, lat, lon, origin_type)

    # 2. Build candidate specs
    specs = _build_candidate_specs(intent, request.max_options)

    # 3. Generate candidates in parallel
    raw_candidates: list[dict] = []
    with ThreadPoolExecutor(max_workers=min(len(specs), 5)) as ex:
        futures = {ex.submit(_generate_one, lat, lon, spec): spec for spec in specs}
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                raw_candidates.append(result)

    logger.info("loop_assistant: %d raw candidates generated", len(raw_candidates))

    if not raw_candidates:
        origin_info = OriginInfo(label=label, lat=lat, lon=lon, origin_type=origin_type)
        return LoopAssistantResponse(
            origin=origin_info,
            assistant_summary=(
                f"Could not generate any loops near {label}. "
                "Try a different location or a shorter distance."
            ),
            options=[],
        ).model_dump()

    # 4. Enrich all candidates in parallel
    with ThreadPoolExecutor(max_workers=min(len(raw_candidates), 5)) as ex:
        enriched = list(ex.map(_enrich_one, raw_candidates))

    # 5. Deduplicate
    unique = _deduplicate(enriched)
    logger.info("loop_assistant: %d unique candidates after dedup", len(unique))

    # 6. Score and rank
    ranked = sorted(unique, key=lambda c: _score(c, intent), reverse=True)

    # 7. Take top N
    top = ranked[: request.max_options]

    # 8. Build structured response
    options = [_build_option(c, intent) for c in top]

    origin_info = OriginInfo(label=label, lat=lat, lon=lon, origin_type=origin_type)
    response = LoopAssistantResponse(
        origin=origin_info,
        assistant_summary=_build_summary(options, intent, label),
        options=options,
    )

    return response.model_dump()
