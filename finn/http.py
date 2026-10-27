"""Polite HTTP with a content-addressed raw cache.

Rules (see docs/data-failure-behaviour.md):
- 403/401/429 are never retried in the same run: we respect the refusal and report it.
- Timeouts / 5xx get one retry.
- Every successful body is written to the raw cache so later runs (and tests) can replay offline.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
REFERERS = {"www.nseindia.com": "https://www.nseindia.com/"}
# Minimum seconds between requests per host. screener 429'd at 1.2s spacing on 2026-10-27; 8s worked.
MIN_INTERVAL = {"www.screener.in": 8.0, "www.nseindia.com": 1.5, "nsearchives.nseindia.com": 1.0}
NO_RETRY = {401, 403, 404, 429}

_last_hit: dict[str, float] = {}


@dataclass
class Fetched:
    ok: bool
    url: str
    status: Optional[int]
    body: Optional[bytes]
    fetched_at: datetime
    from_cache: bool
    sha256: Optional[str]
    reason: Optional[str] = None


def cache_dir() -> Path:
    return Path(os.environ.get("FINN_CACHE_DIR", "data/raw"))


def _key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:32]


def _cache_paths(url: str) -> tuple[Path, Path]:
    k = _key(url)
    return cache_dir() / f"{k}.bin", cache_dir() / f"{k}.json"


def read_cache(url: str) -> Optional[Fetched]:
    body_p, meta_p = _cache_paths(url)
    if not (body_p.exists() and meta_p.exists()):
        return None
    meta = json.loads(meta_p.read_text())
    body = body_p.read_bytes()
    return Fetched(True, url, meta.get("status"), body, datetime.fromisoformat(meta["fetched_at"]),
                   True, hashlib.sha256(body).hexdigest())


def _write_cache(f: Fetched) -> None:
    body_p, meta_p = _cache_paths(f.url)
    body_p.parent.mkdir(parents=True, exist_ok=True)
    body_p.write_bytes(f.body or b"")
    meta_p.write_text(json.dumps({"url": f.url, "status": f.status, "fetched_at": f.fetched_at.isoformat()}))


def _throttle(host: str) -> None:
    gap = MIN_INTERVAL.get(host, 0.5)
    wait = _last_hit.get(host, 0) + gap - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.monotonic()


def fetch(url: str, *, offline: bool = False, max_age_s: Optional[float] = None, timeout: float = 30) -> Fetched:
    """Return cached body if fresh enough (or if offline); otherwise fetch live.

    offline=True never touches the network; a cache miss is reported as not ok.
    max_age_s=None means any cached copy is acceptable.
    """
    cached = read_cache(url)
    now = datetime.now(timezone.utc)
    if cached and (offline or max_age_s is None or (now - cached.fetched_at).total_seconds() <= max_age_s):
        return cached
    if offline:
        return Fetched(False, url, None, None, now, False, None, "offline mode and no cached copy")

    host = urlparse(url).netloc
    headers = {"User-Agent": UA, "Accept": "*/*"}
    if host in REFERERS:
        headers["Referer"] = REFERERS[host]
    last_reason = None
    for attempt in range(2):
        _throttle(host)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
                body = r.read()
                f = Fetched(True, url, r.status, body, datetime.now(timezone.utc), False, hashlib.sha256(body).hexdigest())
                _write_cache(f)
                return f
        except urllib.error.HTTPError as e:
            last_reason = f"HTTP {e.code}"
            if e.code in NO_RETRY:
                return _fail(url, e.code, last_reason, cached)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_reason = f"network error: {getattr(e, 'reason', e)}"
    return _fail(url, None, last_reason or "unknown error", cached)


def _fail(url: str, status: Optional[int], reason: str, cached: Optional[Fetched]) -> Fetched:
    # A stale cached copy is still served, but marked so the UI can say it is stale.
    if cached:
        cached.reason = f"live fetch failed ({reason}); serving cached copy from {cached.fetched_at.isoformat()}"
        return cached
    return Fetched(False, url, status, None, datetime.now(timezone.utc), False, None, reason)


@dataclass
class Probe:
    url: str
    ok: bool
    status: Optional[int]
    latency_ms: int
    bytes: int
    content_type: Optional[str]
    body: bytes
    reason: Optional[str]


def probe(url: str, *, timeout: float = 15) -> Probe:
    """One live request for connectivity diagnostics: no cache read or write, no retry, no stale fallback,
    so the result says exactly what this host saw. Same headers and per-host throttle as fetch()."""
    host = urlparse(url).netloc
    headers = {"User-Agent": UA, "Accept": "*/*"}
    if host in REFERERS:
        headers["Referer"] = REFERERS[host]
    _throttle(host)
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
            body = r.read()
            return Probe(url, True, r.status, int((time.monotonic() - t0) * 1000), len(body),
                         r.headers.get("Content-Type"), body, None)
    except urllib.error.HTTPError as e:
        return Probe(url, False, e.code, int((time.monotonic() - t0) * 1000), 0, None, b"", f"HTTP {e.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return Probe(url, False, None, int((time.monotonic() - t0) * 1000), 0, None, b"",
                     f"network error: {getattr(e, 'reason', e)}")
