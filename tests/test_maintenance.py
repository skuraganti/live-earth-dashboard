"""Stale-feed recovery end to end and watch-radius edges.

Synthetic fixtures only: every feed response comes from the offline fetcher or a direct
store write. No test performs a real USGS or NWS request.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.sources import COOLDOWN_MS, FRESH_MS, USGS_ID
from app.store import haversine_km
from tests.conftest import NOW, USGS_URL, station_report, usgs_payload, weather_payload

KSFO_URL = "https://api.weather.gov/stations/KSFO/observations?limit=48"
SITE = {"lat": 10.0, "lon": 20.0, "radius_km": 50.0, "min_mag": 3.0}


def _refresh(client) -> dict:
    client.clock.value += COOLDOWN_MS + 1_000
    response = client.post("/api/refresh")
    assert response.status_code == 200
    return response.json()


def _source(client, source_id: str) -> dict:
    return next(s for s in client.get("/api/state").json()["sources"] if s["id"] == source_id)


def _alert_keys(client) -> list[tuple[int, str, str]]:
    return sorted(
        (a["watch_id"], a["kind"], a["evidence_id"]) for a in client.get("/api/alerts").json()
    )


def _usgs_snapshots(client) -> int:
    return sum(s["source_id"] == USGS_ID for s in client.get("/api/snapshots").json())


def _watch(client, name: str, **fields) -> int:
    response = client.post("/api/watches", json={"name": name, **fields})
    assert response.status_code == 200
    return response.json()["id"]


def _quake(event_id: str, time: int, updated: int | None = None, mag: float = 4.0) -> dict:
    return {
        "id": event_id,
        "mag": mag,
        "time": time,
        "updated": updated or time,
        "lat": 10.0,
        "lon": 20.1,
    }


def _open(db_path: str, clock, fetcher) -> TestClient:
    app = create_app(db_path=db_path, seed_dir=None, clock=clock, fetcher=fetcher, auto_poll=False)
    client = TestClient(app, base_url="http://localhost")
    client.__enter__()
    client.clock = clock
    return client


def _durable_view(client) -> dict:
    state = client.get("/api/state").json()
    usgs_snapshots = [s for s in client.get("/api/snapshots").json() if s["source_id"] == USGS_ID]
    return {
        "source": {k: v for k, v in _source(client, USGS_ID).items() if k != "age_seconds"},
        "events": {e["id"]: (e["mag"], e["source_sha256"]) for e in state["events"]},
        "latest_usgs_sha256": usgs_snapshots[0]["sha256"],
        "watches": client.get("/api/watches").json(),
        "alerts": client.get("/api/alerts").json(),
    }


def test_stale_feed_recovery_end_to_end(tmp_path, clock, offline_fetcher):
    db_path = str(tmp_path / "recovery.sqlite")
    first = _quake("first", NOW - 60_000)
    client = _open(db_path, clock, offline_fetcher)
    try:
        offline_fetcher.payloads[USGS_URL] = usgs_payload([first], generated=NOW)
        early = _watch(client, "Early watch", **SITE)
        _refresh(client)
        assert _alert_keys(client) == [(early, "earthquake", "first")]
        good = _source(client, USGS_ID)
        # Provider time (feed "generated") and successful retrieval time are tracked separately.
        assert (good["state"], good["observed_at"], good["last_success"]) == (
            "fresh",
            NOW,
            clock.value,
        )
        alert_id = client.get("/api/alerts").json()[0]["id"]
        assert client.post(f"/api/alerts/{alert_id}/ack").status_code == 200
        snapshots = _usgs_snapshots(client)

        # A failed refresh keeps the last good cache and its timestamps and reports "error".
        offline_fetcher.payloads[USGS_URL] = ValueError("synthetic outage")
        outcome = _refresh(client)["outcomes"][0]
        assert (outcome["id"], outcome["ok"], outcome["error"]) == (USGS_ID, False, "ValueError")
        failed = _source(client, USGS_ID)
        assert failed["state"] == "error" and failed["error"] == "ValueError"
        assert failed["last_attempt"] == clock.value
        assert (failed["observed_at"], failed["last_success"]) == (
            good["observed_at"],
            good["last_success"],
        )
        assert [e["id"] for e in client.get("/api/state").json()["events"]] == ["first"]
        assert _usgs_snapshots(client) == snapshots

        # Cached evidence behind an errored source creates no alerts, even for a new watch.
        late_watch = _watch(client, "Late watch", **SITE)
        assert _alert_keys(client) == [(early, "earthquake", "first")]

        # A successful retrieval of an old-generated feed clears the error but stays "stale":
        # the retrieval is current, the provider time is not. Its new event alerts nobody.
        late = _quake("late", clock.value - 30_000)
        stale_generated = clock.value - FRESH_MS - 3_600_000
        offline_fetcher.payloads[USGS_URL] = usgs_payload([first, late], generated=stale_generated)
        assert _refresh(client)["outcomes"][0]["ok"] is True
        stale = _source(client, USGS_ID)
        assert (stale["state"], stale["error"]) == ("stale", None)
        assert (stale["observed_at"], stale["last_success"]) == (stale_generated, clock.value)
        assert set(_durable_view(client)["events"]) == {"first", "late"}
        assert _alert_keys(client) == [(early, "earthquake", "first")]
        before = _durable_view(client)
        assert {sha for _, sha in before["events"].values()} == {before["latest_usgs_sha256"]}
    finally:
        client.__exit__(None, None, None)

    # A real close and reopen of the same database keeps the stale status, timestamps, watches,
    # acknowledgement, event hashes and snapshot hash. Reopening fetches nothing and alerts nobody.
    calls = len(offline_fetcher.calls)
    clock.value += 10 * 60_000
    client = _open(db_path, clock, offline_fetcher)
    try:
        after = _durable_view(client)
        assert after == before
        assert after["source"]["state"] == "stale"
        assert [a["acknowledged"] for a in after["alerts"]] == [True]
        assert len(offline_fetcher.calls) == calls

        # A fresh success restores freshness and evaluates every watch once per evidence.
        offline_fetcher.payloads[USGS_URL] = usgs_payload([first, late], generated=clock.value)
        _refresh(client)
        assert _source(client, USGS_ID)["state"] == "fresh"
        expected = sorted(
            [
                (early, "earthquake", "first"),
                (early, "earthquake", "late"),
                (late_watch, "earthquake", "first"),
                (late_watch, "earthquake", "late"),
            ]
        )
        assert _alert_keys(client) == expected
        assert next(a for a in client.get("/api/alerts").json() if a["id"] == alert_id)[
            "acknowledged"
        ]

        # Repeating the feed, or a newer revision of the same event, never duplicates.
        revised = _quake("late", late["time"], updated=clock.value, mag=4.6)
        offline_fetcher.payloads[USGS_URL] = usgs_payload([first, revised], generated=clock.value)
        _refresh(client)
        _refresh(client)
        assert _alert_keys(client) == expected
        assert _durable_view(client)["events"]["late"][0] == 4.6
    finally:
        client.__exit__(None, None, None)


def test_weather_station_outage_blocks_alerts_until_fresh_recovery(client, offline_fetcher):
    offline_fetcher.payloads[KSFO_URL] = ValueError("synthetic station outage")
    _refresh(client)
    assert _source(client, "weather-KSFO")["state"] == "error"
    hot = _watch(client, "SFO heat", lat=37.62, lon=-122.38, radius_km=5.0, max_temperature_c=15.0)
    assert not [key for key in _alert_keys(client) if key[0] == hot]

    report_time = client.clock.value - 60_000
    offline_fetcher.payloads[KSFO_URL] = weather_payload(
        "KSFO", [station_report("KSFO", report_time, 37.62, -122.38, temp=30.0, wind=5.0)]
    )
    _refresh(client)
    _refresh(client)
    assert _source(client, "weather-KSFO")["state"] == "fresh"
    assert [key for key in _alert_keys(client) if key[0] == hot] == [
        (hot, "temperature", f"KSFO:{report_time}")
    ]


def _quake_client(empty_client, lat: float, lon: float):
    payload = usgs_payload(
        [{"id": "edge", "mag": 4.0, "time": NOW - 60_000, "lat": lat, "lon": lon}],
        generated=NOW - 60_000,
    )
    empty_client.store.apply_payload(USGS_ID, USGS_URL, payload, "e" * 64, NOW, seeded=False)
    return empty_client


@pytest.mark.parametrize("inside", [True, False])
def test_radius_boundary_is_inclusive(empty_client, inside):
    _quake_client(empty_client, 10.0, 21.0)
    distance = haversine_km(10.0, 20.0, 10.0, 21.0)
    radius = distance if inside else math.nextafter(distance, 0.0)
    watch = _watch(empty_client, "Edge", lat=10.0, lon=20.0, radius_km=radius, min_mag=3.0)
    assert _alert_keys(empty_client) == ([(watch, "earthquake", "edge")] if inside else [])


@pytest.mark.parametrize(
    "watch_at,event_at,radius_km,alerts",
    [
        ((0.0, 179.9), (0.0, -179.9), 25.0, True),  # ~22 km across the antimeridian
        ((0.0, 180.0), (0.0, -180.0), 1.0, True),  # the same meridian, written twice
        ((0.0, 179.9), (0.0, -179.9), 20.0, False),
        ((90.0, -45.0), (89.95, 135.0), 6.0, True),  # ~5.6 km over the North Pole
        ((-90.0, 0.0), (-90.0, 170.0), 1.0, True),  # every longitude is the South Pole
        ((89.95, 0.0), (89.95, 180.0), 6.0, False),  # ~11 km apart across the pole
    ],
)
def test_radius_across_antimeridian_and_poles(empty_client, watch_at, event_at, radius_km, alerts):
    _quake_client(empty_client, *event_at)
    watch = _watch(
        empty_client, "Wrap", lat=watch_at[0], lon=watch_at[1], radius_km=radius_km, min_mag=3.0
    )
    assert _alert_keys(empty_client) == ([(watch, "earthquake", "edge")] if alerts else [])


@pytest.mark.parametrize(
    "fields,status",
    [
        ({"lat": 0, "lon": 0, "radius_km": 1}, 200),
        ({"lat": 0, "lon": 0, "radius_km": 20000}, 200),
        ({"lat": 90, "lon": 180, "radius_km": 5}, 200),
        ({"lat": -90, "lon": -180, "radius_km": 5}, 200),
        ({"lat": 0, "lon": 0, "radius_km": 0}, 400),
        ({"lat": 0, "lon": 0, "radius_km": -5}, 400),
        ({"lat": 0, "lon": 0, "radius_km": 0.999}, 400),
        ({"lat": 0, "lon": 0, "radius_km": 20000.001}, 400),
        ({"lat": 0, "lon": 0, "radius_km": True}, 400),
        ({"lat": 0, "lon": 0, "radius_km": "100"}, 400),
        ({"lat": 0, "lon": 0, "radius_km": None}, 400),
        ({"lat": 0, "lon": 0}, 400),
        ({"lat": -90.0001, "lon": 0, "radius_km": 5}, 400),
        ({"lat": 0, "lon": 180.0001, "radius_km": 5}, 400),
    ],
)
def test_watch_radius_and_coordinate_validation(empty_client, fields, status):
    assert empty_client.post("/api/watches", json={"name": "W", **fields}).status_code == status


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e400", "9" * 400])
def test_watch_rejects_nonfinite_json_literals(empty_client, literal):
    body = '{"name":"W","lat":0,"lon":0,"radius_km":' + literal + "}"
    response = empty_client.post(
        "/api/watches", content=body, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400
    assert empty_client.get("/api/watches").json() == []


def test_largest_radius_does_not_reach_the_antipode():
    # The 20,000 km cap is just under half the great-circle circumference (~20,015 km).
    assert 20_000 < haversine_km(0.0, 0.0, 0.0, 180.0) < 20_016


UI_HARNESS = r"""
const vm = require('vm');
const fs = require('fs');
const elements = {};
const make = () => {
  const node = {value: '', textContent: '', className: '', hidden: false, disabled: false,
    children: [], listeners: {}, style: {}};
  node.addEventListener = (type, handler) => { node.listeners[type] = handler; };
  node.append = (...items) => { node.children.push(...items); };
  node.replaceChildren = (...items) => { node.children = items; };
  node.setAttribute = () => {};
  node.scrollIntoView = () => {};
  return node;
};
const document = {visibilityState: 'visible', createElement: make,
  getElementById: id => elements[id] || (elements[id] = make())};
const requests = [];
const intervals = [];
let holdEvidence = false;
const deferredEvidence = [];
const routes = {
  '/api/state': [200, {range: {start: null, end: null}, events: [], weather: [], sources: []}],
  '/api/watches': [200, []], '/api/alerts': [200, []], '/api/snapshots': [200, []],
  '/api/refresh': [429, {error: 'refresh cooling down'}],
};
async function fetch(url, options = {}) {
  requests.push((options.method || 'GET') + ' ' + url);
  const [status, body] = routes[url.split('?')[0]];
  const response = {ok: status < 400, status, json: async () => body};
  if (holdEvidence && ['/api/watches', '/api/alerts', '/api/snapshots'].includes(url))
    return new Promise(resolve => deferredEvidence.push(() => resolve(response)));
  return response;
}
const context = vm.createContext({document, fetch, URLSearchParams, console, Promise,
  setInterval: (handler, ms) => { intervals.push([handler, ms]); return intervals.length; },
  clearInterval: () => {}});
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
const settle = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  await settle();
  const states = () => requests.filter(r => r.startsWith('GET /api/state'));
  elements.magnitude.value = '-2';
  elements.magnitude.listeners.change();
  await settle();
  const allReported = states().at(-1);
  elements.magnitude.value = '3';
  elements.magnitude.listeners.change();
  await settle();
  const minimumThree = states().at(-1);
  await elements.refresh.listeners.click();
  await settle();
  const refreshNotice = elements.notice.textContent;
  requests.length = 0;
  const [poll] = intervals.filter(([, ms]) => ms === 30000);
  poll[0]();
  await settle();
  const polled = requests.slice().sort();
  const alert = {id: 7, watch_name: 'Synthetic race', kind: 'earthquake', message: 'Test',
    event_time: 0, evidence_id: 'race', source_url: 'https://earthquake.usgs.gov/earthquakes/eventpage/race',
    acknowledged: false};
  routes['/api/alerts'] = [200, [alert]];
  holdEvidence = true;
  const stale = vm.runInContext('loadLocalEvidence()', context);
  holdEvidence = false;
  routes['/api/alerts'] = [200, [{...alert, acknowledged: true}]];
  await vm.runInContext('loadLocalEvidence()', context);
  for (const resolve of deferredEvidence) resolve();
  await stale;
  const texts = nodes => nodes.flatMap(n => [n.textContent || '', ...texts(n.children)]);
  const finalAlertText = texts(elements.alerts.children);
  process.stdout.write(JSON.stringify({allReported, minimumThree, refreshNotice,
    polled, finalAlertText}));
})().catch(error => { console.error(error); process.exit(1); });
"""


def test_browser_ui_recovery_gaps():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to run the browser script against a stub DOM")
    script = Path(__file__).parents[1] / "app" / "static" / "app.js"
    result = subprocess.run(
        [node, "-e", UI_HARNESS, str(script)],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    seen = json.loads(result.stdout)
    # "All reported" must not send a magnitude filter: the API then drops null magnitudes.
    assert seen["allReported"] == "GET /api/state?"
    assert seen["minimumThree"] == "GET /api/state?min_mag=3"
    # Backend failures carry {"error": ...}; the visible notice must show that reason.
    assert seen["refreshNotice"] == "refresh cooling down"
    # A delayed older poll must not undo newer acknowledgement UI state.
    assert "Acknowledged locally" in seen["finalAlertText"]
    assert "Acknowledge" not in seen["finalAlertText"]
    # The periodic poll must also reload alerts created by the background refresher.
    assert seen["polled"] == [
        "GET /api/alerts",
        "GET /api/snapshots",
        "GET /api/state?min_mag=3",
        "GET /api/watches",
    ]


def test_all_reported_needs_the_magnitude_filter_omitted(empty_client):
    payload = usgs_payload(
        [
            {"id": "unrated", "mag": None, "time": NOW - 1_000, "lat": 1.0, "lon": 2.0},
            {"id": "rated", "mag": 3.0, "time": NOW - 1_000, "lat": 1.0, "lon": 2.0},
        ]
    )
    empty_client.store.apply_payload(USGS_ID, USGS_URL, payload, "n" * 64, NOW, seeded=False)
    ids = lambda query: {e["id"] for e in empty_client.get("/api/state" + query).json()["events"]}  # noqa: E731
    assert ids("") == {"unrated", "rated"}
    assert ids("?min_mag=-2") == {"rated"}
