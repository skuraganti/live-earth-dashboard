"""Synthetic fixtures only. These are labeled simulated payloads, not fetched data."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.sources import USGS_ID

NOW = 1_800_000_000_000  # fixed synthetic clock: 2027-01-15T08:00:00Z
USGS_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson"


class Clock:
    def __init__(self, value: int = NOW):
        self.value = value

    def __call__(self) -> int:
        return self.value


def usgs_payload(events, generated=NOW - 60_000):
    return {
        "type": "FeatureCollection",
        "metadata": {"generated": generated, "count": len(events)},
        "features": [
            {
                "type": "Feature",
                "id": event["id"],
                "properties": {
                    "mag": event.get("mag"),
                    "type": event.get("type", "earthquake"),
                    "place": event.get("place"),
                    "time": event["time"],
                    "updated": event.get("updated", event["time"]),
                    "status": event.get("status", "reviewed"),
                    "url": event.get("url"),
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [event["lon"], event["lat"], event.get("depth_km", 10.0)],
                },
            }
            for event in events
        ],
    }


def weather_payload(station, reports):
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "id": f"urn:{station}:{report['time']}",
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [report["lon"], report["lat"]]},
                "properties": {
                    "stationId": station,
                    "timestamp": report["time"],
                    "textDescription": report.get("description"),
                    "temperature": report.get("temperature"),
                    "windSpeed": report.get("windSpeed"),
                },
            }
            for report in reports
        ],
    }


def quantity(value, unit):
    if value is None and unit is None:
        return None
    return {"unitCode": unit, "value": value}


def iso(epoch_ms: int) -> str:
    import datetime

    return datetime.datetime.fromtimestamp(epoch_ms / 1000, datetime.timezone.utc).isoformat()


def station_report(station, epoch_ms, lat, lon, temp=15.0, wind=10.0, description="Clear"):
    return {
        "station": station,
        "time": iso(epoch_ms),
        "lat": lat,
        "lon": lon,
        "temperature": quantity(temp, "wmoUnit:degC"),
        "windSpeed": quantity(wind, "wmoUnit:km_h-1"),
        "description": description,
    }


STATION_COORDS = {"KSFO": (37.62, -122.38), "KSEA": (47.45, -122.31), "KNYC": (40.78, -73.97)}


@pytest.fixture
def seed_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "seed"
    directory.mkdir()
    return directory


def write_seed(seed_dir: Path, name: str, payload: object, url: str, retrieved: int) -> str:
    body = json.dumps(payload).encode()
    digest = hashlib.sha256(body).hexdigest()
    (seed_dir / f"{name}.json").write_bytes(body)
    manifest_path = seed_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else []
    manifest.append(
        {
            "name": name,
            "url": url,
            "retrieved_at": iso(retrieved),
            "sha256": digest,
            "bytes": len(body),
            "features": len(payload.get("features", [])),
        }
    )
    manifest_path.write_text(json.dumps(manifest))
    return digest


def seed_full(seed_dir: Path, *, retrieved: int = NOW - 120_000, events=None) -> Path:
    events = (
        events
        if events is not None
        else [
            {
                "id": "ev1",
                "mag": 4.2,
                "place": "10 km N of Somewhere",
                "time": NOW - 3_600_000,
                "lat": 37.7,
                "lon": -122.4,
                "updated": NOW - 3_500_000,
            }
        ]
    )
    write_seed(
        seed_dir,
        "usgs",
        usgs_payload(events),
        "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson",
        retrieved,
    )
    for station, (lat, lon) in STATION_COORDS.items():
        write_seed(
            seed_dir,
            f"weather-{station}",
            weather_payload(
                station,
                [
                    station_report(station, NOW - 3_600_000, lat, lon, temp=18.0, wind=12.0),
                    station_report(
                        station, NOW - 7_200_000, lat, lon, temp=None, wind=None, description=None
                    ),
                ],
            ),
            f"https://api.weather.gov/stations/{station}/observations?limit=48",
            retrieved,
        )
    return seed_dir


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def offline_fetcher():
    """Returns a dict of url -> payload; unlisted URLs raise."""

    calls: list[str] = []

    def fetch(url: str):
        calls.append(url)
        if url in payloads:
            result = payloads[url]
            if isinstance(result, Exception):
                raise result
            return result
        raise AssertionError(f"unexpected fetch {url}")

    payloads: dict[str, object] = {
        "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson": {
            "type": "FeatureCollection",
            "metadata": {"generated": NOW},
            "features": [],
        },
        **{
            f"https://api.weather.gov/stations/{station}/observations?limit=48": {
                "type": "FeatureCollection",
                "features": [],
            }
            for station in STATION_COORDS
        },
    }
    fetch.calls = calls
    fetch.payloads = payloads
    return fetch


@pytest.fixture
def client(tmp_path, seed_dir, clock, offline_fetcher):
    seed_full(seed_dir)
    app = create_app(
        db_path=str(tmp_path / "test.sqlite"),
        seed_dir=str(seed_dir),
        clock=clock,
        fetcher=offline_fetcher,
        auto_poll=False,
    )
    with TestClient(app, base_url="http://localhost") as test_client:
        test_client.store = app.state.store
        test_client.clock = clock
        test_client.app_instance = app
        yield test_client
    app.state.store.close()


@pytest.fixture
def empty_client(tmp_path, seed_dir, clock, offline_fetcher):
    """No seed files: exercises the missing/empty state."""
    app = create_app(
        db_path=str(tmp_path / "empty.sqlite"),
        seed_dir=None,
        clock=clock,
        fetcher=offline_fetcher,
        auto_poll=False,
    )
    with TestClient(app, base_url="http://localhost") as test_client:
        test_client.store = app.state.store
        test_client.clock = clock
        test_client.app_instance = app
        yield test_client
    app.state.store.close()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any real HTTP attempt in tests is a bug."""

    def explode(*args, **kwargs):
        raise AssertionError("network access attempted in test")

    monkeypatch.setattr("httpx.HTTPTransport.handle_request", explode)
    monkeypatch.setattr("httpx.AsyncHTTPTransport.handle_async_request", explode)


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    monkeypatch.delenv("EARTH_DB", raising=False)
    monkeypatch.delenv("EARTH_SEED_DIR", raising=False)
    monkeypatch.delenv("EARTH_AUTO_POLL", raising=False)


def as_json(payload: object) -> bytes:
    return json.dumps(payload).encode()


__all__ = [
    "USGS_ID",
    "USGS_URL",
    "as_json",
    "iso",
    "quantity",
    "seed_full",
    "station_report",
    "usgs_payload",
    "weather_payload",
    "write_seed",
    "STATION_COORDS",
    "NOW",
]
