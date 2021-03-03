"""Fixed publisher feeds. URLs come only from the acquisition manifest."""

from __future__ import annotations

import json
from pathlib import Path

USGS_ID = "usgs"
WEATHER_STATIONS = ("KSFO", "KSEA", "KNYC")
SOURCE_URLS = {
    USGS_ID: "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson",
    **{
        f"weather-{s}": f"https://api.weather.gov/stations/{s}/observations?limit=48"
        for s in WEATHER_STATIONS
    },
}

ALLOWED_HOSTS = frozenset({"earthquake.usgs.gov", "api.weather.gov"})

MAX_BODY_BYTES = 4 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 10.0
USER_AGENT = "fieldglass-local/0.1 (educational local dashboard; no contact)"

COOLDOWN_MS = 60_000
HISTORY_LIMIT = 32
MAX_EVENTS_RETURNED = 2000
WATCH_RECENCY_MS = 24 * 60 * 60 * 1000
FRESH_MS = 2 * 60 * 60 * 1000
CLOCK_SKEW_MS = 10 * 60 * 1000

TEMP_UNITS = frozenset({"wmoUnit:degC"})
WIND_UNITS = frozenset({"wmoUnit:km_h-1"})


def load_manifest(seed_dir: Path) -> dict[str, dict]:
    path = seed_dir / "manifest.json"
    if not path.is_file():
        raise FileNotFoundError(f"seed manifest missing: {path.name}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("manifest must be a list")
    by_name: dict[str, dict] = {}
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValueError("manifest entry missing name")
        name = item["name"]
        if name not in SOURCE_URLS or item.get("url") != SOURCE_URLS[name]:
            raise ValueError(f"manifest source/url not allowed: {name}")
        if name in by_name:
            raise ValueError(f"duplicate manifest source: {name}")
        by_name[name] = item
    return by_name


def seed_filename(source_id: str) -> str:
    if source_id == USGS_ID:
        return "usgs.json"
    if source_id.startswith("weather-") and source_id[8:] in WEATHER_STATIONS:
        return f"{source_id}.json"
    raise ValueError(f"unrecognized source {source_id}")
