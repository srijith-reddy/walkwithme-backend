from backend.valhalla_client import valhalla_route

def get_shortest_route(start, end):
    """
    Uses Valhalla walking engine to compute shortest pedestrian route.
    Valhalla is returning RAW coords, so do NOT decode polyline.
    """

    if not start or not end:
        return {"error": "Start and end coordinates required."}

    try:
        result = valhalla_route(start, end, costing="pedestrian")

        if "trip" not in result:
            return {"error": "No route found from Valhalla."}

        shape = result["trip"]["legs"][0]["shape"]

        # 🔥 STOP using polyline.decode()
        # 🔥 Convert raw microdegree coords → degrees
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
