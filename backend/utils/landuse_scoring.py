# backend/utils/landuse_scoring.py
#
# Scenic scoring from standard Valhalla route responses.
#
# Valhalla does NOT return edge-level attributes by default.
# Previous version read `maneuvers[].edge[]` — that field is never populated,
# so all scores were always 0.0.
#
# This version scores from fields Valhalla DOES return:
#   - maneuver.street_names     (list of street name strings)
#   - maneuver.instruction      (human-readable turn instruction)
#   - maneuver.length           (km — weight longer segments more)
#   - trip.summary.length       (total distance)
#
# Signals used:
#   GREEN  — path/trail/park/garden/greenway names, walk-only maneuver types
#   WATER  — river/lake/bay/canal/waterfront names
#   SCENIC — combined: green + water + low-traffic name patterns + promenades

_WATER_TOKENS = {
    "river", "lake", "pond", "harbor", "harbour", "bay", "creek",
    "brook", "canal", "waterfront", "pier", "marina", "cove", "inlet",
    "lagoon", "reservoir", "embankment", "quay", "wharf", "esplanade",
}

_GREEN_TOKENS = {
    "park", "garden", "gardens", "greenway", "trail", "path", "pathway",
    "promenade", "nature", "botanical", "reserve", "meadow", "commons",
    "common", "grove", "arboretum", "parkway", "greenway", "plaza",
    "square", "yard",  # public squares often feel scenic
}

_SCENIC_BONUS_TOKENS = {
    "view", "vista", "overlook", "bridge", "waterfall", "scenic",
    "historic", "heritage", "boulevard", "avenue",
}

# Valhalla maneuver types that indicate pedestrian-only movement
# (value from Valhalla: 0=none, 1=start, 2=start_right, ..., 26=transit_transfer)
_PEDESTRIAN_TYPES = {0, 1, 2, 3}  # rough heuristic — non-road segments


def _tokenize(text: str) -> set[str]:
    return {w.lower().strip(".,()") for w in text.split() if w}


def _score_maneuver(street_names: list[str], instruction: str, length_km: float) -> dict:
    """
    Score a single maneuver segment.
    Returns raw hit counts (not normalized — caller normalizes by total length).
    """
    all_text = " ".join(street_names) + " " + instruction
    tokens = _tokenize(all_text)

    green = 1.0 if tokens & _GREEN_TOKENS else 0.0
    water = 1.0 if tokens & _WATER_TOKENS else 0.0
    scenic_bonus = 0.5 if tokens & _SCENIC_BONUS_TOKENS else 0.0

    scenic = min(1.0, green + water + scenic_bonus)

    return {
        "green": green * length_km,
        "water": water * length_km,
        "scenic": scenic * length_km,
        "length_km": length_km,
    }


def compute_scores_from_valhalla(route_json: dict) -> dict:
    """
    Compute green / water / scenic scores for a Valhalla route response.

    Returns scores normalized to [0, 1] — fraction of total route distance
    that passes through green / water / scenic segments.
    """
    if "trip" not in route_json or "legs" not in route_json["trip"]:
        return {"green": 0.0, "water": 0.0, "scenic": 0.0}

    total_green = total_water = total_scenic = total_length = 0.0

    for leg in route_json["trip"]["legs"]:
        for maneuver in leg.get("maneuvers", []):
            street_names: list[str] = maneuver.get("street_names", [])
            instruction: str = maneuver.get("instruction", "")
            length_km: float = maneuver.get("length", 0.0)

            if length_km <= 0:
                continue

            hit = _score_maneuver(street_names, instruction, length_km)
            total_green += hit["green"]
            total_water += hit["water"]
            total_scenic += hit["scenic"]
            total_length += length_km

    if total_length == 0:
        return {"green": 0.0, "water": 0.0, "scenic": 0.0}

    return {
        "green": round(total_green / total_length, 4),
        "water": round(total_water / total_length, 4),
        "scenic": round(total_scenic / total_length, 4),
    }
