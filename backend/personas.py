# backend/personas.py
#
# Time-aware walk personas.
#
# A persona frames the walk experience for the user — it drives:
#   - The name shown on the route card ("Golden Hour Walk")
#   - Routing costing bias (scenic vs safe vs explore)
#   - What enrichment to highlight (cafes in the morning, views at sunset)
#   - Copy tone in the iOS UI
#
# Personas are computed from: hour of day + weather + night flag.
# No external API call — deterministic and instant.

from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Persona definitions
# ---------------------------------------------------------------------------
_PERSONAS = [
    {
        "id": "night",
        "name": "Night Walk",
        "emoji": "🌙",
        "tagline": "Quiet streets, warm lights, the city at rest.",
        "routing_bias": "safe",
        "highlight_categories": ["bar", "cafe"],   # 24h spots
        "time_of_day": "night",
        "condition": lambda hour, weather, night: night,
    },
    {
        "id": "rainy",
        "name": "Rainy Day Walk",
        "emoji": "🌧️",
        "tagline": "Cozy cafes, covered arcades, and the sound of rain.",
        "routing_bias": "explore",
        "highlight_categories": ["cafe", "museum"],
        "time_of_day": "any",
        "condition": lambda hour, weather, night: weather in ("rain", "snow") and not night,
    },
    {
        "id": "morning",
        "name": "Morning Walk",
        "emoji": "🌅",
        "tagline": "Fresh air, first coffee, quiet streets before the city wakes up.",
        "routing_bias": "scenic",
        "highlight_categories": ["cafe", "park"],
        "time_of_day": "morning",
        "condition": lambda hour, weather, night: 5 <= hour <= 10 and not night,
    },
    {
        "id": "golden_hour",
        "name": "Golden Hour Walk",
        "emoji": "🧡",
        "tagline": "The best light of the day. Find a view.",
        "routing_bias": "scenic",
        "highlight_categories": ["landmark", "nature", "park"],
        "time_of_day": "evening",
        "condition": lambda hour, weather, night: 16 <= hour <= 19 and weather == "clear" and not night,
    },
    {
        "id": "lunch",
        "name": "Lunch Walk",
        "emoji": "🍜",
        "tagline": "A midday reset — stretch your legs and find something good to eat.",
        "routing_bias": "explore",
        "highlight_categories": ["restaurant", "cafe"],
        "time_of_day": "afternoon",
        "condition": lambda hour, weather, night: 11 <= hour <= 14 and not night,
    },
    {
        "id": "after_work",
        "name": "After Work Walk",
        "emoji": "🌆",
        "tagline": "Decompress. The city shifts. You can too.",
        "routing_bias": "explore",
        "highlight_categories": ["bar", "restaurant", "landmark"],
        "time_of_day": "evening",
        "condition": lambda hour, weather, night: 17 <= hour <= 20 and not night,
    },
    {
        "id": "hot_day",
        "name": "Cool Route Walk",
        "emoji": "🌡️",
        "tagline": "Shaded paths, waterfront breezes, and a cold drink at the end.",
        "routing_bias": "scenic",
        "highlight_categories": ["park", "nature", "cafe"],
        "time_of_day": "daytime",
        "condition": lambda hour, weather, night: weather == "hot" and not night,
    },
    {
        "id": "daytime",
        "name": "City Walk",
        "emoji": "☀️",
        "tagline": "Go explore. Anything could be around the next corner.",
        "routing_bias": "explore",
        "highlight_categories": ["landmark", "cafe", "park"],
        "time_of_day": "daytime",
        "condition": lambda hour, weather, night: True,  # default
    },
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def get_persona(weather: str, night: bool) -> dict:
    """
    Determine the walk persona given current weather and night flag.
    Returns a persona dict ready for API response.
    """
    hour = datetime.now(timezone.utc).hour

    for p in _PERSONAS:
        if p["condition"](hour, weather, night):
            return {
                "id": p["id"],
                "name": p["name"],
                "emoji": p["emoji"],
                "tagline": p["tagline"],
                "routing_bias": p["routing_bias"],
                "highlight_categories": p["highlight_categories"],
                "time_of_day": p["time_of_day"],
            }

    # Should never reach here given default catch-all, but just in case
    return {
        "id": "daytime",
        "name": "City Walk",
        "emoji": "☀️",
        "tagline": "Go explore.",
        "routing_bias": "explore",
        "highlight_categories": ["landmark", "cafe", "park"],
        "time_of_day": "daytime",
    }


def get_persona_for_location(lat: float, lon: float) -> dict:
    """
    Full persona resolution including live weather and night detection.
    Runs weather + night in parallel via common utils.
    """
    from backend.utils.common import get_weather_and_night
    weather, night = get_weather_and_night(lat, lon)
    persona = get_persona(weather, night)
    persona["weather"] = weather
    return persona
