# Public demonstration data

Prepared 2026-10-16; theme year 2021 is not a completion date.

392 original captured USGS events (391 earthquakes and one landslide) plus 144 original NWS observations. Selected values match the original captured responses. The bundled five source response/manifest files allow exact bootstrap; this is historical replay, not a live Pages feed.

Fixture: `docs/demo-data.json` · SHA-256 `4d0d98d0ac7f1247edaee8e50c90d97a077d017f91e20a6667f6646029eda8d5` · 193,620 bytes.

Declared mode: Frozen original USGS/NWS snapshot; Pages does not poll live feeds

Top-level schema fields: `title`, `data_kind`, `generated`, `events`, `weather`, `sources`, `limit`, `theme_year`, `developed_at`, `repository`

Original publisher URLs, revisions, retrieval methods, rights and caveats are in [DATA_SOURCES.md](DATA_SOURCES.md). Browser behavior is described in [docs/DEMO.md](docs/DEMO.md). Data and application dependencies are credited separately in [UPSTREAM.md](UPSTREAM.md).
