"""Contract regressions for source ordering, event typing, and bounded reads."""

from __future__ import annotations

import hashlib
import json

from app.main import MAX_REQUEST_BYTES, create_app
from app.sources import USGS_ID
from tests.conftest import NOW, USGS_URL, station_report, usgs_payload, weather_payload


def test_refresh_evaluates_existing_watch(client, offline_fetcher):
    client.post(
        "/api/watches",
        json={"name": "Bay", "lat": 37.7, "lon": -122.4, "radius_km": 200, "min_mag": 3},
    )
    before = client.get("/api/alerts").json()
    payload = usgs_payload(
        [
            {
                "id": "new-quake",
                "type": "earthquake",
                "mag": 4,
                "time": NOW - 1000,
                "lat": 37.7,
                "lon": -122.4,
            }
        ],
        generated=NOW,
    )
    offline_fetcher.payloads[USGS_URL] = payload
    for station in ("KSFO", "KSEA", "KNYC"):
        offline_fetcher.payloads[
            f"https://api.weather.gov/stations/{station}/observations?limit=48"
        ] = weather_payload(
            station,
            [
                station_report(
                    station,
                    NOW,
                    *{
                        "KSFO": (37.62, -122.38),
                        "KSEA": (47.45, -122.31),
                        "KNYC": (40.78, -73.97),
                    }[station],
                )
            ],
        )
    response = client.post("/api/refresh")
    assert response.status_code == 200
    alerts = client.get("/api/alerts").json()
    assert len(alerts) == len(before) + 1
    assert alerts[-1]["evidence_id"] == "new-quake"


def test_older_seed_does_not_downgrade_cached_revision(tmp_path, seed_dir, clock, offline_fetcher):
    app = create_app(
        db_path=str(tmp_path / "restart.sqlite"),
        seed_dir=str(seed_dir),
        clock=clock,
        fetcher=offline_fetcher,
        auto_poll=False,
    )
    app.state.store.apply_payload(
        USGS_ID,
        USGS_URL,
        usgs_payload(
            [{"id": "stable", "mag": 5, "time": NOW, "lat": 1, "lon": 2, "updated": NOW}],
            generated=NOW,
        ),
        "a" * 64,
        NOW,
        seeded=False,
    )
    app.state.store.close()
    reopened = create_app(
        db_path=str(tmp_path / "restart.sqlite"),
        seed_dir=str(seed_dir),
        clock=clock,
        fetcher=offline_fetcher,
        auto_poll=False,
    )
    row = reopened.state.store.conn.execute(
        "SELECT mag,updated FROM events WHERE id='stable'"
    ).fetchone()
    assert row["mag"] == 5
    assert row["updated"] == NOW
    reopened.state.store.close()


def test_chunked_request_body_is_bounded(client):
    def chunks():
        yield b"{" + b" " * MAX_REQUEST_BYTES
        yield b"}"

    # TestClient sends a streamed body without Content-Length.
    response = client.post("/api/watches", content=chunks())
    assert response.status_code == 413


def test_real_feed_preserves_event_type_and_alerts_only_quakes(empty_client):
    body = {
        "type": "FeatureCollection",
        "metadata": {"generated": NOW},
        "features": [
            {
                "type": "Feature",
                "id": "quake",
                "properties": {
                    "type": "earthquake",
                    "mag": 4,
                    "time": NOW - 1000,
                    "updated": NOW,
                },
                "geometry": {"type": "Point", "coordinates": [-122.4, 37.7, 5]},
            },
            {
                "type": "Feature",
                "id": "slide",
                "properties": {
                    "type": "landslide",
                    "mag": 4,
                    "time": NOW - 1000,
                    "updated": NOW,
                },
                "geometry": {"type": "Point", "coordinates": [-122.4, 37.7, 5]},
            },
        ],
    }
    digest = hashlib.sha256(json.dumps(body).encode()).hexdigest()
    empty_client.store.apply_payload(USGS_ID, USGS_URL, body, digest, NOW, seeded=False)
    events = empty_client.get("/api/state").json()["events"]
    types = {event["id"]: event["type"] for event in events}
    assert types == {"quake": "earthquake", "slide": "landslide"}

    empty_client.post(
        "/api/watches",
        json={"name": "Bay", "lat": 37.7, "lon": -122.4, "radius_km": 200, "min_mag": 3},
    )
    assert [alert["evidence_id"] for alert in empty_client.get("/api/alerts").json()] == ["quake"]


def test_failed_refresh_retains_last_good_and_later_recovers(empty_client, offline_fetcher):
    url = USGS_URL
    good = usgs_payload(
        [{"id": "retained", "mag": 3, "time": NOW, "lat": 1, "lon": 2}], generated=NOW
    )
    offline_fetcher.payloads[url] = good
    first = empty_client.post("/api/refresh")
    assert first.status_code == 200
    assert empty_client.get("/api/state").json()["counts"]["events"] == 1

    offline_fetcher.payloads[url] = ValueError("synthetic failure")
    empty_client.clock.value += 61_000
    failed = empty_client.post("/api/refresh")
    assert failed.json()["outcomes"][0]["ok"] is False
    state = empty_client.get("/api/state").json()
    assert state["counts"]["events"] == 1
    source = next(source for source in state["sources"] if source["id"] == USGS_ID)
    assert source["state"] == "error"

    offline_fetcher.payloads[url] = good
    empty_client.clock.value += 61_000
    recovered = empty_client.post("/api/refresh")
    assert recovered.json()["outcomes"][0]["ok"] is True
    source = next(
        source
        for source in empty_client.get("/api/state").json()["sources"]
        if source["id"] == USGS_ID
    )
    assert source["error"] is None
