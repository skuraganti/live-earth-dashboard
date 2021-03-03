# A five-minute real-data demonstration

1. Start `sh stack.sh up`, open http://127.0.0.1:8281 and compare provider times with retrieval times. Missing wind is explicit, not zero. Refresh makes four real GETs and can show provider errors without losing cached observations.
2. Choose **All reported**, locate the type-labeled landslide and inspect a source-linked popup. Compare M6+ with the full catalog. The nominal M2.5+ feed includes five lower reported magnitudes in the frozen snapshot.
3. Move the replay slider to the middle of the week. Station cards become empty because their captured coverage starts later. Play, pause, then return to current. Explain latest-revision replay versus information known at event time.
4. At the public KSFO station reference (37.619, −122.375), save a 5km watch, M≥8 and temperature ≥0°C. Fresh observed weather above the chosen demonstration threshold creates a local match with distance and source evidence. This deliberately low threshold illustrates configuration, not a danger assessment. Stale/missing evidence produces no new match. Acknowledge it, replay again and confirm no replay-generated duplicates.
5. Restart this project only. Watch/acknowledgment, source provenance and catalog remain. `sh stack.sh stop` conserves resources and retains the named volume.

`verify_real.py` leaves the clearly named “Verification · KSFO” watch visible. `verify_browser.py` creates/removes a separate “Browser verification” watch and injects one explicitly synthetic browser read failure, restoring the real fetch function afterward. Actual publisher data are not modified by the fault.
