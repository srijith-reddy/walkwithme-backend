import requests
import numpy as np
import time
import hashlib

# ============================================================
# GLOBAL IN-MEMORY CACHE (persists during process lifetime)
# ============================================================
ELEV_CACHE = {}   # key: "lat,lon" → elevation (meters)


def cache_key(lat, lon):
    return f"{round(lat, 5)},{round(lon, 5)}"  # avoid micro-differences


# ============================================================
# 1. OpenTopoData (PRIMARY: free, global, stable)
# ============================================================
def fetch_opentopo(coords):
    """
    coords = [(lat, lon), ...]
    Returns list of elevations or None (if fails)
    """
    locations = "|".join([f"{lat},{lon}" for lat, lon in coords])
    url = f"https://api.opentopodata.org/v1/eudem25m?locations={locations}"

    try:
        r = requests.get(url, timeout=4)
        if r.status_code != 200:
            return None
        js = r.json()
        return [pt["elevation"] if pt["elevation"] is not None else 0
                for pt in js.get("results", [])]
    except:
        return None


# ============================================================
# 2. ESRI Elevation API (fallback) — works globally
# ============================================================
def fetch_esri(coords):
    """
    ESRI world elevation service (no key required)
    """
    try:
        url = "https://elevation.arcgis.com/arcgis/rest/services/Tools/ElevationSync/GPServer/Profile/execute"

        features = [{"geometry": {"paths": [[[lon, lat]]]}, "attributes": {}} for lat, lon in coords]

        payload = {
            "InputLineFeatures": {
                "geometryType": "esriGeometryPolyline",
                "features": features
            },
            "returnZ": True,
            "f": "json"
        }

        r = requests.post(url, json=payload, timeout=5)
        if r.status_code != 200:
            return None

        js = r.json()
        out = []
        for feat in js.get("results", []):
            for path in feat.get("value", {}).get("features", []):
                z = path["geometry"]["paths"][0][0][2]
                out.append(z)

        return out if out else None

    except:
        return None


# ============================================================
# 3. USGS Elevation (fallback) — USA only
# ============================================================
def fetch_usgs(coords):
    """
    USA high-quality elevation (USGS)
    """
    out = []
    try:
        for lat, lon in coords:
            url = f"https://nationalmap.gov/epqs/pqs.php?x={lon}&y={lat}&units=Meters&output=json"
            r = requests.get(url, timeout=4).json()
            z = r["USGS_Elevation_Point_Query_Service"]["Elevation_Query"]["Elevation"]
            out.append(z)
        return out
    except:
        return None


# ============================================================
# 4. Fetch elevation for batch (with cache + fallbacks)
# ============================================================
def fetch_batch(coords):
    """
    Tries:
    1) cache
    2) OpenTopoData
    3) ESRI
    4) USGS
    5) zeros
    """
    coords = list(coords)

    # ————— STEP 1: return cached if all found —————
    all_cached = True
    elevations = []
    for lat, lon in coords:
        key = cache_key(lat, lon)
        if key in ELEV_CACHE:
            elevations.append(ELEV_CACHE[key])
        else:
            all_cached = False
            break

    if all_cached:
        return elevations

    # ————— STEP 2: OpenTopoData —————
    res = fetch_opentopo(coords)
    if res:
        for (lat, lon), z in zip(coords, res):
            ELEV_CACHE[cache_key(lat, lon)] = z
        return res

    # ————— STEP 3: ESRI —————
    res = fetch_esri(coords)
    if res:
        for (lat, lon), z in zip(coords, res):
            ELEV_CACHE[cache_key(lat, lon)] = z
        return res

    # ————— STEP 4: USGS (USA only) —————
    res = fetch_usgs(coords)
    if res:
        for (lat, lon), z in zip(coords, res):
            ELEV_CACHE[cache_key(lat, lon)] = z
        return res

    # ————— FINAL FALLBACK: zeros —————
    zeros = [0] * len(coords)
    for (lat, lon) in coords:
        ELEV_CACHE[cache_key(lat, lon)] = 0
    return zeros


# ============================================================
# 5. Get full elevation profile (batching)
# ============================================================
def get_elevation_profile(coords):
    batch_size = 100
    elev = []

    for i in range(0, len(coords), batch_size):
        chunk = coords[i:i+batch_size]
        out = fetch_batch(chunk)
        elev.extend(out)

    return smooth_elevation(elev)


# ============================================================
# 6. Smooth elevation profile
# ============================================================
def smooth_elevation(elev):
    elev = np.array(elev, dtype=float)
    kernel = np.array([1, 2, 4, 2, 1]) / 10
    return np.convolve(elev, kernel, mode="same").tolist()


# ============================================================
# 7. Gain & loss
# ============================================================
def compute_gain_loss(elev):
    gain = 0
    loss = 0
    for i in range(1, len(elev)):
        diff = elev[i] - elev[i - 1]
        if diff > 0:
            gain += diff
        else:
            loss -= diff
    return round(gain, 2), round(loss, 2)


# ============================================================
# 8. Slopes
# ============================================================
def compute_slopes(coords, elev):

    def haversine(lat1, lon1, lat2, lon2):
        R = 6371000
        p1 = np.radians(lat1)
        p2 = np.radians(lat2)
        dlat = np.radians(lat2 - lat1)
        dlon = np.radians(lon2 - lon1)

        a = (np.sin(dlat/2)**2 +
             np.cos(p1)*np.cos(p2)*np.sin(dlon/2)**2)

        return 2 * R * np.arcsin(np.sqrt(a))

    slopes = []

    for i in range(1, len(coords)):
        lat1, lon1 = coords[i - 1]
        lat2, lon2 = coords[i]
        dist = haversine(lat1, lon1, lat2, lon2)

        if dist < 1:
            slopes.append(0)
            continue

        diff = elev[i] - elev[i - 1]
        slopes.append(round((diff / dist) * 100, 3))  # grade %

    return slopes


# ============================================================
# 9. Difficulty classification (walking-specific)
# ============================================================
def classify_difficulty(gain_m, max_slope):
    if gain_m < 40 and max_slope < 5:
        return "Easy"
    if gain_m < 120 and max_slope < 10:
        return "Moderate"
    if gain_m < 250 and max_slope < 15:
        return "Hard"
    return "Very Hard"


# ============================================================
# 10. Main analyzer
# ============================================================
def analyze_route_elevation(coords):
    if not coords:
        return {
            "elevations": [],
            "elevation_gain_m": 0,
            "elevation_loss_m": 0,
            "slopes": [],
            "max_slope_percent": 0,
            "difficulty": "Easy"
        }

    elev = get_elevation_profile(coords)
    gain, loss = compute_gain_loss(elev)
    slopes = compute_slopes(coords, elev)
    max_slope = max(abs(s) for s in slopes) if slopes else 0
    diff = classify_difficulty(gain, max_slope)

    return {
        "elevations": elev,
        "elevation_gain_m": gain,
        "elevation_loss_m": loss,
        "slopes": slopes,
        "max_slope_percent": max_slope,
        "difficulty": diff
    }
