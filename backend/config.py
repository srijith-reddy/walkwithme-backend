# backend/config.py
# Single source of truth for all env-driven configuration.
# Import from here — never os.getenv() scattered across modules.

import os

# ---------------------------------------------------------------------------
# Valhalla
# ---------------------------------------------------------------------------
VALHALLA_URL: str = os.getenv("VALHALLA_URL", "http://165.227.188.199:8002")
VALHALLA_TIMEOUT: int = int(os.getenv("VALHALLA_TIMEOUT", "10"))

# ---------------------------------------------------------------------------
# External APIs
# ---------------------------------------------------------------------------
GOOGLE_PLACES_API_KEY: str = os.getenv("GOOGLE_PLACES_API_KEY", "")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

# ---------------------------------------------------------------------------
# Overpass (OSM POI queries — used for route enrichment)
# ---------------------------------------------------------------------------
OVERPASS_URL: str = os.getenv(
    "OVERPASS_URL", "https://overpass-api.de/api/interpreter"
)
OVERPASS_TIMEOUT: int = int(os.getenv("OVERPASS_TIMEOUT", "6"))

# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------
# Max perpendicular distance from route for a POI to be included
ENRICHMENT_CORRIDOR_M: int = int(os.getenv("ENRICHMENT_CORRIDOR_M", "150"))
# Max number of POIs per category in route response
ENRICHMENT_MAX_LANDMARKS: int = int(os.getenv("ENRICHMENT_MAX_LANDMARKS", "8"))
ENRICHMENT_MAX_FOOD: int = int(os.getenv("ENRICHMENT_MAX_FOOD", "8"))

# ---------------------------------------------------------------------------
# Walking speed assumption (km/h) — used for duration → distance conversion
# ---------------------------------------------------------------------------
WALK_SPEED_KPH: float = float(os.getenv("WALK_SPEED_KPH", "5.0"))
