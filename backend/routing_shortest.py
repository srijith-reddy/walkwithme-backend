from backend.valhalla_client import valhalla_route
from backend.utils.polyline import decode_polyline  # you have this file already

def get_shortest_route(start, end):
    """
    Uses Valhalla walking engine to compute shortest pedestrian route.
    """

    if not start or not end:
        return {"error": "Start and end coordinates required."}

    try:
        result = valhalla_route(start, end, costing="pedestrian")

        # Valhalla returned an error
        if "trip" not in result:
            return {"error": "No route found from Valhalla."}

        shape = result["trip"]["legs"][0]["shape"]

        # ⭐ DECODE polyline → list of [lat, lon]
        coords = decode_polyline(shape)

        return {
            "mode": "shortest",
            "coordinates": coords,
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
