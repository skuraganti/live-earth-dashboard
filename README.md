# Fieldglass — live earth dashboard

**[Open the GitHub Pages browser demo](https://skuraganti.github.io/live-earth-dashboard/)** · [Architecture](ARCHITECTURE.md) · [Data sources](DATA_SOURCES.md) · [Verification](VERIFICATION.md)

Genuine USGS/NWS ingestion, map and event-time playback, radius watches, deduplication and source-freshness monitoring.

## Two ways to explore

The **Pages site** is a self-contained browser demonstration over a frozen USGS/NWS capture, with relative assets and no backend or credentials. Its radius tool only filters that capture and never alerts ([docs/DEMO.md](docs/DEMO.md)). The repository also contains the **full Python/Docker application**, which can refresh the live feeds, track source freshness and raise deduplicated watch alerts ([DEMO.md](DEMO.md)). Pages cannot run the backend or poller.

## Run the full application locally

Requirements: a POSIX host (macOS or Linux), Python3.13+, [uv](https://docs.astral.sh/uv/), Docker and Docker Compose. No GPU is required. Run one portfolio stack at a time on a small machine.

```sh
uv sync --frozen
uv run python scripts/bootstrap.py
sh stack.sh up
```

Open **http://127.0.0.1:8281**. Stop with `sh stack.sh stop`; this retains this repository's independent named volume. Helpers honor your current Docker context or explicitly supplied `DOCKER_HOST`; they do not select a personal machine profile. Images/networks/volumes are uniquely named `portfolio-release-*`, keeping the original development stacks separate. Host ports bind to127.0.0.1.

By default the stack polls the four public feeds every 300 seconds (`EARTH_AUTO_POLL=1`, `EARTH_POLL_SECONDS`). To use the saved capture/cache without automatic feed polling with no network requests, start it with `EARTH_AUTO_POLL=0 sh stack.sh up`. [DEMO.md](DEMO.md) walks through both modes.

## Verify

```sh
uv run pytest
uv run ruff check .
python3 -m http.server 8008 --bind 127.0.0.1 --directory docs
```

The final command previews Pages at http://127.0.0.1:8008. Bootstrap copies the committed capture from `examples/source-snapshot/` into `data/raw/` and makes no network request. The native tests never contact USGS or NWS: outages, stale feeds and recovery are simulated with an offline fetcher and a fixed clock. Unit fixtures, actual-source checks, captured evaluations and browser simulations are distinguished in [VERIFICATION.md](VERIFICATION.md). No model call is required for the native test suite.

## Scope and limitations

The Pages demo uses a frozen public-publisher snapshot, not live polling. The local app can refresh actual feeds. Playback filters captured revisions by event time and cannot reconstruct historical as-known information; nullable weather readings remain missing.

[DEMO.md](DEMO.md) describes a local walkthrough; [docs/DEMO.md](docs/DEMO.md) describes the Pages interactions. [DECISIONS.md](DECISIONS.md), [PLAN.md](PLAN.md) and [SOURCE_MANIFEST.json](SOURCE_MANIFEST.json) record engineering choices and source versions. Upstream components and original data publishers are credited in [UPSTREAM.md](UPSTREAM.md); third-party licenses remain in force. Original application code and authored documentation remain unlicensed; see [LICENSING.md](LICENSING.md) for reserved rights and third-party boundaries.

## Explore projects

[Ledger](https://skuraganti.github.io/personal-spending-tracker/) · [Fieldglass](https://skuraganti.github.io/live-earth-dashboard/) · [Relay](https://skuraganti.github.io/data-pipeline-monitor/) · [Folio](https://skuraganti.github.io/private-ai-knowledge-engine/) · [Contour](https://skuraganti.github.io/ai-codebase-explorer/) · [TraceLab](https://skuraganti.github.io/ai-agent-evaluation-lab/) · [Faultline](https://skuraganti.github.io/ai-incident-investigator/)

Defaults work without copying `.env.example`. Dependency installation needs internet access. Fieldglass has no AI or model integration.

## Implementation history

- USGS earthquake and NWS weather ingestion with deduplication and source-freshness checks.
- Map views, event-time playback and radius-based location watches.
- A captured-data browser demonstration, with genuine feed refresh available in the local application.
