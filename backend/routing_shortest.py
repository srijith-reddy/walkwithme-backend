from backend.valhalla_client import valhalla_route
import polyline

def get_shortest_route(start, end):
    """
    Uses Valhalla walking engine to compute shortest pedestrian route.
    Handles BOTH encoded polylines and raw integer coordinate arrays.
    """

    if not start or not end:
        return {"error": "Start and end coordinates required."}

    try:
        result = valhalla_route(start, end, costing="pedestrian")

        # Valhalla returned an error
        if "trip" not in result:
            return {"error": "No route found from Valhalla."}

        shape = result["trip"]["legs"][0]["shape"]

        # ---------------------------------------------------
        # ⭐ AUTO-DETECT SHAPE FORMAT
        # ---------------------------------------------------
        if isinstance(shape, str):
            # Encoded polyline (normal Valhalla output)
            coords = polyline.decode(shape)

        else:
            # Raw integer microdegree coords → fix scaling
            # E.g. [4073763, -7402857] → [40.73763, -74.02857]
            coords = [(lat / 1e6, lon / 1e6) for lat, lon in shape]

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
