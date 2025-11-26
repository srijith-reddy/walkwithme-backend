import requests
import numpy as np
import time

# ============================================================
# 1. Batch elevation fetching (100 coords/request, with retries)
# ============================================================
def fetch_batch_elevation(coords, retries=3):
    """
    coords = [(lat, lon), ...]
    Returns list of elevations (meters).
    Uses OpenElevation API batch endpoint.
    Retries intelligently when API rate-limits.
    """

    if not coords:
        return []

    locations_param = "|".join([f"{lat},{lon}" for lat, lon in coords])
    url = f"https://api.open-elevation.com/api/v1/lookup?locations={locations_param}"

    for attempt in range(retries):
        try:
            res = requests.get(url, timeout=4)
            if res.status_code == 200:
                data = res.json()
                return [item["elevation"] for item in data["results"]]

        except Exception:
            pass

        # Retry (OpenElevation rate-limits often)
        time.sleep(0.4 * (attempt + 1))

    # FAIL SAFE: return 0 for all values
    return [0] * len(coords)


# ============================================================
# 2. Full elevation profile for a route
# ============================================================
def get_elevation_profile(coords):
    """
    coords: list[(lat, lon)]
    Fetch elevation in batches of 100.
    Returns smoothed elevation list.
    """
    batch_size = 100
    elevations = []

    for i in range(0, len(coords), batch_size):
        chunk = coords[i:i + batch_size]
        elevs = fetch_batch_elevation(chunk)
        elevations.extend(elevs)

    elevations = [e if e is not None else 0 for e in elevations]

    return smooth_elevation(elevations)


# ============================================================
# 3. Smooth elevation signal (reduces noise)
# ============================================================
def smooth_elevation(elev):
    """
    Simple moving average smoothing.
    Reduces noise without removing steep slopes.
    """
    elev = np.array(elev, dtype=float)
    kernel = np.array([0.25, 0.5, 0.25])
    smoothed = np.convolve(elev, kernel, mode="same")
    return smoothed.tolist()


# ============================================================
# 4. Gain & loss (meters)
# ============================================================
def compute_gain_loss(elev):
    gain = 0
    loss = 0

    for i in range(1, len(elev)):
        diff = elev[i] - elev[i - 1]
        if diff > 0:
            gain += diff
        else:
            loss += abs(diff)

    return round(gain, 2), round(loss, 2)


# ============================================================
# 5. Slope (grade %) using haversine distance
# ============================================================
def compute_slopes(coords, elev):

    def haversine(lat1, lon1, lat2, lon2):
        R = 6371000
        p1 = np.radians(lat1)
        p2 = np.radians(lat2)
        dlat = np.radians(lat2 - lat1)
        dlon = np.radians(lon2 - lon1)

        a = np.sin(dlat/2)**2 + np.cos(p1) * np.cos(p2) * np.sin(dlon/2)**2
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
        slopes.append(round((diff / dist) * 100, 3))

    return slopes


# ============================================================
# 6. Difficulty score
# ============================================================
def classify_difficulty(gain_m, max_slope):
    if gain_m < 50 and max_slope < 6:
        return "Easy"
    if gain_m < 150 and max_slope < 12:
        return "Moderate"
    if gain_m < 300 and max_slope < 18:
        return "Hard"
    return "Very Hard"


# ============================================================
# 7. Main elevation analyzer
# ============================================================
def analyze_route_elevation(coords):
    """
    coords: [(lat, lon)]
    Output:
        {
          elevations,
          elevation_gain_m,
          elevation_loss_m,
          slopes,
          max_slope_percent,
          difficulty
        }
    """

    if not coords:
        return {
            "elevations": [],
            "elevation_gain_m": 0,
            "elevation_loss_m": 0,
            "slopes": [],
            "max_slope_percent": 0,
            "difficulty": "Easy",
        }

    elev = get_elevation_profile(coords)
    gain, loss = compute_gain_loss(elev)
    slopes = compute_slopes(coords, elev)
    max_slope = max(slopes) if slopes else 0
    difficulty = classify_difficulty(gain, max_slope)

    return {
        "elevations": elev,
        "elevation_gain_m": gain,
        "elevation_loss_m": loss,
        "slopes": slopes,
        "max_slope_percent": max_slope,
        "difficulty": difficulty,
    }
