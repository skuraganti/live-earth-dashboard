"""Parsing/validation tests. All payloads here are synthetic."""

from __future__ import annotations

import pytest

from app.parse import PayloadError, parse_source, parse_usgs, parse_weather
from tests.conftest import NOW, iso, quantity, usgs_payload, weather_payload

USGS = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson"


def test_usgs_valid_event_fields():
    payload = usgs_payload(
        [
            {
                "id": "a1",
                "mag": 3.5,
                "place": "Somewhere",
                "time": NOW,
                "lat": 10.0,
                "lon": 20.0,
                "depth_km": 5.5,
                "status": "automatic",
            }
        ]
    )
    generated, events = parse_usgs(payload)
    assert generated == NOW - 60_000
    assert events[0]["mag"] == 3.5
    assert events[0]["depth_km"] == 5.5
    assert events[0]["time"] == NOW


def test_usgs_preserves_null_magnitude():
    payload = usgs_payload(
        [{"id": "a1", "mag": None, "place": None, "time": NOW, "lat": 1.0, "lon": 2.0}]
    )
    _, events = parse_usgs(payload)
    assert events[0]["mag"] is None
    assert events[0]["place"] is None


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), "3.5", True, [3.5]],
)
def test_usgs_rejects_nonfinite_or_wrong_types(value):
    payload = usgs_payload([{"id": "a1", "mag": value, "time": NOW, "lat": 1.0, "lon": 2.0}])
    with pytest.raises(PayloadError):
        parse_usgs(payload)


@pytest.mark.parametrize("lat,lon", [(91.0, 0.0), (-91.0, 0.0), (0.0, 181.0), (0.0, -181.0)])
def test_usgs_rejects_out_of_range_coordinates(lat, lon):
    payload = usgs_payload([{"id": "a1", "mag": 3.0, "time": NOW, "lat": lat, "lon": lon}])
    with pytest.raises(PayloadError):
        parse_usgs(payload)


def test_usgs_rejects_duplicate_ids_and_bad_shape():
    duplicate = usgs_payload(
        [
            {"id": "a1", "mag": 3.0, "time": NOW, "lat": 1.0, "lon": 2.0},
            {"id": "a1", "mag": 3.1, "time": NOW, "lat": 1.0, "lon": 2.0},
        ]
    )
    with pytest.raises(PayloadError):
        parse_usgs(duplicate)
    with pytest.raises(PayloadError):
        parse_usgs({"type": "FeatureCollection", "features": "nope"})
    with pytest.raises(PayloadError):
        parse_usgs({"type": "NotAFeatureCollection", "features": []})


def test_weather_reads_temperature_and_wind_units():
    payload = weather_payload(
        "KSFO",
        [
            {
                "station": "KSFO",
                "time": iso(NOW),
                "lat": 37.6,
                "lon": -122.4,
                "temperature": quantity(18.0, "wmoUnit:degC"),
                "windSpeed": quantity(22.0, "wmoUnit:km_h-1"),
                "description": "Clear",
            }
        ],
    )
    reports = parse_weather(payload, "KSFO")
    assert reports[0]["temperature_c"] == 18.0
    assert reports[0]["wind_kmh"] == 22.0
    assert reports[0]["time"] == NOW


def test_weather_keeps_nulls_and_rejects_unsupported_units():
    payload = weather_payload(
        "KSFO",
        [
            {
                "station": "KSFO",
                "time": iso(NOW),
                "lat": 37.6,
                "lon": -122.4,
                "temperature": quantity(None, "wmoUnit:degC"),
                "windSpeed": quantity(9.0, "wmoUnit:m_s-1"),
                "description": None,
            }
        ],
    )
    reports = parse_weather(payload, "KSFO")
    assert reports[0]["temperature_c"] is None
    assert reports[0]["wind_kmh"] is None  # m/s is not silently converted
    assert reports[0]["description"] is None


def test_weather_rejects_station_mismatch_and_naive_timestamp():
    payload = weather_payload(
        "KSEA",
        [{"station": "KSEA", "time": iso(NOW), "lat": 47.4, "lon": -122.3}],
    )
    with pytest.raises(PayloadError):
        parse_weather(payload, "KSFO")
    coarse = weather_payload(
        "KSFO",
        [{"station": "KSFO", "time": "2027-01-15T08:00:00", "lat": 37.6, "lon": -122.4}],
    )
    with pytest.raises(PayloadError):
        parse_weather(coarse, "KSFO")


def test_weather_dedups_repeated_observation_timestamp():
    report = {"station": "KSFO", "time": iso(NOW), "lat": 37.6, "lon": -122.4}
    payload = weather_payload("KSFO", [report, dict(report) | {"description": "dup"}])
    assert len(parse_weather(payload, "KSFO")) == 1


def test_parse_source_dispatch_rejects_unknown_source():
    with pytest.raises(PayloadError):
        parse_source("weather-KDEN", {})
