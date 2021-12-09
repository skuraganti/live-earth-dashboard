# Release verification — 2026-10-16

Actual development and release preparation 2026-10-16. This report records checks on the sanitized public source copy before its initial commit. Deployment is checked separately after pushing, without backdated commits. Passing these bounded checks does not guarantee every future feed, model response or workload.

| Check | Observed result |
|---|---|
| Clean source environment | `uv sync --frozen`, project-specific `scripts/bootstrap.py`: passed |
| Native suite | **74 passed** with Python 3.14.8; FastAPI/Starlette emitted a TestClient deprecation warning |
| Lint | `uv run ruff check .`: passed; pinned upstream corpus files excluded from project style rules |
| Docker | Digest-pinned Python 3.13 image built; startup, HTTP health and application page passed |
| Workflow | Frozen genuine USGS/NWS seed ingested; polling status inspected |
| Persistence | Restarted app container; workflow state retained |
| Browser | Isolated Chromium via agent-browser 0.38.1; 8 domain assertions passed; native input/click controls passed |
| Error state | Fixture temporarily unavailable: visible recoverable error; restored fixture loads after reload |
| Responsive layout | 1440×1000 and 390×844 inspected; 390px document width with no page overflow |
| Accessibility | axe-core 4.12.1, WCAG 2 A/AA and 2.1 AA tags: **0 detected violations** |
| Privacy | Candidate-file Gitleaks scan passed; no private home paths, unrelated service IDs, credentials or mutable data included |
| Release inference | **0 model calls**; recorded original model studies remain distinct from release checks |

Browser scenarios: original snapshot loads; empty magnitude state; landslide excluded; event detail interaction; event-time playback; invalid watch rejected; radius snapshot result; three weather stations.

Some axe color checks on clipped scroll contents require manual review. Visible desktop/mobile views and the authored foreground/background palette were inspected; the minimum checked ink/muted/link ratio against the declared page/panel backgrounds was 5.67:1. This is a bounded audit, not a universal accessibility certification. Scroll regions are keyboard focusable and tables accompany charts/graphs.

## Corrections and retesting

The interactive SVG uses a group role rather than nesting buttons in an image. Invalid/empty coordinates and out-of-bound radii are rejected; filter changes invalidate the old radius result. Snapshot disclosure and non-earthquake exclusion remain visible.

## Recorded findings and limitations

The Pages demo uses a frozen public-publisher snapshot, not live polling. The local app can refresh actual feeds. Playback filters captured revisions by event time and cannot reconstruct historical as-known information; nullable weather readings remain missing.

Native tests use explicit fixtures, original-source boundary checks and simulated model responses; they do not perform live inference. See [PUBLIC_DEMO_DATA.md](PUBLIC_DEMO_DATA.md) for the curated Pages fixture and checksum, [DATA_SOURCES.md](DATA_SOURCES.md) for publisher/version/rights and [UPSTREAM.md](UPSTREAM.md) for attribution. Original model studies have small samples and cannot establish general performance or costs.

## Reproduce

```sh
uv sync --frozen
uv run python scripts/bootstrap.py
uv run pytest
uv run ruff check .
sh stack.sh up
```

Local URL: http://127.0.0.1:8281. The container limit is 256 MiB for the app, plus Docker and host process overhead. Tested one portfolio stack at a time on an ARM Mac with 8 GiB host RAM and a 2 GiB Docker VM. No GPU. Defaults use independent named volumes and localhost bindings. Stack stop retains state; no unrelated services are managed.

For Pages: `python3 -m http.server 8008 --bind 127.0.0.1 --directory docs`. With optional agent-browser 0.38.1 installed, run `sh scripts/check-pages.sh`; assertions are in `tests/pages-smoke.js`. No browser automation package is shipped to Pages.

## Freshness, radius and browser recovery maintenance

- **106 native tests passed** with Python 3.12.14 and Node 24.20.0. Ruff passed. The existing TestClient deprecation warning remains.
- Offline regressions check stale provider time versus successful retrieval, failure retention, true database close/reopen with watches and acknowledgements, freshness recovery, alert deduplication, inclusive radius thresholds, antimeridian/polar distances and invalid/nonfinite inputs.
- Browser-script tests use a stub DOM and stub responses; they are separate from Chrome checks. They reproduce the null-magnitude filter, refresh-error and missing alert-poll issues. A deferred-response regression first failed, then passed after response ordering protected newer acknowledgment state.
- The patched Docker image built and became healthy. A single four-source real refresh succeeded for USGS and all three NWS stations, reporting four fresh source times. Immediate repeat refresh returned 429; replay created no alerts. No automatic polling was enabled during this check.
- Chrome observed an API-added watch and its earthquake alerts appear through the normal visible-page 30-second read timer, without reload or another publisher refresh. The final loaded view showed four fresh sources, the saved watch, an acknowledged alert and 427 All reported events.
- Final restart compared the exact saved watches, 99 alerts and snapshot metadata, which remained unchanged. There were 427 stored seismic events and three latest station observations. The served script matched the reviewed host source.
- The local and Pages walkthroughs distinguish saved cache, genuine feed refresh, event-time replay and simulated test failures. Freshness never implies a nonnull reading; the observed current KSFO temperature was missing.

The forecast and hazard-warning use cases remain out of scope. Radius calculations use a spherical Earth approximation. Source availability and event counts change over time; these observations do not guarantee later publisher availability or establish official warning coverage.
