# backend/utils/geo.py

import requests
import time
from fastapi import HTTPException

# Required by Nominatim → avoids IP block
HEADERS = {
    "User-Agent": "WalkWithMe/1.0 (https://github.com/srijith-reddy)"
}

# -------------------------------------------------------------
# Helper: detect if input looks like "lat, lon"
# -------------------------------------------------------------
def looks_like_coords(value: str):
    if "," not in value:
        return False

    parts = [p.strip() for p in value.split(",")]
    if len(parts) != 2:
        return False

    try:
        float(parts[0])
        float(parts[1])
        return True
    except:
        return False


# -------------------------------------------------------------
# Geocode using Nominatim (with retry + cooldown)
# -------------------------------------------------------------
def geocode_nominatim(text: str):
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": text.strip(),
        "format": "json",
        "limit": 1,
        "addressdetails": 1,
    }

    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=5)

            # Rate limit / service unavailable (common)
            if r.status_code in (429, 503):
                time.sleep(1.1)  # Nominatim requires 1 sec delay
                continue

            data = r.json()

            if data:
                lat = float(data[0]["lat"])
                lon = float(data[0]["lon"])
                return (lat, lon)
            else:
                raise HTTPException(404, f"No results for '{text}'")

        except Exception:
            time.sleep(1.1)

    raise HTTPException(503, "Geocoding temporarily unavailable. Try again in 1 minute.")


# -------------------------------------------------------------
# Photon fallback (unlimited, fast)
# -------------------------------------------------------------
def geocode_photon(text: str):
    url = "https://photon.komoot.io/api/"
    params = {"q": text.strip()}

    try:
        r = requests.get(url, params=params, timeout=5)
        data = r.json()

        if "features" in data and len(data["features"]) > 0:
            coords = data["features"][0]["geometry"]["coordinates"]
            lon, lat = coords[0], coords[1]
            return float(lat), float(lon)
    except:
        pass

    raise HTTPException(404, f"No results for '{text}' (Photon fallback failed)")


# -------------------------------------------------------------
# Combined geocode (Nominatim first → Photon fallback)
# -------------------------------------------------------------
def geocode(text: str):
    """
    Try:
      1) Nominatim (strict, accurate)
      2) Photon fallback (fast/unlimited)
    """
    try:
        return geocode_nominatim(text)
    except:
        return geocode_photon(text)


# -------------------------------------------------------------
# Reverse geocode: (lat, lon) → address
# -------------------------------------------------------------
def reverse_geocode(lat: float, lon: float):
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {
        "lat": lat,
        "lon": lon,
        "format": "json",
        "zoom": 16,
        "addressdetails": 1,
    }

    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=5)
        data = r.json()
        return data.get("display_name", "Unknown Location")
    except:
        return "Unknown Location"


# -------------------------------------------------------------
# Parse ANY input → (lat, lon)
# -------------------------------------------------------------
def parse_location(value: str):
    """
    Accepts:
        "40.73,-74.06"
        "Times Square"
        "Crunch Hoboken"
        "Le Leo Jersey City"
        "145 Newark Ave"
    """
    value = value.strip()

    # Direct numeric coordinates
    if looks_like_coords(value):
        lat, lon = value.split(",")
        return float(lat), float(lon)

    # Otherwise → geocode text
    return geocode(value)


# -------------------------------------------------------------
# Safe wrapper → returns None
# -------------------------------------------------------------
def parse_location_safe(value: str):
    try:
        return parse_location(value)
    except:
        return None
