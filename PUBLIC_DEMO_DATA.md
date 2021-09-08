# Public demonstration data

Curated input for the browser demonstration.

392 original captured USGS events (391 earthquakes and one landslide) plus 144 original NWS observations. Selected values match the original captured responses. The bundled five source response/manifest files allow exact bootstrap; this is historical replay, not a live Pages feed.

Fixture: `docs/demo-data.json` · SHA-256 `89504a8fab08cb5e7cbe5c0cb669261353629c4b80f8106e0f814ac2463ec32d` · 193,561 bytes.

Declared mode: Frozen original USGS/NWS snapshot; Pages does not poll live feeds

Top-level schema fields: `title`, `data_kind`, `generated`, `events`, `weather`, `sources`, `limit`, `repository`

Original publisher URLs, revisions, retrieval methods, rights and caveats are in [DATA_SOURCES.md](DATA_SOURCES.md). Browser behavior is described in [docs/DEMO.md](docs/DEMO.md). Data and application dependencies are credited separately in [UPSTREAM.md](UPSTREAM.md).
