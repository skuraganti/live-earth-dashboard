# Fieldglass browser demonstration

Serve the `docs` directory at its Pages root or via a local static HTTP server. This is a static browser experience, not the running Python/Docker application.

The fixture is a frozen original USGS/NWS capture. The earthquake map uses an equirectangular longitude/latitude projection; magnitude and event-time controls filter captured events, while landslide records remain explicitly disclosed and outside the earthquake threshold. Event times use latest captured revisions, not historical as-known state. Weather cards display the latest captured observation per each of three stations and preserve nulls. The optional radius tool computes geodesic distances only within the currently filtered snapshot; it is not an alert, hazard assessment or notification. No live polling.

Source URLs, retrieval times and SHA-256 values are shown in the app. [Full Python/Docker source and local startup](https://github.com/skuraganti/2021-live-earth-dashboard).
