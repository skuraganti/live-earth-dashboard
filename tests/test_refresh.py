"""Synthetic, offline HTTP refresh concurrency, guards, failure and lifespan probes."""

import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.fetch import FetchError
from app.main import create_app
from app.sources import SOURCE_URLS
from tests.conftest import seed_full


def empty_payload(_url):
    return {"type": "FeatureCollection", "metadata": {"generated": 0}, "features": []}


def test_refresh_enforces_cooldown_and_in_flight(clock):
    started, release = threading.Event(), threading.Event()
    calls = []

    def fetch(url):
        calls.append(url)
        if len(calls) == 1:
            started.set()
            assert release.wait(3), "test did not release mock fetch"
        return empty_payload(url)

    app = create_app(db_path=":memory:", seed_dir=None, clock=clock, fetcher=fetch, auto_poll=False)
    with TestClient(app, base_url="http://localhost") as client:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(client.post, "/api/refresh")
            try:
                assert started.wait(2)
                assert client.post("/api/refresh").status_code == 409
            finally:
                release.set()
            assert pending.result(timeout=3).status_code == 200
        assert len(calls) == 4
        assert client.post("/api/refresh").status_code == 429
        clock.value += 61_000
        assert client.post("/api/refresh").status_code == 200
        assert len(calls) == 8


def test_host_and_origin_guard_all_reads_and_writes(client):
    assert client.get("/api/watches", headers={"host": "evil.com"}).status_code == 400
    assert client.post("/api/refresh", headers={"host": "evil.com"}).status_code == 400
    assert client.post("/api/refresh", headers={"origin": "https://evil.com"}).status_code == 403
    assert client.post("/api/refresh", headers={"sec-fetch-site": "cross-site"}).status_code == 403


def test_content_length_and_body_size_limits(client):
    huge = b"x" * 70_000
    assert client.post("/api/watches", content=huge).status_code == 413
    assert client.post("/api/watches", json={"name": "x" * 200}).status_code == 400
    assert client.post("/api/refresh", headers={"content-length": "10"}).status_code == 400


def test_failed_source_records_error_and_keeps_cache(seed_dir, tmp_path, clock):
    seed_full(seed_dir)

    def fail(_url):
        raise FetchError("Synthetic transport failure")

    app = create_app(
        db_path=str(tmp_path / "fail.db"),
        seed_dir=str(seed_dir),
        clock=clock,
        fetcher=fail,
        auto_poll=False,
    )
    with TestClient(app, base_url="http://localhost") as client:
        before = client.get("/api/state").json()
        outcome = client.post("/api/refresh").json()
        assert len(outcome["outcomes"]) == 4
        assert all(x["ok"] is False for x in outcome["outcomes"])
        after = client.get("/api/state").json()
        assert after["events"] == before["events"] and after["weather"] == before["weather"]
        assert all(x["state"] == "error" and x["error"] == "FetchError" for x in after["sources"])


def test_absent_seed_can_refresh_canonical_sources(tmp_path):
    calls = []

    def fetch(url):
        calls.append(url)
        return empty_payload(url)

    app = create_app(
        db_path=":memory:", seed_dir=str(tmp_path / "absent"), fetcher=fetch, auto_poll=False
    )
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/api/state").json()["counts"] == {"events": 0, "weather": 0}
        assert client.post("/api/refresh").status_code == 200
        assert calls == list(SOURCE_URLS.values())


def test_refresh_allows_no_origin_cli_and_keeps_cooldown():
    app = create_app(
        db_path=":memory:", seed_dir=None, clock=lambda: 0, fetcher=empty_payload, auto_poll=False
    )
    with TestClient(app, base_url="http://localhost") as client:
        assert client.post("/api/refresh").status_code == 200
        assert client.post("/api/refresh").status_code == 429
        assert client.post("/api/refresh", headers={"host": "example.com"}).status_code == 400


def test_poller_belongs_to_lifespan_and_joins_on_shutdown():
    calls = []

    def fetch(url):
        calls.append(url)
        return empty_payload(url)

    app = create_app(db_path=":memory:", seed_dir=None, fetcher=fetch, auto_poll=True)
    assert not hasattr(app.state, "poll_thread")
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/health").status_code == 200
        assert app.state.poll_thread.is_alive()
        assert len(calls) == 4
    assert not app.state.poll_thread.is_alive()
    assert app.state.store.closed
