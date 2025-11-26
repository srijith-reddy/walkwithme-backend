# backend/valhalla_client.py

import requests

VALHALLA_URL = "http://165.227.188.199:8002"  # Or your Fly.io Valhalla URL

def valhalla_route(start, end, costing="pedestrian", costing_options=None):
    """
    Generic Valhalla routing request wrapper.
    start = (lat, lon)
    end   = (lat, lon)
    costing = "pedestrian" | "bicycle" | "auto"
    """

    lat1, lon1 = start
    lat2, lon2 = end

    body = {
        "locations": [
            {"lat": lat1, "lon": lon1},
            {"lat": lat2, "lon": lon2}
        ],
        "costing": costing,
    }

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
