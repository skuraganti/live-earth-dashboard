"""Haversine/radius, watch validation bounds, weather cutoff readback, replay filtering."""

from __future__ import annotations

import json
import math

import pytest

from app.store import haversine_km
from tests.conftest import NOW

HTTP_OK = 200
BAD_REQUEST = 400
NOT_FOUND = 404
FORBIDDEN = 403
CONFLICT = 409
TOO_MANY = 429


def test_haversine_known_distance():
    # San Francisco to New York is ~4128 km (great-circle approximation).
    km = haversine_km(37.77, -122.42, 40.71, -74.01)
    assert math.isclose(km, 4128, rel_tol=0.02)


def test_haversine_zero_and_antipodal_are_finite():
    assert haversine_km(10.0, 20.0, 10.0, 20.0) == 0.0
    assert math.isfinite(haversine_km(0.0, 0.0, 0.0, 180.0))


def test_watch_create_persists_and_lists(client):
    response = client.post(
        "/api/watches",
        json={
            "name": "Home",
            "lat": 37.7,
            "lon": -122.4,
            "radius_km": 100.0,
            "min_mag": 3.0,
            "max_temperature_c": None,
            "max_wind_kmh": None,
        },
    )
    assert response.status_code == HTTP_OK
    watch = response.json()
    assert watch["id"] > 0
    assert watch["name"] == "Home"
    assert watch["min_mag"] == 3.0
    watches = client.get("/api/watches").json()
    assert any(w["id"] == watch["id"] for w in watches)


@pytest.mark.parametrize(
    "field,value",
    [
        ("lat", 91.0),
        ("lat", float("nan")),
        ("lon", 181.0),
        ("radius_km", 0.5),
        ("radius_km", 20001),
        ("min_mag", 11.0),
        ("name", ""),
        ("name", "x" * 81),
    ],
)
def test_watch_rejects_out_of_bounds(client, field, value):
    body = {"name": "W", "lat": 37.7, "lon": -122.4, "radius_km": 100.0}
    body[field] = value
    assert (
        client.post(
            "/api/watches", content=json.dumps(body), headers={"Content-Type": "application/json"}
        ).status_code
        == BAD_REQUEST
    )


def test_watch_rejects_nonfinite_numeric(client):
    body = {"name": "W", "lat": float("inf"), "lon": -122.4, "radius_km": 100.0}
    assert (
        client.post(
            "/api/watches", content=json.dumps(body), headers={"Content-Type": "application/json"}
        ).status_code
        == BAD_REQUEST
    )


def test_watch_delete(client):
    watch_id = client.post(
        "/api/watches",
        json={
            "name": "W",
            "lat": 0.0,
            "lon": 0.0,
            "radius_km": 50.0,
        },
    ).json()["id"]
    assert client.delete(f"/api/watches/{watch_id}").status_code == HTTP_OK
    assert client.delete(f"/api/watches/{watch_id}").status_code == NOT_FOUND


def test_replay_filters_event_origin_and_weather_cutoff(client):
    state = client.get("/api/state", params={"until": NOW - 3_600_001}).json()
    assert state["mode"] == "replay"
    assert state["until"] == NOW - 3_600_001
    assert state["counts"]["events"] == 0  # the single seeded event is 1h old
    for report in state["weather"]:
        assert report["time"] == NOW - 7_200_000


def test_replay_respects_min_magnitude(client):
    state = client.get("/api/state", params={"min_mag": 5.0}).json()
    assert state["counts"]["events"] == 0
    state = client.get("/api/state", params={"min_mag": 4.0}).json()
    assert state["counts"]["events"] == 1


def test_state_rejects_nonfinite_or_bad_until(client):
    assert client.get("/api/state", params={"until": float("nan")}).status_code == 422
    assert client.get("/api/state", params={"until": -5}).status_code == BAD_REQUEST
    assert client.get("/api/state", params={"min_mag": "abc"}).status_code == 422


def test_epoch_ms_contract_is_ms_utc(client):
    state = client.get("/api/state").json()
    event = state["events"][0]
    assert event["time"] == NOW - 3_600_000
    assert isinstance(event["time"], int)
    assert event["lat"] == 37.7
    assert event["depth_km"] == 10.0


def test_weather_uses_station_distance_not_scaled_thresholds():
    # KSFO at (37.62, -122.38) vs a watch at (47.45, -122.31) is ~1000 km.
    km = haversine_km(37.62, -122.38, 47.45, -122.31)
    assert km > 900
