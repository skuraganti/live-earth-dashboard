# Fieldglass development and publication plan

Actual development/publication preparation2026-10-16. The full application is independent, useful and locally runnable. Genuine USGS/NWS ingestion, map and event-time playback, radius watches, deduplication and source-freshness monitoring.

Completed original milestones: define user/workflow/non-goals; compare real-data candidates; pin sources/licenses; scoped implementation; integration and corrections; native/Docker/browser/persistence checks; record actual results and limitations. Public release adds a separate static browser demo, reviewed examples, reproducible bootstrap, portable configuration and publication checks before an initial commit.

Publication gates: clean-source/native tests after bootstrap, Docker health and real-data smoke workflow, Pages relative-path functionality/mobile/accessibility, credential/privacy/license review, truthful metadata, one initial commit, then sequential push/Pages deployment and public URL verification. A failure stops that repository's publication until corrected. No fabricated history or model-evaluation outcome is allowed.

The Pages demo uses a frozen public-publisher snapshot, not live polling. The local app can refresh actual feeds. Playback filters captured revisions by event time and cannot reconstruct historical as-known information; nullable weather readings remain missing.
