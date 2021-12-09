# Fieldglass browser demonstration

Serve the `docs` directory at its Pages root or via a local static HTTP server. This is a static browser experience, not the running Python/Docker application.

The fixture is a frozen original USGS/NWS capture. The earthquake map uses an equirectangular longitude/latitude projection; magnitude and event-time controls filter captured events, while landslide records remain explicitly disclosed and outside the earthquake threshold. Event times use latest captured revisions, not historical as-known state. Weather cards display the latest captured observation per each of three stations and preserve nulls. The optional radius tool computes geodesic distances only within the currently filtered snapshot; it is not an alert, hazard assessment or notification. No live polling.

## Walkthrough (frozen capture only)

1. Wait for the status line to read `Frozen snapshot · source age …`. The age is how old the capture is; nothing on this page refreshes it.
2. Lower **Minimum earthquake magnitude** and drag **Event-time replay**. The map (**Quake locations · equirectangular**) and the event table only filter captured events.
3. Select an event for **Selected event**, then use **Open USGS event page** to go to the publisher record.
4. Under **Radius watch · snapshot only**, enter **Latitude**, **Longitude** and **Radius · km** (1 to 20,000), then press **Calculate matches**. Matching is inclusive (distance ≤ radius) over the currently filtered earthquakes only. It creates no alert, saves nothing and requests nothing.

## What only the local application does

Live refresh of the four publisher feeds; **fresh** / **stale** / **error** source states; saved watches with deduplicated alerts on fresh, recent evidence; and recovery after a failed refresh are all in the Python/Docker app ([DEMO.md](../DEMO.md)). Its stale-feed and outage behaviour is checked by deterministic tests with simulated payloads. None of that runs here.

The Pages provenance display shows source links, age and SHA-256 values. The local app separately records provider and retrieval times. [Full Python/Docker source and local startup](https://github.com/skuraganti/live-earth-dashboard).
