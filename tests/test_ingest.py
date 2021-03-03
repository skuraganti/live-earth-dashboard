"""Ingestion, revision ordering, dedup, seed provenance, failure retention."""

from __future__ import annotations

import hashlib
import json

import pytest

from app.main import create_app
from app.sources import USGS_ID
from tests.conftest import (
    NOW,
    iso,
    seed_full,
    station_report,
    usgs_payload,
    weather_payload,
    write_seed,
)

USGS_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson"


def event(event_id="ev1", updated=NOW, mag=3.0):
    return {
        "id": event_id,
        "mag": mag,
        "place": "Somewhere",
        "time": NOW - 1000,
        "lat": 10.0,
        "lon": 20.0,
        "updated": updated,
    }


def test_seed_ingests_and_marks_provenance(client):
    state = client.get("/api/state").json()
    assert state["mode"] == "current"
    assert state["counts"]["events"] == 1
    assert len(state["weather"]) == 3
    usgs = next(s for s in state["sources"] if s["id"] == USGS_ID)
    # last_success is the manifest retrieval time, not app start time.
    assert usgs["last_success"] == NOW - 120_000
    assert usgs["state"] == "fresh"
    snapshots = client.get("/api/snapshots").json()
    seeded = [s for s in snapshots if s["source_id"] == USGS_ID]
    assert seeded[0]["seeded"] == 1
    assert (
        seeded[0]["sha256"]
        == hashlib.sha256((client.store.seed_dir / "usgs.json").read_bytes()).hexdigest()
    )


def test_seed_hash_mismatch_is_rejected(tmp_path, seed_dir, clock, offline_fetcher):
    seed_full(seed_dir)
    (seed_dir / "usgs.json").write_text(json.dumps(usgs_payload([event()])))
    with pytest.raises(ValueError, match="checksum mismatch"):
        create_app(
            db_path=str(tmp_path / "x.sqlite"),
            seed_dir=str(seed_dir),
            clock=clock,
            fetcher=offline_fetcher,
            auto_poll=False,
        )


def test_unknown_seed_filenames_are_ignored(seed_dir, tmp_path, clock, offline_fetcher):
    seed_full(seed_dir)
    (seed_dir / "mystery.json").write_text("{}")
    app = create_app(
        db_path=str(tmp_path / "y.sqlite"),
        seed_dir=str(seed_dir),
        clock=clock,
        fetcher=offline_fetcher,
        auto_poll=False,
    )
    assert app.state.store.state(None, None, 300)["counts"]["events"] == 1
    app.state.store.close()


def test_repeat_snapshot_does_not_inflate_counts(client):
    store = client.store
    payload = usgs_payload([event()])
    digest = hashlib.sha256(json.dumps(payload).encode()).hexdigest()
    for _ in range(3):
        store.apply_payload(USGS_ID, USGS_URL, payload, digest, NOW, seeded=False)
    assert client.get("/api/state").json()["counts"]["events"] == 1


def test_stale_revision_cannot_overwrite_newer(client):
    store = client.store
    newer = usgs_payload([event(updated=NOW, mag=4.4)])
    store.apply_payload(USGS_ID, USGS_URL, newer, "a" * 64, NOW, seeded=False)
    older = usgs_payload([event(updated=NOW - 600_000, mag=2.5)])
    store.apply_payload(USGS_ID, USGS_URL, older, "b" * 64, NOW, seeded=False)
    state = client.get("/api/state").json()
    assert state["events"][0]["mag"] == 4.4
    assert state["events"][0]["updated"] == NOW


def test_equal_revision_updates_fields(client):
    store = client.store
    store.apply_payload(
        USGS_ID, USGS_URL, usgs_payload([event(updated=NOW, mag=4.4)]), "a" * 64, NOW, seeded=False
    )
    store.apply_payload(
        USGS_ID, USGS_URL, usgs_payload([event(updated=NOW, mag=4.6)]), "b" * 64, NOW, seeded=False
    )
    state = client.get("/api/state").json()
    assert state["events"][0]["mag"] == 4.6
    assert state["events"][0]["source_sha256"] == "b" * 64


def test_malformed_payload_rolls_back_every_field(client, empty_client):
    store = empty_client.store
    good = usgs_payload([event()])
    store.apply_payload(USGS_ID, USGS_URL, good, "a" * 64, NOW, seeded=False)
    before = empty_client.get("/api/snapshots").json()
    broken = usgs_payload([event("ev9", mag=float("inf"))])
    with pytest.raises(Exception):
        store.apply_payload(USGS_ID, USGS_URL, broken, "c" * 64, NOW, seeded=False)
    after = empty_client.get("/api/snapshots").json()
    assert len(before) == len(after)
    assert empty_client.get("/api/state").json()["counts"]["events"] == 1


def test_partial_write_failure_rolls_back_prior_rows(client, empty_client):
    """A payload that fails midway must not leave earlier rows committed."""
    store = empty_client.store
    payload = usgs_payload([event("ok1", updated=NOW), event("ok2", mag=float("nan"), updated=NOW)])
    with pytest.raises(Exception):
        store.apply_payload(USGS_ID, USGS_URL, payload, "d" * 64, NOW, seeded=False)
    assert empty_client.get("/api/state").json()["counts"]["events"] == 0


def test_weather_dedup_by_station_and_timestamp(client):
    store = client.store
    for _ in range(2):
        store.apply_payload(
            "weather-KSFO",
            "https://api.weather.gov/stations/KSFO/observations?limit=48",
            weather_payload(
                "KSFO",
                [station_report("KSFO", NOW - 3_600_000, 37.62, -122.38, temp=19.0, wind=11.0)],
            ),
            "e" * 64,
            NOW,
            seeded=False,
        )
    weather = client.get("/api/state").json()["weather"]
    assert len([w for w in weather if w["station"] == "KSFO"]) == 1
    assert next(w for w in weather if w["station"] == "KSFO")["temperature_c"] == 19.0


def test_seeded_null_observations_stay_null(client):
    weather = client.get("/api/state").json()["weather"]
    for report in weather:
        assert report["temperature_c"] == 18.0  # latest report is the non-null one
    replay = client.get("/api/state", params={"until": NOW - 3_600_000}).json()
    sf = next(w for w in replay["weather"] if w["station"] == "KSFO")
    assert sf["time"] == NOW - 3_600_000


def test_source_failure_retains_last_good_and_reports_error(client):
    store = client.store
    before = client.get("/api/state").json()["events"]
    store.record_failure(USGS_ID, USGS_URL, "FetchError", NOW)
    state = client.get("/api/state").json()
    assert state["events"] == before
    usgs = next(s for s in state["sources"] if s["id"] == USGS_ID)
    assert usgs["state"] == "error"
    assert usgs["error"] == "FetchError"
    assert usgs["last_success"] == NOW - 120_000
    assert usgs["age_seconds"] == pytest.approx(60.0)


def test_attempt_and_snapshot_history_is_bounded(client):
    store = client.store
    payload = usgs_payload([event()])
    digest = hashlib.sha256(json.dumps(payload).encode()).hexdigest()
    for _ in range(40):
        store.apply_payload(USGS_ID, USGS_URL, payload, digest, NOW, seeded=False)
    rows = store.conn.execute(
        "SELECT COUNT(*) n FROM attempts WHERE source_id=?", (USGS_ID,)
    ).fetchone()["n"]
    snaps = store.conn.execute(
        "SELECT COUNT(*) n FROM snapshots WHERE source_id=?", (USGS_ID,)
    ).fetchone()["n"]
    assert rows == 32
    assert snaps == 32
    # Entities are deduped independently of bounded history.
    assert client.get("/api/state").json()["counts"]["events"] == 1


def test_persistence_reopen_keeps_rows(tmp_path, seed_dir, clock, offline_fetcher):
    seed_full(seed_dir)
    db = tmp_path / "persist.sqlite"
    first = create_app(
        db_path=str(db),
        seed_dir=str(seed_dir),
        clock=clock,
        fetcher=offline_fetcher,
        auto_poll=False,
    )
    first.state.store.apply_payload(
        USGS_ID,
        USGS_URL,
        usgs_payload([event("keep", updated=NOW)]),
        "f" * 64,
        NOW,
        seeded=False,
    )
    first.state.store.close()
    second = create_app(
        db_path=str(db),
        seed_dir=str(seed_dir),
        clock=clock,
        fetcher=offline_fetcher,
        auto_poll=False,
    )
    state = second.state.store.state(None, None, 300)
    assert state["counts"]["events"] == 2
    assert "keep" in {e["id"] for e in state["events"]}
    second.state.store.close()


def test_no_seed_means_missing_state_until_refresh(tmp_path, clock, offline_fetcher):
    app = create_app(
        db_path=str(tmp_path / "none.sqlite"),
        seed_dir=str(tmp_path / "absent"),
        clock=clock,
        fetcher=offline_fetcher,
        auto_poll=False,
    )
    state = app.state.store.state(None, None, 300)
    assert state["counts"] == {"events": 0, "weather": 0}
    assert state["range"] == {"start": None, "end": None}
    assert len(state["sources"]) == 4
    assert all(source["state"] == "missing" for source in state["sources"])
    app.state.store.close()


def test_seed_preserves_manifest_retrieval_date_not_load_time(
    seed_dir, tmp_path, clock, offline_fetcher
):
    retrieved = NOW - 86_400_000
    write_seed(seed_dir, "usgs", usgs_payload([event()]), USGS_URL, retrieved)
    app = create_app(
        db_path=str(tmp_path / "dates.sqlite"),
        seed_dir=str(seed_dir),
        clock=clock,
        fetcher=offline_fetcher,
        auto_poll=False,
    )
    row = app.state.store.snapshots()[0]
    assert row["retrieved_at"] == retrieved
    assert row["retrieved_at"] != clock()
    app.state.store.close()


def test_iso_helper_roundtrip():
    assert iso(NOW).startswith("2027-01-15T08:00:00")
