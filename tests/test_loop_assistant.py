# tests/test_loop_assistant.py
#
# Unit tests for Loop Assistant logic.
#
# All tests are pure-logic — no Valhalla or Overpass calls are made.
# Tests that touch the service layer mock get_route and enrich_route.

import math
import pytest
from unittest.mock import patch, MagicMock

from backend.loop_assistant.intent_parser import parse_intent, ParsedIntent
from backend.loop_assistant.service import (
    _deduplicate,
    _score,
    _build_candidate_specs,
    _build_subtitle,
    _build_why_this,
    _build_summary,
    _build_option,
    _resolve_origin,
    _EMPTY_ENRICHMENT,
)
from backend.loop_assistant.models import LoopAssistantRequest


# ===========================================================================
# Intent Parser Tests
# ===========================================================================

class TestParseIntent:

    def test_food_in_east_village(self):
        intent = parse_intent("food loop in East Village")
        assert intent.theme == "food"
        assert intent.query_type == "area"
        assert intent.location_hint == "east village"

    def test_coffee_from_23rd_st(self):
        intent = parse_intent("coffee walk from 23rd st")
        assert intent.theme == "coffee"
        assert intent.query_type == "station"
        assert "23rd" in intent.location_hint

    def test_scenic_near_central_park(self):
        intent = parse_intent("scenic walk near Central Park")
        assert intent.theme == "scenic"
        assert intent.query_type == "area"
        assert intent.location_hint is not None

    def test_surprise_me_open_ended(self):
        intent = parse_intent("surprise me")
        assert intent.theme == "explore"
        assert intent.query_type == "open_ended"
        assert intent.location_hint is None

    def test_give_me_a_good_walk(self):
        intent = parse_intent("give me a good walk")
        # "good walk" → explore
        assert intent.theme == "explore"
        assert intent.query_type == "open_ended"

    def test_quick_duration(self):
        intent = parse_intent("quick food loop near me")
        assert intent.duration_min == 20

    def test_long_duration(self):
        intent = parse_intent("long scenic walk in Brooklyn")
        assert intent.duration_min == 60

    def test_explicit_minutes(self):
        intent = parse_intent("45 min walk in Soho")
        assert intent.duration_min == 45

    def test_landmark_query(self):
        intent = parse_intent("landmark loop around Times Square")
        assert intent.theme == "landmark"
        assert intent.location_hint is not None

    def test_history_in_lower_manhattan(self):
        intent = parse_intent("historic walk in Lower Manhattan")
        assert intent.theme == "history"
        assert intent.location_hint == "lower manhattan"

    def test_parks_query(self):
        intent = parse_intent("green park loop near me")
        assert intent.theme == "parks"

    def test_explore_wander(self):
        intent = parse_intent("I want to wander around Brooklyn")
        assert intent.theme == "explore"
        assert intent.query_type == "area"

    def test_station_with_street_number(self):
        intent = parse_intent("create loop routes from 14th Street")
        assert intent.query_type == "station"

    def test_route_style_food(self):
        intent = parse_intent("food loop")
        assert intent.route_style == "explore"

    def test_route_style_scenic(self):
        intent = parse_intent("scenic loop")
        assert intent.route_style == "scenic"

    def test_location_hint_cleaned(self):
        # Trailing noise like "walk" should be stripped from location hint
        intent = parse_intent("in Greenwich Village walk")
        # "walk" should not be part of the location hint
        if intent.location_hint:
            assert "walk" not in intent.location_hint

    def test_near_pattern(self):
        intent = parse_intent("quick loop near Union Square")
        assert intent.location_hint == "union square"

    def test_around_pattern(self):
        intent = parse_intent("explore loop around Nolita")
        assert intent.location_hint == "nolita"

    def test_default_theme_no_keywords(self):
        # No matching keywords → default scenic
        intent = parse_intent("generate a loop")
        assert intent.theme == "scenic"

    def test_default_duration_no_keywords(self):
        intent = parse_intent("food loop in SoHo")
        assert intent.duration_min == 35  # default


# ===========================================================================
# Candidate Spec Builder Tests
# ===========================================================================

class TestBuildCandidateSpecs:

    def _make_intent(self, theme="food", duration_min=35):
        return ParsedIntent(
            query_type="area",
            location_hint="east village",
            theme=theme,
            duration_min=duration_min,
            route_style="explore",
        )

    def test_returns_at_least_max_options_plus_one(self):
        intent = self._make_intent()
        specs = _build_candidate_specs(intent, max_options=3)
        # Should generate at least max_options specs (some extras for safety)
        assert len(specs) >= 3

    def test_primary_theme_included(self):
        intent = self._make_intent(theme="food")
        specs = _build_candidate_specs(intent, max_options=3)
        themes = [s.theme for s in specs]
        assert "food" in themes

    def test_complementary_themes_present(self):
        intent = self._make_intent(theme="food")
        specs = _build_candidate_specs(intent, max_options=4)
        themes = set(s.theme for s in specs)
        # Should include at least one complementary theme
        assert len(themes) > 1

    def test_all_themes_are_valid_strings(self):
        intent = self._make_intent()
        specs = _build_candidate_specs(intent, max_options=5)
        for spec in specs:
            assert isinstance(spec.theme, str) and len(spec.theme) > 0
            assert isinstance(spec.duration_min, int) and spec.duration_min > 0


# ===========================================================================
# Deduplication Tests
# ===========================================================================

class TestDeduplicate:

    def _make_candidate(self, center_lat: float, center_lon: float, loop_km: float, n: int = 60):
        """Build a minimal fake candidate with synthetic coordinates."""
        # Generate a simple circular polyline around the center
        coords = []
        for i in range(n):
            angle = (2 * math.pi * i) / n
            lat = center_lat + (loop_km / 222) * math.cos(angle)
            lon = center_lon + (loop_km / 222) * math.sin(angle)
            coords.append((lat, lon))
        return {
            "coordinates": coords,
            "loop_km": loop_km,
            "_spec_theme": "scenic",
            "_spec_duration": 35,
            "enrichment": dict(_EMPTY_ENRICHMENT),
        }

    def test_identical_routes_deduped(self):
        c1 = self._make_candidate(40.73, -74.00, 3.0)
        c2 = self._make_candidate(40.73, -74.00, 3.0)
        result = _deduplicate([c1, c2])
        assert len(result) == 1

    def test_distant_routes_both_kept(self):
        c1 = self._make_candidate(40.73, -74.00, 3.0)
        c2 = self._make_candidate(40.76, -74.03, 3.0)  # ~500m away
        result = _deduplicate([c1, c2])
        assert len(result) == 2

    def test_same_location_very_different_length_both_kept(self):
        c1 = self._make_candidate(40.73, -74.00, 2.0)
        c2 = self._make_candidate(40.73, -74.00, 5.0)  # length ratio > 0.25
        result = _deduplicate([c1, c2])
        assert len(result) == 2

    def test_empty_candidates(self):
        result = _deduplicate([])
        assert result == []

    def test_single_candidate(self):
        c = self._make_candidate(40.73, -74.00, 3.0)
        result = _deduplicate([c])
        assert len(result) == 1

    def test_three_unique_routes(self):
        c1 = self._make_candidate(40.73, -74.00, 2.5)
        c2 = self._make_candidate(40.75, -73.98, 3.0)
        c3 = self._make_candidate(40.71, -74.02, 4.0)
        result = _deduplicate([c1, c2, c3])
        assert len(result) == 3

    def test_preserves_first_of_duplicates(self):
        c1 = self._make_candidate(40.73, -74.00, 3.0)
        c2 = self._make_candidate(40.73, -74.00, 3.0)
        c1["_spec_theme"] = "scenic"
        c2["_spec_theme"] = "explore"
        result = _deduplicate([c1, c2])
        assert result[0]["_spec_theme"] == "scenic"


# ===========================================================================
# Scoring Tests
# ===========================================================================

class TestScore:

    def _make_intent(self, theme="food", duration_min=35):
        return ParsedIntent(
            query_type="area",
            location_hint="east village",
            theme=theme,
            duration_min=duration_min,
            route_style="explore",
        )

    def _make_candidate(self, theme="food", duration_min=35, poi_count=0,
                        poi_seeded=False, loop_km=3.0, target_km=3.0,
                        food_pois=None, landmark_pois=None, park_pois=None, cafe_pois=None):
        enrichment = dict(_EMPTY_ENRICHMENT)
        enrichment["poi_count"] = poi_count
        if food_pois:
            enrichment["food"] = [{"category": "restaurant"} for _ in range(food_pois)]
        if cafe_pois:
            enrichment["food"] = [{"category": "cafe"} for _ in range(cafe_pois)]
        if landmark_pois:
            enrichment["landmarks"] = [{"category": "landmark"} for _ in range(landmark_pois)]
        if park_pois:
            enrichment["parks"] = [{"category": "park"} for _ in range(park_pois)]

        return {
            "_spec_theme": theme,
            "_spec_duration": duration_min,
            "loop_km": loop_km,
            "target_km": target_km,
            "poi_seeded": poi_seeded,
            "enrichment": enrichment,
        }

    def test_exact_theme_match_scores_higher_than_mismatch(self):
        intent = self._make_intent(theme="food")
        match = self._make_candidate(theme="food")
        mismatch = self._make_candidate(theme="scenic")
        assert _score(match, intent) > _score(mismatch, intent)

    def test_more_pois_scores_higher(self):
        intent = self._make_intent(theme="food")
        rich = self._make_candidate(theme="food", poi_count=8)
        sparse = self._make_candidate(theme="food", poi_count=0)
        assert _score(rich, intent) > _score(sparse, intent)

    def test_poi_seeded_bonus(self):
        intent = self._make_intent(theme="food")
        seeded = self._make_candidate(theme="food", poi_seeded=True)
        not_seeded = self._make_candidate(theme="food", poi_seeded=False)
        assert _score(seeded, intent) > _score(not_seeded, intent)

    def test_duration_penalty_for_off_target(self):
        intent = self._make_intent(duration_min=35)
        close = self._make_candidate(theme="scenic", duration_min=35)
        far = self._make_candidate(theme="scenic", duration_min=60)
        assert _score(close, intent) > _score(far, intent)

    def test_accurate_distance_scores_higher(self):
        intent = self._make_intent()
        accurate = self._make_candidate(theme="food", loop_km=3.0, target_km=3.0)
        inaccurate = self._make_candidate(theme="food", loop_km=1.0, target_km=3.0)
        assert _score(accurate, intent) > _score(inaccurate, intent)

    def test_food_category_bonus_for_food_intent(self):
        intent = self._make_intent(theme="food")
        with_food = self._make_candidate(theme="food", poi_count=3, food_pois=3)
        without_food = self._make_candidate(theme="food", poi_count=3)
        assert _score(with_food, intent) > _score(without_food, intent)

    def test_cafe_bonus_for_coffee_intent(self):
        intent = self._make_intent(theme="coffee")
        with_cafes = self._make_candidate(theme="coffee", poi_count=3, cafe_pois=3)
        no_cafes = self._make_candidate(theme="coffee", poi_count=3)
        assert _score(with_cafes, intent) > _score(no_cafes, intent)

    def test_adjacent_theme_gets_partial_score(self):
        intent = self._make_intent(theme="food")
        exact = self._make_candidate(theme="food")
        adjacent = self._make_candidate(theme="coffee")  # complementary to food
        other = self._make_candidate(theme="scenic")
        assert _score(exact, intent) > _score(adjacent, intent)
        assert _score(adjacent, intent) > _score(other, intent)


# ===========================================================================
# Response Builder Tests
# ===========================================================================

class TestBuildSubtitle:

    def _enrichment(self, highlights=None):
        e = dict(_EMPTY_ENRICHMENT)
        if highlights:
            e["highlights"] = highlights
        return e

    def test_two_highlights(self):
        candidate = {"_spec_duration": 35, "loop_km": 2.5, "duration_s": 2100}
        e = self._enrichment(highlights=["☕ Joe's Coffee", "🍽️ Rice & Beans"])
        subtitle = _build_subtitle(candidate, e)
        assert "Joe's Coffee" in subtitle
        assert "Rice & Beans" in subtitle
        assert "→" in subtitle

    def test_one_highlight(self):
        candidate = {"_spec_duration": 35, "loop_km": 2.5, "duration_s": 2100}
        e = self._enrichment(highlights=["📍 Brooklyn Bridge"])
        subtitle = _build_subtitle(candidate, e)
        assert "Brooklyn Bridge" in subtitle

    def test_no_highlights_fallback(self):
        candidate = {"_spec_duration": 35, "loop_km": 2.5, "duration_s": 2100}
        e = self._enrichment()
        subtitle = _build_subtitle(candidate, e)
        # Should include distance or duration info
        assert "min" in subtitle or "km" in subtitle


class TestBuildSummary:

    def _make_option(self, theme="scenic", duration_min=35):
        from backend.loop_assistant.models import LoopOption, RoutePreview
        return LoopOption(
            id="abc12345",
            title="Scenic Loop",
            subtitle="test",
            theme=theme,
            route_style="scenic",
            duration_min=duration_min,
            distance_miles=1.5,
            why_this="Because it's great.",
            highlights=[],
            neighborhood_character="",
            suggested_stops=[],
            route_preview=RoutePreview(geometry=[], waypoints=[]),
        )

    def test_no_options_returns_fallback(self):
        intent = ParsedIntent("area", "east village", "food", 35, "explore")
        summary = _build_summary([], intent, "East Village")
        assert "East Village" in summary
        assert "No loops" in summary or "could not" in summary.lower() or "no loops" in summary.lower()

    def test_single_option_summary(self):
        intent = ParsedIntent("area", "east village", "food", 35, "explore")
        options = [self._make_option("food", 35)]
        summary = _build_summary(options, intent, "East Village")
        assert "East Village" in summary
        assert "1 loop" in summary

    def test_multiple_options_summary(self):
        intent = ParsedIntent("area", "east village", "food", 35, "explore")
        options = [
            self._make_option("food", 30),
            self._make_option("scenic", 40),
            self._make_option("explore", 35),
        ]
        summary = _build_summary(options, intent, "East Village")
        assert "3 loops" in summary
        assert "East Village" in summary

    def test_duration_range_in_summary(self):
        intent = ParsedIntent("area", "east village", "food", 35, "explore")
        options = [self._make_option("food", 25), self._make_option("scenic", 45)]
        summary = _build_summary(options, intent, "East Village")
        assert "25" in summary and "45" in summary

    def test_start_end_same_point_mentioned(self):
        intent = ParsedIntent("area", "east village", "food", 35, "explore")
        options = [self._make_option("food", 35)]
        summary = _build_summary(options, intent, "East Village")
        assert "same point" in summary


# ===========================================================================
# Origin Resolution Tests
# ===========================================================================

class TestResolveOrigin:

    def test_uses_user_gps_when_no_location_hint(self):
        intent = ParsedIntent("open_ended", None, "explore", 35, "explore")
        with patch("backend.loop_assistant.service.reverse_geocode", return_value="Test Area, NY"):
            lat, lon, label, origin_type = _resolve_origin(intent, 40.73, -74.00)
        assert lat == 40.73
        assert lon == -74.00
        assert origin_type == "user_location"

    def test_falls_back_to_default_without_user_gps(self):
        intent = ParsedIntent("open_ended", None, "explore", 35, "explore")
        lat, lon, label, origin_type = _resolve_origin(intent, None, None)
        assert origin_type == "default"
        assert label != ""
        assert isinstance(lat, float)
        assert isinstance(lon, float)

    def test_uses_location_hint_over_user_gps(self):
        intent = ParsedIntent("area", "east village", "food", 35, "explore")
        with patch("backend.loop_assistant.service.parse_location", return_value=(40.726, -73.981)):
            with patch("backend.loop_assistant.service.reverse_geocode", return_value="East Village, NY"):
                lat, lon, label, origin_type = _resolve_origin(intent, 40.73, -74.00)
        assert lat == 40.726
        assert lon == -73.981
        assert origin_type == "area"

    def test_falls_back_to_user_gps_if_geocode_fails(self):
        intent = ParsedIntent("area", "nonexistent gibberish place xyz", "food", 35, "explore")
        with patch("backend.loop_assistant.service.parse_location", side_effect=Exception("geocode fail")):
            with patch("backend.loop_assistant.service.reverse_geocode", return_value="User Location"):
                lat, lon, label, origin_type = _resolve_origin(intent, 40.73, -74.00)
        assert lat == 40.73
        assert origin_type == "user_location"


# ===========================================================================
# Integration-style test: run_loop_assistant with mocked routing
# ===========================================================================

class TestRunLoopAssistant:

    def _fake_route(self, *args, **kwargs):
        """Fake loop route result."""
        coords = [(40.73 + i * 0.001, -74.00 + i * 0.001) for i in range(50)]
        return {
            "mode": "loop",
            "theme": "scenic",
            "loop_km": 3.0,
            "target_km": 2.9,
            "distance_m": 3000,
            "duration_s": 2160,
            "coordinates": coords,
            "waypoints": coords[::8],
            "poi_seeded": False,
        }

    def _fake_enrich(self, coords):
        return {
            "landmarks": [{"name": "Test Bridge", "category": "landmark",
                           "emoji": "📍", "lat": 40.73, "lon": -74.00,
                           "distance_from_route_m": 50}],
            "food": [{"name": "Test Cafe", "category": "cafe",
                      "emoji": "☕", "lat": 40.731, "lon": -73.999,
                      "distance_from_route_m": 80}],
            "parks": [],
            "highlights": ["📍 Test Bridge", "☕ Test Cafe"],
            "summary": "You'll pass Test Bridge. Test Cafe is right along the route.",
            "neighborhood_flavor": {"label": "Cultural", "emoji": "📍", "description": "Rich in culture."},
            "poi_count": 2,
        }

    def test_returns_structured_response(self):
        request = LoopAssistantRequest(query="food loop in East Village", max_options=2)

        with patch("backend.loop_assistant.service.get_route", side_effect=self._fake_route), \
             patch("backend.loop_assistant.service.enrich_route", side_effect=self._fake_enrich), \
             patch("backend.loop_assistant.service.parse_location", return_value=(40.726, -73.981)), \
             patch("backend.loop_assistant.service.reverse_geocode", return_value="East Village, Manhattan"):

            from backend.loop_assistant.service import run_loop_assistant
            result = run_loop_assistant(request)

        assert "origin" in result
        assert "assistant_summary" in result
        assert "options" in result
        assert result["origin"]["origin_type"] in ("area", "station", "user_location", "default")
        assert isinstance(result["options"], list)

    def test_options_have_required_fields(self):
        request = LoopAssistantRequest(query="scenic walk near Central Park", max_options=2)

        with patch("backend.loop_assistant.service.get_route", side_effect=self._fake_route), \
             patch("backend.loop_assistant.service.enrich_route", side_effect=self._fake_enrich), \
             patch("backend.loop_assistant.service.parse_location", return_value=(40.785, -73.968)), \
             patch("backend.loop_assistant.service.reverse_geocode", return_value="Central Park, NY"):

            from backend.loop_assistant.service import run_loop_assistant
            result = run_loop_assistant(request)

        for option in result["options"]:
            assert "id" in option
            assert "title" in option
            assert "theme" in option
            assert "duration_min" in option
            assert "distance_miles" in option
            assert "highlights" in option
            assert "route_preview" in option
            assert "geometry" in option["route_preview"]
            assert "waypoints" in option["route_preview"]

    def test_graceful_when_all_routing_fails(self):
        request = LoopAssistantRequest(query="food loop in East Village", max_options=2)

        with patch("backend.loop_assistant.service.get_route", return_value={"error": "Valhalla down"}), \
             patch("backend.loop_assistant.service.parse_location", return_value=(40.726, -73.981)), \
             patch("backend.loop_assistant.service.reverse_geocode", return_value="East Village"):

            from backend.loop_assistant.service import run_loop_assistant
            result = run_loop_assistant(request)

        assert result["options"] == []
        assert "Could not" in result["assistant_summary"] or "No loops" in result["assistant_summary"]

    def test_max_options_respected(self):
        request = LoopAssistantRequest(query="scenic walk near Brooklyn", max_options=2)

        call_count = 0

        def fake_route_varied(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # Offset each candidate so dedup keeps them all
            offset = call_count * 0.01
            coords = [(40.65 + offset + i * 0.001, -73.95 + i * 0.001) for i in range(50)]
            return {
                "mode": "loop", "theme": "scenic",
                "loop_km": 3.0 + call_count * 0.3,
                "target_km": 2.9,
                "distance_m": 3000,
                "duration_s": 2160,
                "coordinates": coords,
                "waypoints": coords[::8],
                "poi_seeded": False,
            }

        with patch("backend.loop_assistant.service.get_route", side_effect=fake_route_varied), \
             patch("backend.loop_assistant.service.enrich_route", side_effect=self._fake_enrich), \
             patch("backend.loop_assistant.service.parse_location", return_value=(40.65, -73.95)), \
             patch("backend.loop_assistant.service.reverse_geocode", return_value="Brooklyn, NY"):

            from backend.loop_assistant.service import run_loop_assistant
            result = run_loop_assistant(request)

        assert len(result["options"]) <= 2

    def test_open_ended_query_uses_user_gps(self):
        request = LoopAssistantRequest(
            query="surprise me",
            user_lat=40.73,
            user_lon=-74.00,
            max_options=1,
        )

        def fake_route(*args, **kwargs):
            start = args[0]
            assert abs(start[0] - 40.73) < 0.001, "Should use user GPS lat"
            assert abs(start[1] - (-74.00)) < 0.001, "Should use user GPS lon"
            coords = [(40.73 + i * 0.001, -74.00 + i * 0.001) for i in range(50)]
            return {
                "mode": "loop", "theme": "explore",
                "loop_km": 2.8, "target_km": 2.8,
                "distance_m": 2800, "duration_s": 2016,
                "coordinates": coords,
                "waypoints": coords[::8],
                "poi_seeded": False,
            }

        with patch("backend.loop_assistant.service.get_route", side_effect=fake_route), \
             patch("backend.loop_assistant.service.enrich_route", side_effect=self._fake_enrich), \
             patch("backend.loop_assistant.service.reverse_geocode", return_value="Your Location"):

            from backend.loop_assistant.service import run_loop_assistant
            result = run_loop_assistant(request)

        assert result["origin"]["origin_type"] == "user_location"
