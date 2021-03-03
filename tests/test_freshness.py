"""Freshness is source-time based, not load/ingestion-time based."""

from __future__ import annotations

import hashlib
import json

from app.main import create_app
from app.sources import CLOCK_SKEW_MS, FRESH_MS, USGS_ID
from tests.conftest import NOW, USGS_URL


def _apply(store, generated):
    payload = {
        "type": "FeatureCollection",
        "metadata": {"generated": generated},
        "features": [
            {
                "type": "Feature",
                "id": "e1",
                "properties": {
                    "mag": 3.0,
                    "place": "P",
                    "time": NOW - 10_000,
                    "updated": NOW - 10_000,
                    "status": "reviewed",
                },
                "geometry": {"type": "Point", "coordinates": [20.0, 10.0, 5.0]},
            }
        ],
    }
    digest = hashlib.sha256(json.dumps(payload).encode()).hexdigest()
    store.apply_payload(USGS_ID, USGS_URL, payload, digest, NOW, seeded=False)


def test_freshness_uses_observed_time_not_ingestion(client):
    # Ingestion succeeded at NOW (last_success), but the feed generation is old,
    # so the source reads "stale" even though it was just loaded.
    _apply(client.store, NOW - 6 * 3_600_000)  # 6 hours old
    source = next(s for s in client.get("/api/state").json()["sources"] if s["id"] == USGS_ID)
    assert source["last_success"] == NOW
    assert source["observed_at"] == NOW - 6 * 3_600_000
    assert source["state"] == "stale"


def test_old_cache_does_not_become_live_on_reopen(tmp_path, clock, offline_fetcher):
    app = create_app(
        db_path=str(tmp_path / "r.sqlite"),
        seed_dir=None,
        clock=clock,
        fetcher=offline_fetcher,
        auto_poll=False,
    )
    _apply(app.state.store, clock() - 4 * 3_600_000)
    source = next(
        s for s in app.state.store.state(None, None, 300)["sources"] if s["id"] == USGS_ID
    )
    assert source["state"] == "stale"
    app.state.store.close()


def test_clock_skew_is_flaged_not_fresh(client):
    # Feed generated in the future: must not be reported as "fresh".
    _apply(client.store, NOW + 2 * CLOCK_SKEW_MS)
    source = next(s for s in client.get("/api/state").json()["sources"] if s["id"] == USGS_ID)
    assert source["state"] == "clock_skew"


def test_fresh_threshold_is_two_hours(client):
    _apply(client.store, NOW - FRESH_MS // 2)
    source = next(s for s in client.get("/api/state").json()["sources"] if s["id"] == USGS_ID)
    assert source["state"] == "fresh"
