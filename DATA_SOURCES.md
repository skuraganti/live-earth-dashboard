# Data sources and acquisition decision

Research/acquisition: 2026-10-16 UTC. Original publisher feeds were actually queried; installation is not evidence.

| Candidate | Provenance / terms / access | Fit and decision |
|---|---|---|
| USGS M2.5+ rolling seven-day catalog + NWS station observations | Original US government publishers; anonymous GET verified, no account/fees. [USGS feed schema](https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php), [USGS copyright](https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits), [NWS API policy](https://www.weather.gov/documentation/services-web-API) states open data free for any purpose | Selected: observed events/weather, stable identifiers and generation/report timestamps, revision/quality/null handling, modest local volume |
| USGS + Open-Meteo | Original weather aggregation/model publisher; [terms](https://open-meteo.com/en/terms) distinguish CC BY 4.0 data from free non-commercial API access with request limits | Credible alternative for broad model coverage, but modeled products/forecast values must not be called station observations; selected authentic NWS observations instead |
| USGS + NOAA Aviation Weather Center METAR | [Original NOAA AWC API](https://aviationweather.gov/data/api/) documents aviation observations | Useful observed-weather alternative, but a second METAR-specific representation/coverage is unnecessary once NWS original calls succeed. No AWC data acquired or blended |

## Acquired originals

`data/raw/manifest.json` records exact URLs, SHA256, retrieval times, byte sizes/counts and source generation/latest observation times. Initial USGS snapshot: 392 seismic events (391 earthquakes and one landslide), 277,267 bytes, SHA256 `0798950a6e246d8b07025a1d257f09d9a9c115f119e1f9acd0c2a9b3be613dbf`; generated epoch ms 1792138158000. NWS KSFO/KSEA/KNYC: 48 actual reports each, respectively 191,427 / 183,333 / 203,823 bytes. Individual hashes/timestamps are in the manifest. No sampling or generated data; fixtures/failures in tests are separate. No model split applies to this non-AI project.

USGS-produced data are U.S. public domain absent third-party exceptions; retain USGS/source attribution and review per-source credits, not every item on a government website. NWS explicitly offers API information as open data free for any purpose, with reasonable request limits and a required identifying User-Agent. A distinct local app agent was used without personal contact/credentials. Do not redistribute unrelated imagery/third-party content merely because the host is .gov.

## Semantics and limitations

Earthquakes: GeoJSON id, magnitude, place, origin/update milliseconds, depth/coordinates and review status. Nominal M2.5+ feed, rolling seven-day coverage, uneven detection/completeness and provisional revisions; not all earthquakes or risk predictions. Dedup IDs and monotonic revisions; absence from a rolling feed is not evidence of retraction. NWS: geometry and observation timestamp plus temperature/wind/description; nulls/unsupported units remain explicit missing values. Only three U.S. stations are demonstrated, with about 48 reports each; weather/earthquake coverage windows differ. No causal relation is inferred.

Ingestion time, provider generation time, report/event time and replay cutoff are distinct. Freshness uses source time; an unchanged/old cached report cannot become live because the app reopened. Replay is event-time filtering of the latest captured catalog with captured station reports before cutoff; it is not a claim about what was known in real time then. Joins are spatial distance and time only, with distance shown for station matches. Watch thresholds/alerts are local user configuration, not official emergency warnings.

## Basemap

Natural Earth 110m land v5.1.2: [original maintained repository](https://github.com/nvkelso/natural-earth-vector), [public-domain terms](https://www.naturalearthdata.com/about/terms-of-use/). Frozen local 138,160-byte GeoJSON with 127 land features, no political-boundary or live-map claim. Exact source/hash in VENDOR_MANIFEST.json. Low-resolution map is for orientation. No external tiles, accounts, tracking or uploads.

## Independent snapshot inspection

The initial nominal M2.5+ feed contains five reported magnitudes below 2.5 (2.45 ×2, 2.46 ×2, 2.47 ×1). Preserve these measurements; no rounding explanation is assumed. Event type must be retained and displayed so the one landslide is not described as an earthquake. The UI magnitude filter applies the actual reported value, so a 2.5 cutoff excludes those five records.

| Station | Captured UTC coverage | Missing wind |
|---|---|---:|
| KSFO | 2026-10-16 04:10–07:50 (3h40) | 45/48 |
| KSEA | 2026-10-16 04:00–07:50 (3h50) | 0/48 |
| KNYC | 2026-10-14 08:51–2026-10-16 06:51 (46h) | 11/48 |

All captured temperature units are degC and wind units km/h. A missing latest wind remains null: the earlier nonnull readings (06:56 KSFO, 05:59 KNYC) must not be silently substituted. Forty-eight reports do not mean forty-eight hours. NWS documents possible observation delays up to twenty minutes; station cadence and completeness vary. Source hashes, counts, timestamp uniqueness, local Leaflet assets and land geometry were independently checked by the read-only source reviewer.
