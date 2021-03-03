"""Validate USGS and NWS payloads. Never executes source contents."""

from __future__ import annotations

import math
from datetime import datetime

from app.sources import TEMP_UNITS, USGS_ID, WIND_UNITS


class PayloadError(ValueError):
    """A source body failed structural validation and must not be applied."""


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PayloadError(f"{label} is not a number")
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise PayloadError(f"{label} is not finite") from exc
    if not math.isfinite(number):
        raise PayloadError(f"{label} is not finite")
    return number


def _optional_quantity(node: object, allowed_units: frozenset[str], label: str) -> float | None:
    if node is None:
        return None
    if not isinstance(node, dict):
        raise PayloadError(f"{label} is not an object")
    unit = node.get("unitCode")
    if unit is not None and not isinstance(unit, str):
        raise PayloadError(f"{label} unit is not a string")
    if unit not in allowed_units:
        return None
    value = node.get("value")
    if value is None:
        return None
    return _finite(value, label)


def parse_iso_ms(text: object, label: str) -> int:
    if not isinstance(text, str) or not text:
        raise PayloadError(f"{label} timestamp missing")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, OverflowError) as exc:
        raise PayloadError(f"{label} timestamp invalid") from exc
    if parsed.tzinfo is None:
        raise PayloadError(f"{label} timestamp not timezone-aware")
    try:
        result = int(parsed.timestamp() * 1000)
    except (ValueError, OverflowError, OSError) as exc:
        raise PayloadError(f"{label} timestamp invalid") from exc
    if not 0 <= result <= 9_999_999_999_999:
        raise PayloadError(f"{label} timestamp out of bounds")
    return result


def _epoch(value: object, label: str) -> int:
    result = _finite(value, label)
    if not 0 <= result <= 9_999_999_999_999:
        raise PayloadError(f"{label} timestamp out of bounds")
    return int(result)


def parse_usgs(body: object) -> tuple[int | None, list[dict]]:
    if not isinstance(body, dict) or body.get("type") != "FeatureCollection":
        raise PayloadError("usgs body is not a FeatureCollection")
    features = body.get("features")
    if not isinstance(features, list):
        raise PayloadError("usgs features missing")
    generated = None
    metadata = body.get("metadata")
    if isinstance(metadata, dict) and metadata.get("generated") is not None:
        generated = _epoch(metadata["generated"], "generated")
    events = []
    seen: set[str] = set()
    for feature in features:
        if not isinstance(feature, dict):
            raise PayloadError("usgs feature is not an object")
        event_id = feature.get("id")
        props = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(event_id, str) or not event_id:
            raise PayloadError("usgs feature id missing")
        if event_id in seen:
            raise PayloadError(f"usgs duplicate id {event_id}")
        seen.add(event_id)
        if not isinstance(props, dict) or not isinstance(geometry, dict):
            raise PayloadError(f"usgs feature {event_id} incomplete")
        coords = geometry.get("coordinates")
        if not isinstance(coords, list) or len(coords) < 3:
            raise PayloadError(f"usgs coordinates incomplete for {event_id}")
        lon = _finite(coords[0], "lon")
        lat = _finite(coords[1], "lat")
        depth = _finite(coords[2], "depth")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise PayloadError(f"usgs coordinates out of range for {event_id}")
        mag = props.get("mag")
        mag_value = None if mag is None else _finite(mag, "mag")
        place = props.get("place")
        if place is not None and not isinstance(place, str):
            raise PayloadError(f"usgs place invalid for {event_id}")
        status = props.get("status")
        if status is not None and not isinstance(status, str):
            raise PayloadError(f"usgs status invalid for {event_id}")
        url = props.get("url")
        if url is not None and not isinstance(url, str):
            raise PayloadError(f"usgs url invalid for {event_id}")
        kind = props.get("type") or "unknown"
        if not isinstance(kind, str) or len(kind) > 80:
            raise PayloadError(f"usgs event type invalid for {event_id}")
        events.append(
            {
                "id": event_id,
                "type": kind,
                "lat": lat,
                "lon": lon,
                "depth_km": depth,
                "mag": mag_value,
                "place": place,
                "time": _epoch(props.get("time"), "time"),
                "updated": _epoch(props.get("updated"), "updated"),
                "status": status,
                "source_url": url,
            }
        )
    return generated, events


def parse_weather(body: object, station: str) -> list[dict]:
    if not isinstance(body, dict) or not isinstance(body.get("features"), list):
        raise PayloadError(f"weather {station} features missing")
    reports = []
    seen: set[int] = set()
    for feature in body["features"]:
        if not isinstance(feature, dict):
            raise PayloadError("weather feature is not an object")
        props = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(props, dict) or not isinstance(geometry, dict):
            raise PayloadError("weather feature incomplete")
        station_id = props.get("stationId")
        if station_id != station:
            raise PayloadError(f"weather station {station_id} != {station}")
        coords = geometry.get("coordinates")
        if not isinstance(coords, list) or len(coords) < 2:
            raise PayloadError("weather coordinates incomplete")
        lon = _finite(coords[0], "lon")
        lat = _finite(coords[1], "lat")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise PayloadError("weather coordinates out of range")
        observed = parse_iso_ms(props.get("timestamp"), "observation")
        if observed in seen:
            continue
        seen.add(observed)
        description = props.get("textDescription")
        if description is not None and not isinstance(description, str):
            raise PayloadError("weather description invalid")
        reports.append(
            {
                "station": station,
                "lat": lat,
                "lon": lon,
                "time": observed,
                "temperature_c": _optional_quantity(
                    props.get("temperature"), TEMP_UNITS, "temperature"
                ),
                "wind_kmh": _optional_quantity(props.get("windSpeed"), WIND_UNITS, "wind"),
                "description": description,
            }
        )
    return reports


def parse_source(source_id: str, body: object) -> dict:
    if source_id == USGS_ID:
        generated, events = parse_usgs(body)
        return {"generated": generated, "events": events, "weather": []}
    if source_id.startswith("weather-"):
        station = source_id[8:]
        return {"generated": None, "events": [], "weather": parse_weather(body, station)}
    raise PayloadError(f"unknown source {source_id}")
