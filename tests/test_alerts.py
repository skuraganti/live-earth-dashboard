"""Watch evaluation, alert dedup/ack, and the no-alerts-from-replay rule."""

from __future__ import annotations


def test_fresh_earthquake_in_radius_creates_alert(client):
    watch = client.post(
        "/api/watches",
        json={
            "name": "Bay Area",
            "lat": 37.7,
            "lon": -122.4,
            "radius_km": 200.0,
            "min_mag": 3.0,
        },
    ).json()
    alerts = client.get("/api/alerts").json()
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["watch_id"] == watch["id"]
    assert alert["kind"] == "earthquake"
    assert alert["evidence_id"] == "ev1"
    assert alert["acknowledged"] is False


def test_alert_deduplicates_by_watch_kind_evidence(client):
    client.post(
        "/api/watches",
        json={
            "name": "Bay Area",
            "lat": 37.7,
            "lon": -122.4,
            "radius_km": 200.0,
            "min_mag": 3.0,
        },
    )
    # Re-evaluating the same watch with unchanged state must not add duplicate alerts.
    watch = client.get("/api/watches").json()[0]
    client.store.evaluate_watch(watch, client.clock())
    assert len(client.get("/api/alerts").json()) == 1


def test_temperature_and_wind_threshold_alerts(client):
    client.post(
        "/api/watches",
        json={
            "name": "SFO Site",
            "lat": 37.62,
            "lon": -122.38,
            "radius_km": 5.0,
            "max_temperature_c": 15.0,
            "max_wind_kmh": 10.0,
        },
    )
    alerts = client.get("/api/alerts").json()
    kinds = {a["kind"] for a in alerts}
    assert "temperature" in kinds  # 18.0 C >= 15.0
    assert "wind" in kinds  # 12.0 km/h >= 10.0


def test_ack_updates_acknowledgment(client):
    client.post(
        "/api/watches",
        json={
            "name": "Bay Area",
            "lat": 37.7,
            "lon": -122.4,
            "radius_km": 200.0,
            "min_mag": 3.0,
        },
    )
    alert_id = client.get("/api/alerts").json()[0]["id"]
    assert client.post(f"/api/alerts/{alert_id}/ack").status_code == 200
    assert client.get("/api/alerts").json()[0]["acknowledged"] is True
    assert client.post("/api/alerts/999999/ack").status_code == 404


def test_stale_earthquake_is_not_alerted(client):
    # Seed an event older than the 24h recency window via a fresh source.
    from app.sources import USGS_ID
    from tests.conftest import NOW, USGS_URL, usgs_payload

    store = client.store
    payload = usgs_payload(
        [
            {
                "id": "old1",
                "mag": 5.0,
                "place": "Old",
                "time": NOW - 30 * 3_600_000,
                "lat": 37.7,
                "lon": -122.4,
                "updated": NOW - 30 * 3_600_000,
            }
        ],
        generated=NOW - 60_000,
    )
    store.apply_payload(USGS_ID, USGS_URL, payload, "f" * 64, NOW, seeded=False)
    client.post(
        "/api/watches",
        json={
            "name": "Bay Area",
            "lat": 37.7,
            "lon": -122.4,
            "radius_km": 200.0,
            "min_mag": 3.0,
        },
    )
    alerts = client.get("/api/alerts").json()
    assert all(a["evidence_id"] != "old1" for a in alerts)


def test_requesting_replay_never_creates_alerts(client):
    before = len(client.get("/api/alerts").json())
    for _ in range(3):
        client.get("/api/state", params={"until": 0})
    assert len(client.get("/api/alerts").json()) == before


def test_watch_with_null_thresholds_never_fires_null_data(client):
    # Null temp/wind thresholds mean "no threshold"; null observations must not match.
    watch = client.post(
        "/api/watches",
        json={
            "name": "Nulls",
            "lat": 37.62,
            "lon": -122.38,
            "radius_km": 5.0,
        },
    ).json()
    alerts = client.get("/api/alerts").json()
    assert all(a["watch_id"] != watch["id"] for a in alerts)
