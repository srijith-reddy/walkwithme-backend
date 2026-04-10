# backend/loop_assistant/models.py

from typing import Optional
from pydantic import BaseModel, Field


class LoopAssistantRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    user_lat: Optional[float] = None
    user_lon: Optional[float] = None
    max_options: int = Field(default=3, ge=1, le=5)


class RoutePreview(BaseModel):
    # Downsampled coordinate list for map rendering: [[lat, lon], ...]
    geometry: list
    # Simplified waypoints for AR anchor placement (every Nth point)
    waypoints: list


class LoopOption(BaseModel):
    id: str
    title: str
    subtitle: str
    theme: str
    route_style: str
    duration_min: int
    distance_miles: float
    why_this: str
    highlights: list
    neighborhood_character: str
    suggested_stops: list
    route_preview: RoutePreview


class OriginInfo(BaseModel):
    label: str
    lat: float
    lon: float
    origin_type: str


class LoopAssistantResponse(BaseModel):
    origin: OriginInfo
    assistant_summary: str
    options: list[LoopOption]
