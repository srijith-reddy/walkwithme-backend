# backend/trails/trail_scorer.py

import numpy as np
from shapely.geometry import LineString
import requests


# ============================================================
# 1. Batch elevation fetcher (Open-Elevation)
# ============================================================
def fetch_batch_elevation(coords):
    """
    coords = [(lat, lon), ...]
    Returns list of elevation values.
    Guaranteed same length as coords.
    """

    if not coords:
        return []

    param = "|".join([f"{lat},{lon}" for lat, lon in coords])
    url = f"https://api.open-elevation.com/api/v1/lookup?locations={param}"

    try:
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        data = r.json()["results"]
        return [item["elevation"] for item in data]
    except:
        # Fail-safe: return zeros
        return [0.0] * len(coords)


# ============================================================
# 2. Elevation gain (batch + smoothing)
# ============================================================
def compute_elevation_gain(geometry: LineString):
    """
    Computes smoothed elevation gain for a trail LineString.
    """

    # Valhalla → Shapely stores coords as (lon, lat)
    coords = [(lat, lon) for lon, lat in geometry.coords]

    # Fetch elevations in chunks
    batch_size = 100
    elevations = []

    for i in range(0, len(coords), batch_size):
        chunk = coords[i:i + batch_size]
        elevations.extend(fetch_batch_elevation(chunk))

    # Simple smoothing kernel
    elev = np.array(elevations, dtype=float)
    kernel = np.array([0.25, 0.5, 0.25])
    smooth = np.convolve(elev, kernel, mode="same")

    # Compute total positive elevation gain
    gain = 0.0
    for i in range(1, len(smooth)):
        diff = smooth[i] - smooth[i - 1]
        if diff > 0:
            gain += diff

    return round(float(gain), 2)


# ============================================================
# 3. Difficulty score (light Naismith rule)
# ============================================================
def score_difficulty(length_m, elevation_gain):
    """
    Difficulty score = km + elevation_gain/100
    """

    diff_value = (length_m / 1000) + (elevation_gain / 100)

    if diff_value < 2:
        level = "Easy"
    elif diff_value < 5:
        level = "Moderate"
    else:
        level = "Hard"

    return level, round(diff_value, 2)


# ============================================================
# 4. Scenic scoring
# ============================================================
def score_scenic(props):
    """
    Simple scoring based on name + surface type.
    """

    scenic = 0
    name = (props.get("name") or "").lower()
    surface = props.get("surface", "")

    if any(k in name for k in ["park", "lake", "river", "creek", "garden", "trail"]):
        scenic += 2

    if surface in ["dirt", "gravel", "ground"]:
        scenic += 1

    if surface == "paved":
        scenic -= 1

    return scenic


# ============================================================
# 5. Safety scoring
# ============================================================
def score_safety(props):
    """
    Surface-based safety heuristic.
    """

    safety = 0
    surface = props.get("surface", "")

    if surface == "paved":
        safety += 2

    if surface in ["dirt", "ground"]:
        safety += 1

    if surface in ["rocky", "loose"]:
        safety -= 1

    return safety


# ============================================================
# 6. MASTER: combine all trail scores
# ============================================================
def score_trails(trails):
    """
    trails = output of find_nearby_trails()
    Each trail dict contains:
      - geometry (LineString)
      - geometry_m
      - properties
      - length_m
      - distance_from_user_m
    """

    results = []

    for t in trails:
        geom = t["geometry"]
        props = t["properties"]
        length_m = t["length_m"]

        # Elevation gain
        elev_gain = compute_elevation_gain(geom)

        # Difficulty
        difficulty_level, difficulty_score = score_difficulty(length_m, elev_gain)

        # Scenic + safety
        scenic_score = score_scenic(props)
        safety_score = score_safety(props)

        # Output record
        results.append({
            "name": props.get("name", "Unnamed Trail"),
            "length_m": round(length_m, 2),
            "distance_from_user_m": t.get("distance_from_user_m"),
            "elevation_gain_m": elev_gain,
            "difficulty_level": difficulty_level,
            "difficulty_score": difficulty_score,
            "scenic_score": scenic_score,
            "safety_score": safety_score,
            "geometry_coords": [(lat, lon) for lon, lat in geom.coords]
        })

    # Sort by best “experience”:
    # 1. Low difficulty score (easier first)
    # 2. High scenic
    # 3. High safety
    results.sort(
        key=lambda tr: (tr["difficulty_score"], -tr["scenic_score"], -tr["safety_score"])
    )

    return results
