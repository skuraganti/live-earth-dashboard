"""Fixed publisher GETs with an absolute deadline and bounded raw response bytes."""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from app.sources import ALLOWED_HOSTS, FETCH_TIMEOUT_SECONDS, MAX_BODY_BYTES, USER_AGENT


class FetchError(RuntimeError):
    """A guarded request failed before its body could be trusted."""


@dataclass(frozen=True)
class FetchResult:
    url: str
    body: bytes
    sha256: str

    def text(self) -> str:
        return self.body.decode("utf-8")


def _check_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
        raise FetchError("url host not allowed")
    if parts.username or parts.password or parts.port not in (None, 443):
        raise FetchError("url credentials or port not allowed")
    return parts.hostname


async def _fetch(url: str, client: httpx.AsyncClient | None = None) -> FetchResult:
    host = _check_url(url)
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=False, trust_env=False
        )
    started = time.monotonic()
    try:
        # Includes connect, headers, redirects and every raw-body read, even a drip.
        async with asyncio.timeout(FETCH_TIMEOUT_SECONDS):
            current = url
            for _ in range(3):
                _check_url(current)
                async with client.stream(
                    "GET",
                    current,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept": "application/geo+json, application/json",
                        "Accept-Encoding": "identity",
                    },
                ) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location:
                            raise FetchError("redirect missing location")
                        current = str(response.url.join(location))
                        if urlsplit(current).hostname != host:
                            raise FetchError("redirect left allowed host")
                        continue
                    if response.status_code != 200:
                        raise FetchError(f"http {response.status_code}")
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise FetchError("compressed responses are not accepted")
                    parts, total = [], 0
                    async for chunk in response.aiter_raw():
                        if time.monotonic() - started >= FETCH_TIMEOUT_SECONDS:
                            raise FetchError("response deadline exceeded")
                        total += len(chunk)
                        if total > MAX_BODY_BYTES:
                            raise FetchError("response exceeds 4MB")
                        parts.append(chunk)
                    body = b"".join(parts)
                    return FetchResult(url, body, hashlib.sha256(body).hexdigest())
            raise FetchError("too many redirects")
    except TimeoutError as exc:
        raise FetchError("response deadline exceeded") from exc
    except httpx.HTTPError as exc:
        raise FetchError(exc.__class__.__name__) from exc
    finally:
        if owns_client:
            await client.aclose()


def fetch_url(url: str, client: httpx.AsyncClient | None = None) -> FetchResult:
    """Synchronous caller interface; used only from worker threads or acquisition CLI."""
    return asyncio.run(_fetch(url, client))
