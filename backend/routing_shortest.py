from backend.valhalla_client import valhalla_route
import polyline

def get_shortest_route(start, end):
    """
    Uses Valhalla walking engine to compute shortest pedestrian route.
    Valhalla is returning polyline6 → decode with precision=6.
    """

    if not start or not end:
        return {"error": "Start and end coordinates required."}

    try:
        result = valhalla_route(start, end, costing="pedestrian")

        if "trip" not in result:
            return {"error": "No route found from Valhalla."}

        shape = result["trip"]["legs"][0]["shape"]

        # 🔥 Valhalla uses polyline6 → precision=6
        coords = polyline.decode(shape, precision=6)

        return {
            "mode": "shortest",
            "coordinates": coords,   # now ~[40.73, -74.02]
            "summary": result["trip"]["summary"],
        }

    except Exception as e:
        return {
            "error": f"Valhalla routing failed: {e}",
            "suggest": [
                "Try another start or end point.",
                "Check Valhalla server status.",
            ],
        }
