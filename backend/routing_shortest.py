# backend/routing_shortest.py

from backend.valhalla_client import valhalla_route

def get_shortest_route(start, end):
    """
    Uses Valhalla walking engine to compute shortest pedestrian route.
    """

    if not start or not end:
        return {"error": "Start and end coordinates required."}

    try:
        result = valhalla_route(start, end, costing="pedestrian")
        return {
            "mode": "shortest",
            "coordinates_polyline": result["trip"]["legs"][0]["shape"],
            "summary": result["trip"]["summary"]
        }

    except Exception as e:
        return {
            "error": f"Valhalla routing failed: {e}",
            "suggest": [
                "Try another start or end point.",
                "Check Valhalla server status."
            ]
        }
