import requests

def geocode_location(query: str):
    try:
        url = "https://nominatim.openstreetmap.org/search"
        params = {"q": query, "format": "json", "limit": 1}
        res = requests.get(url, params=params, headers={
            "User-Agent": "WalkWithMe/1.0"
        }).json()

        if not res:
            return None

        lat = float(res[0]["lat"])
        lon = float(res[0]["lon"])
        return lat, lon

    except:
        return None
