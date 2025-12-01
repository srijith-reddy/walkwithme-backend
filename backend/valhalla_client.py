# backend/valhalla_client.py

import requests

VALHALLA_URL = "http://165.227.188.199:8002"

def valhalla_route(start, end, costing="pedestrian", costing_options=None):
    """
    Generic Valhalla routing request wrapper with EDGE-LEVEL data enabled.
    start = (lat, lon)
    end   = (lat, lon)
    """

    lat1, lon1 = start
    lat2, lon2 = end

    body = {
        "locations": [
            {"lat": lat1, "lon": lon1},
            {"lat": lat2, "lon": lon2}
        ],
        "costing": costing,

        # ⭐ THIS IS THE MAGIC LINE ⭐
        # This forces Valhalla to return full edge metadata
        "directions_options": {
            "units": "kilometers",
            "actions": ["edges"]
        },

        # ⭐ Additional protection (hard block bad edges)
        "filters": {
            "exclude": {
                "class": ["motorway", "trunk", "primary"],
                "use": ["ferry", "rail", "construction", "pier"],
                "surface": ["wood", "gravel", "ground", "dirt"]
            }
        }
    }

    # propagate costing options
    if costing_options:
        body["costing_options"] = costing_options

    try:
        res = requests.post(
            f"{VALHALLA_URL}/route",
            json=body,
            timeout=10
        )
        return res.json()

    except Exception as e:
        return {"error": f"Valhalla request failed: {e}"}
