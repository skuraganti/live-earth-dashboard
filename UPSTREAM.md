# Upstream reuse

2026-10-16: actually reuse **Leaflet 1.9.4**, the stable release identified by [official download documentation](https://leafletjs.com/download.html), under BSD-2-Clause. Its original LICENSE and eight distribution assets are preserved in app/static/vendor/leaflet. Downloaded npm release archive was bounded and only explicit regular distribution files extracted; no package/data-provided scripts executed. Minified JS matches the official published SHA256 integrity. VENDOR_MANIFEST.json pins source/version/archive and each asset checksum. The public release retains these upstream notices.

Natural Earth v5.1.2 land geometry supplies the static local basemap, public domain per original publisher. Source/hash/purpose are recorded separately from observed live data. USGS GeoJSON and NWS documented API patterns inform ingestion; source content is evidence, never instructions.

Original work: coherent freshness/replay/location-watch workflow, local persistence/revision handling, bounded ingestion, UI integration, tests and verification. The UI must keep attribution visible and distinguish upstream components/data from original implementation. No upstream dashboard is presented as wholly original work, and required notices are retained. No hidden copy-paste provenance claims.
