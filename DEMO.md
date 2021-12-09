# Local demonstration: captured snapshot, then live feeds

The local app has two data modes. Keep them separate when you demonstrate or verify it. Bootstrap never overwrites existing cached sources. On an already-used volume, the captured phase displays that saved cache rather than resetting it to the bundled snapshot.

| | Captured snapshot | Live feeds |
|---|---|---|
| Data | Committed USGS/NWS capture in `examples/source-snapshot/`, copied to `data/raw/` by bootstrap and loaded only for sources absent from the database | Real GETs to the four fixed publisher URLs (USGS 2.5+ week feed; NWS KSFO, KSEA, KNYC) |
| Network | None | Four bounded requests per refresh |
| Start with | `EARTH_AUTO_POLL=0 sh stack.sh up` | `sh stack.sh up` (default `EARTH_AUTO_POLL=1`: one refresh every `EARTH_POLL_SECONDS`, 300 by default) |

A source is **fresh** only when its provider time (USGS `generated`, or the newest NWS observation) is at most two hours old. Otherwise it is **stale**, **error** (the latest attempt failed), **missing** or **clock_skew**. Watches alert only on fresh sources and on evidence from the last 24 hours. So a captured snapshot that is more than two hours old shows stale sources and creates no watch matches. That is the intended behaviour, not a fault.

## A. Captured snapshot, no network

1. Run `uv sync --frozen`, then `uv run python scripts/bootstrap.py`, then `EARTH_AUTO_POLL=0 sh stack.sh up`, and open http://127.0.0.1:8281.
2. **The instruments.** Each source card shows its state, `Provider:` and `Last retrieval:` times, `Age:` and, after a failure, `Latest attempt:` with the error class. The status line reads `N/4 sources fresh · current captured status`. Missing wind is shown as missing, never as zero.
3. **See the pattern.** Under **Minimum magnitude**, choose **All reported** (no magnitude filter, so events with no reported magnitude stay listed). Find the type-labeled landslide and open a source-linked popup, then compare with **M 6+**, where that M3.9 landslide is excluded. The nominal M2.5+ feed includes five lower reported magnitudes in the frozen snapshot.
4. **Play history** steps the event-time cutoff; the label changes from `CURRENT CAPTURE` to `EVENT-TIME REPLAY`. Station cards can empty when their captured coverage starts later. Use **Return to current** to go back. Replay uses the latest captured revision of each event, not what was known at the time. Replay requests never create alerts.
5. **Places to watch.** Set **Place name** to `KSFO demonstration`. Save a watch at the public KSFO reference (37.619, −122.375): **Radius · km** `5`, **Earthquake magnitude ≥** `8`, **Temperature ≥ · °C (optional)** `0`. Stale captured sources create no new matches; previously retained **Watch evidence** remains visible.

The same checks are available from the API: `curl -s http://127.0.0.1:8281/api/state` returns `sources[].state`, `observed_at`, `last_success` and `error`.

## B. Live feeds

1. Start or restart with live polling: `sh stack.sh stop`, then `sh stack.sh up`. Or keep polling off and press **Refresh sources** once. From a terminal, the equivalent is `curl -s -X POST http://127.0.0.1:8281/api/refresh`.
With an existing seed/cache, default polling waits for its first interval; startup alone does not prove a fresh retrieval.
2. A refresh makes four real GETs and returns one outcome per source. Repeating it within 60 seconds returns HTTP 429 (`refresh cooling down`), and an overlapping refresh returns HTTP 409 (`refresh in flight`). The page's notice shows that reason. While the page is visible and not in replay, it reloads sources, watches and **Watch evidence** every 30 seconds, so alerts raised by the background poller appear without a manual reload.
3. After a successful refresh, sources whose provider time is recent read **fresh**, and saved watches are reevaluated after each successfully applied source. Deduplication preserves one alert per watch, kind and evidence ID. The KSFO watch from step A5 matches only when the source is fresh and the current observation has a nonnull temperature ≥ 0 °C. A missing temperature produces no temperature alert, even when the source is fresh. An actual match shows its distance and source link. The deliberately low threshold only illustrates configuration; it is not a hazard assessment. Each watch, kind and evidence ID creates at most one alert, so repeated refreshes and newer revisions of the same event do not duplicate it. Acknowledge it under **Watch evidence**.
4. If a provider request fails, that card shows **error** with `Latest attempt:` and the error class. The last good observations stay visible, and that source produces no new alerts until a later refresh succeeds.
5. Persistence: run `sh stack.sh stop` and then `sh stack.sh up`. Watches, acknowledgements, source history and the catalog remain in this project's named volume.

## Deterministic fault tests versus real feed requests

`uv run pytest` never contacts USGS or NWS. An autouse fixture fails any real HTTP attempt. Tests supply payloads through an offline fetcher and use a fixed synthetic clock. The stale-feed and outage scenarios are simulated:
- [tests/test_maintenance.py](tests/test_maintenance.py): failure keeps the last good cache, stale or errored evidence creates no alerts, and a close and reopen keeps stale status, watches, acknowledgements and hashes. Recovery then restores freshness with deduplicated alerts. It also covers inclusive radius boundaries, the antimeridian and poles, invalid input, and the three browser-script fixes (magnitude filter, error reasons, alert polling).
- [tests/test_regressions.py](tests/test_regressions.py) and [tests/test_refresh.py](tests/test_refresh.py) cover related refresh and recovery cases.

Run them with these shipped commands:

```sh
uv run pytest tests/test_maintenance.py   # recovery, close/reopen, radius edges, browser-script checks
uv run pytest                             # full native suite
uv run ruff check .
python3 -m http.server 8008 --bind 127.0.0.1 --directory docs   # Pages preview
sh scripts/check-pages.sh                 # optional Pages smoke test; needs agent-browser 0.38.1
```

The browser-script checks in `tests/test_maintenance.py` need Node on `PATH` and skip without it. They run `app/static/app.js` against a stub DOM and a stub `fetch`, not a real browser. Their results, like the rest of the suite, say nothing about the live publishers' current availability. Only part B above makes real requests.
