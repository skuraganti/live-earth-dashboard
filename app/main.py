"""Fieldglass API. app.main:app."""

from __future__ import annotations

import asyncio
import json
import math
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.fetch import FetchError, fetch_url
from app.parse import PayloadError
from app.sources import COOLDOWN_MS, SOURCE_URLS
from app.store import Store, haversine_km

LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
MAX_REQUEST_BYTES = 64 * 1024
STATIC_DIR = Path(__file__).resolve().parent / "static"
_DEFAULT_SEED = object()

CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "font-src 'none'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'"
)


def _env_int(name: str, default: int, low: int, high: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer") from exc
    if not low <= value <= high:
        raise SystemExit(f"{name} out of range {low}..{high}")
    return value


def _finite(value: object, label: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or isinstance(value, str):
        raise ValueError(f"{label} must be a finite number")
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be finite") from exc
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"{label} out of bounds")
    return number


def _optional(value: object, label: str, low: float, high: float) -> float | None:
    if value is None:
        return None
    return _finite(value, label, low, high)


class RefreshGate:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.busy = False
        self.last_started: int | None = None

    def begin(self, now: int) -> str | None:
        with self._lock:
            if self.busy:
                return "in_flight"
            if self.last_started is not None and now - self.last_started < COOLDOWN_MS:
                return "cooldown"
            self.busy = True
            self.last_started = now
            return None

    def end(self) -> None:
        with self._lock:
            self.busy = False


class BodyLimit:
    """Bound chunked request bodies before any JSON parser sees them."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        header = dict(scope.get("headers", [])).get(b"content-length")
        declared = None
        if header is not None:
            try:
                declared = int(header)
                if declared < 0:
                    raise ValueError()
            except ValueError:
                return await JSONResponse({"error": "invalid content length"}, status_code=400)(
                    scope, receive, send
                )
            if declared > MAX_REQUEST_BYTES:
                return await JSONResponse({"error": "body too large"}, status_code=413)(
                    scope, receive, send
                )
        chunks, total = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > MAX_REQUEST_BYTES:
                return await JSONResponse({"error": "body too large"}, status_code=413)(
                    scope, receive, send
                )
            chunks.append(chunk)
            if not message.get("more_body"):
                break
        if declared is not None and declared != total:
            return await JSONResponse({"error": "content length mismatch"}, status_code=400)(
                scope, receive, send
            )
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)


def create_app(
    *,
    db_path: str | None = None,
    seed_dir=_DEFAULT_SEED,
    clock=None,
    fetcher=None,
    auto_poll: bool | None = None,
    poll_seconds: int | None = None,
) -> FastAPI:
    resolved_db = db_path or os.environ.get("EARTH_DB", "data/fieldglass.sqlite")
    resolved_seed = (
        os.environ.get("EARTH_SEED_DIR", "data/raw") if seed_dir is _DEFAULT_SEED else seed_dir
    )
    seed_path = Path(resolved_seed) if resolved_seed else None
    interval = (
        poll_seconds if poll_seconds is not None else _env_int("EARTH_POLL_SECONDS", 300, 60, 86400)
    )
    if auto_poll is None:
        flag = os.environ.get("EARTH_AUTO_POLL", "1")
        if flag not in {"0", "1", "false", "False", "true", "True"}:
            raise SystemExit("EARTH_AUTO_POLL must be 0 or 1 (or true/false)")
        auto_poll = flag in {"1", "true", "True"}
    if isinstance(interval, bool) or not isinstance(interval, int) or not 60 <= interval <= 86400:
        raise ValueError("poll_seconds out of range 60..86400")
    now_ms = clock or (lambda: int(__import__("time").time() * 1000))
    store = Store(resolved_db, seed_path, now_ms)
    seeded = store.seed()
    gate = RefreshGate()
    stop = threading.Event()

    def refresh_one(source_id: str, url: str) -> dict:
        started = now_ms()
        try:
            if fetcher is not None:
                fetched = fetcher(url)
                body_bytes = fetched if isinstance(fetched, bytes) else json.dumps(fetched).encode()
                import hashlib

                digest = hashlib.sha256(body_bytes).hexdigest()
                body = fetched if isinstance(fetched, (dict, list)) else json.loads(body_bytes)
            else:
                result = fetch_url(url)
                digest = result.sha256
                body_bytes = result.body
                body = json.loads(body_bytes.decode("utf-8"))
            outcome = store.apply_payload(
                source_id, url, body, digest, started, seeded=False, raw_bytes=body_bytes
            )
            outcome.update({"id": source_id, "url": url})
            return outcome
        except (FetchError, PayloadError, json.JSONDecodeError, UnicodeError, ValueError) as exc:
            store.record_failure(source_id, url, exc.__class__.__name__, started)
            return {"id": source_id, "url": url, "ok": False, "error": exc.__class__.__name__}

    def refresh_all() -> dict:
        outcomes = []
        for source_id, url in SOURCE_URLS.items():
            if stop.is_set():
                break
            outcomes.append(refresh_one(source_id, url))
        return {"outcomes": outcomes, "sources": store.source_rows(now_ms())}

    def loop():
        while not stop.wait(interval):
            reason = gate.begin(now_ms())
            if reason:
                continue
            try:
                refresh_all()
                app.state.poll_error = None
            except Exception as exc:
                # Keep the next scheduled recovery attempt possible; report liveness honestly.
                app.state.poll_error = exc.__class__.__name__
            finally:
                gate.end()

    @asynccontextmanager
    async def lifespan(application):
        thread = None
        if auto_poll:
            if not seeded and gate.begin(now_ms()) is None:
                try:
                    await asyncio.to_thread(refresh_all)
                finally:
                    gate.end()
            thread = threading.Thread(target=loop, name="fieldglass-poll", daemon=True)
            application.state.poll_thread = thread
            thread.start()
        try:
            yield
        finally:
            stop.set()
            if thread is not None:
                await asyncio.to_thread(thread.join, 45)
            # A still-running fetch must never write through a closed connection.
            if thread is None or not thread.is_alive():
                store.close()

    app = FastAPI(
        title="Fieldglass", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )
    app.add_middleware(BodyLimit)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])
    app.state.poll_error = None
    app.state.store = store
    app.state.refresh_all = refresh_all
    app.state.now_ms = now_ms
    app.state.poll_seconds = interval
    app.state.haversine_km = haversine_km

    @app.middleware("http")
    async def guard(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    def reject_mutation(request: Request) -> JSONResponse | None:
        host = request.url.hostname
        if host not in LOOPBACK:
            return JSONResponse({"error": "host not allowed"}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"error": "origin not allowed"}, status_code=403)
        origin = request.headers.get("origin")
        if origin:
            expected = f"{request.url.scheme}://{request.headers.get('host')}"
            if origin != expected:
                return JSONResponse({"error": "origin not allowed"}, status_code=403)
        length = request.headers.get("content-length")
        if length is not None:
            try:
                if int(length) > MAX_REQUEST_BYTES:
                    return JSONResponse({"error": "body too large"}, status_code=413)
            except ValueError:
                return JSONResponse({"error": "invalid content length"}, status_code=400)
        return None

    @app.get("/health")
    def health():
        error = app.state.poll_error
        if auto_poll and hasattr(app.state, "poll_thread") and not app.state.poll_thread.is_alive():
            error = error or "poller_stopped"
        return JSONResponse(
            {"status": "degraded" if error else "ok", "poll_error": error},
            status_code=503 if error else 200,
        )

    @app.get("/api/state")
    def state(until: int | None = None, min_mag: float | None = None):
        try:
            if until is not None:
                until = int(_finite(until, "until", 0, 9_999_999_999_999))
            if min_mag is not None:
                min_mag = _finite(min_mag, "min_mag", -2, 10)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return store.state(until, min_mag, interval)

    @app.post("/api/refresh")
    def refresh(request: Request):
        blocked = reject_mutation(request)
        if blocked:
            return blocked
        reason = gate.begin(now_ms())
        if reason == "in_flight":
            return JSONResponse({"error": "refresh in flight"}, status_code=409)
        if reason == "cooldown":
            return JSONResponse({"error": "refresh cooling down"}, status_code=429)
        try:
            return refresh_all()
        finally:
            gate.end()

    @app.get("/api/watches")
    def watches():
        return store.watches()

    @app.post("/api/watches")
    async def create_watch(request: Request):
        blocked = reject_mutation(request)
        if blocked:
            return blocked
        raw = await request.body()
        if len(raw) > MAX_REQUEST_BYTES:
            return JSONResponse({"error": "body too large"}, status_code=413)
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("body must be an object")
            name = payload.get("name")
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
                raise ValueError("name must be 1..80 characters")
            fields = {
                "name": name.strip(),
                "lat": _finite(payload.get("lat"), "lat", -90, 90),
                "lon": _finite(payload.get("lon"), "lon", -180, 180),
                "radius_km": _finite(payload.get("radius_km"), "radius_km", 1, 20000),
                "min_mag": _optional(payload.get("min_mag"), "min_mag", -2, 10),
                "max_temperature_c": _optional(
                    payload.get("max_temperature_c"), "max_temperature_c", -100, 80
                ),
                "max_wind_kmh": _optional(payload.get("max_wind_kmh"), "max_wind_kmh", 0, 500),
            }
        except (ValueError, json.JSONDecodeError, UnicodeError):
            return JSONResponse({"error": "invalid watch"}, status_code=400)
        return store.create_watch(fields, now_ms())

    @app.delete("/api/watches/{watch_id}")
    def delete_watch(watch_id: int, request: Request):
        blocked = reject_mutation(request)
        if blocked:
            return blocked
        if not store.delete_watch(watch_id):
            return JSONResponse({"error": "not found"}, status_code=404)
        return {"deleted": watch_id}

    @app.get("/api/alerts")
    def alerts():
        return store.alerts()

    @app.post("/api/alerts/{alert_id}/ack")
    def ack(alert_id: int, request: Request):
        blocked = reject_mutation(request)
        if blocked:
            return blocked
        if not store.acknowledge(alert_id):
            return JSONResponse({"error": "not found"}, status_code=404)
        return {"acknowledged": alert_id}

    @app.get("/api/snapshots")
    def snapshots():
        return store.snapshots()

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
        index = STATIC_DIR / "index.html"
        if index.is_file():

            @app.get("/")
            def root():
                return FileResponse(index)

    return app


# Uvicorn's "app.main:app" target builds the real app on first connection, so
# importing the module (tests, tooling) never seeds a database or starts a poller.
async def _asgi(scope, receive, send):
    if not hasattr(_asgi, "app"):
        _asgi.app = create_app()
    return await _asgi.app(scope, receive, send)


app = _asgi
