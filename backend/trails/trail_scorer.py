# backend/trails/trail_scorer.py

import numpy as np
from shapely.geometry import LineString
import requests
import time


# ============================================================
# 1. Safe elevation fetcher (tries OpenTopoData → OpenElevation)
# ============================================================
def fetch_batch_elevation(coords):
    """
    coords: [(lat, lon)]
    Returns elevation list (same length).
    """

    if not coords:
        return []

    # Format: lat,lon|lat,lon|...
    loc = "|".join([f"{lat},{lon}" for lat, lon in coords])

    # --------------------------------------
    # Primary: OpenTopoData (BEST OPTION)
    # --------------------------------------
    topo_url = f"https://api.opentopodata.org/v1/eudem25m?locations={loc}"

    try:
        r = requests.get(topo_url, timeout=4)
        if r.status_code == 200:
            js = r.json()
            if "results" in js:
                elev = [x.get("elevation", 0.0) for x in js["results"]]
                return elev
    except:
        pass

    # --------------------------------------
    # Fallback: OpenElevation
    # --------------------------------------
    elev_url = f"https://api.open-elevation.com/api/v1/lookup?locations={loc}"

    for attempt in range(3):
        try:
            r = requests.get(elev_url, timeout=4)
            if r.status_code == 200:
                js = r.json()
                if "results" in js:
                    return [item.get("elevation", 0.0) for item in js["results"]]
        except:
            pass

        time.sleep(0.3 * (attempt + 1))

    # Fail-safe: flat ground
    return [0.0] * len(coords)


# ============================================================
# 2. Compute elevation gain on trail geometry
# ============================================================
def compute_elevation_gain(geometry: LineString):
    """
    geometry.coords = [(lon, lat), ...]
    Convert → (lat, lon) for API.
    """

    # FIXED coordinate order:
    coords = [(lat, lon) for lon, lat in geometry.coords]

    elevations = []
    batch_size = 100

    for i in range(0, len(coords), batch_size):
        chunk = coords[i:i+batch_size]
        elevations.extend(fetch_batch_elevation(chunk))

    elev = np.array(elevations, dtype=float)

    # Smooth (reduce noise)
    kernel = np.array([0.25, 0.5, 0.25])
    smooth = np.convolve(elev, kernel, mode="same")

    gain = 0.0
    for i in range(1, len(smooth)):
        diff = smooth[i] - smooth[i-1]
        if diff > 0:
            gain += diff

    return round(float(gain), 2)


# ============================================================
# 3. Difficulty scoring (walk-friendly)
# ============================================================
def score_difficulty(length_m, elevation_gain):
    """
    difficulty_score = km + elevation/100
    """

    score = (length_m / 1000.0) + (elevation_gain / 100.0)

    if score < 2:
        level = "Easy"
    elif score < 5:
        level = "Moderate"
    else:
        level = "Hard"

    return level, round(score, 2)


# ============================================================
# 4. Scenic scoring
# ============================================================
def score_scenic(props):
    scenic = 0
    name = (props.get("name") or "").lower()
    surface = props.get("surface", "")

    if any(key in name for key in ["park", "lake", "river", "creek", "garden", "trail"]):
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
    surface = props.get("surface", "")
    safety = 0

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
    Returns iOS-ready, AllTrails-style trail records.
    """

    import hashlib
    results = []

    for t in trails:
        geom = t["geometry"]                     # Shapely LineString
        props = t["properties"]                  # name, surface, highway/use
        length_m = float(t["length_m"])          # trail length

        # ============================================================
        # Elevation Gain
        # ============================================================
        elev_gain = compute_elevation_gain(geom)

        # ============================================================
        # Difficulty / Scenic / Safety
        # ============================================================
        difficulty_level, difficulty_score = score_difficulty(length_m, elev_gain)
        scenic_score = score_scenic(props)
        safety_score = score_safety(props)

        # ============================================================
        # Geometry coords corrected to [lat, lon]
        # ============================================================
        coords_latlon = [(lat, lon) for lon, lat in geom.coords]

        # ============================================================
        # Stable ID based on geometry
        # ============================================================
        geom_hash = hashlib.sha1(str(coords_latlon).encode()).hexdigest()[:12]
        trail_id = f"trail_{geom_hash}"

        # ============================================================
        # Center point of trail (for map preview)
        # ============================================================
        centroid = geom.centroid
        center_lat = centroid.y
        center_lon = centroid.x

        # ============================================================
        # Estimated time (minutes) using avg walking speed 1.3 m/s
        # ============================================================
        walking_speed_m_s = 1.3
        est_time_min = round((length_m / walking_speed_m_s) / 60)

        # ============================================================
        # Build final iOS-ready record
        # ============================================================
        results.append({
            "id": trail_id,
            "name": props.get("name", "Unnamed Trail"),

            # Map preview anchor
            "center_lat": center_lat,
            "center_lon": center_lon,

            # Metrics
            "length_m": round(length_m, 2),
            "distance_from_user_m": t.get("distance_from_user_m"),
            "elevation_gain_m": elev_gain,
            "difficulty_level": difficulty_level,
            "difficulty_score": difficulty_score,
            "scenic_score": scenic_score,
            "safety_score": safety_score,
            "est_time_min": est_time_min,

            # Geometry (for map overlay + AR)
            "preview_coords": coords_latlon,
            "geometry_coords": coords_latlon,

            # Metadata useful for filters
            "use": props.get("highway", ""),
            "surface": props.get("surface", "unknown"),

            # Optional future tags (can be empty for now)
            "tags": []
        })

    # Sort by difficulty → scenic → safety
    results.sort(
        key=lambda tr: (tr["difficulty_score"], -tr["scenic_score"], -tr["safety_score"])
    )

    return results

