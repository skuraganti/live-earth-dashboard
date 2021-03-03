# Release status

**Local release gates: verified on 2026-10-16.** Theme 2021 is a technology theme, not a completion date. Source, native tests, Docker workflow/persistence, Pages browser/mobile/error states and publication privacy review passed. Actual publication is recorded by GitHub commit/deployment metadata after this prepared initial commit. See [VERIFICATION.md](VERIFICATION.md) for exact checks and limits.

Local: `sh stack.sh up` → http://127.0.0.1:8281. [Pages demo](https://skuraganti.github.io/2021-live-earth-dashboard/) · [Source](https://github.com/skuraganti/2021-live-earth-dashboard). Pages uses static browser interactions; full Python services run locally. Runtime databases, caches, model-control files and credentials stay excluded. The Pages demo uses a frozen public-publisher snapshot, not live polling. The local app can refresh actual feeds. Playback filters captured revisions by event time and cannot reconstruct historical as-known information; nullable weather readings remain missing.

Next maintenance action: use the documented setup, verify original-source checksums before updating fixtures, rerun affected tests and retain failed/uncertain evaluation outcomes. No hosted inference or unattended service is supplied by Pages.
