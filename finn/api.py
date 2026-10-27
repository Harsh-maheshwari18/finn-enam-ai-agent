"""Read-only HTTP API over the committed snapshot. Plain WSGI, no framework: `gunicorn finn.api:app`.

GET /health                                   snapshot identity and whether it verifies
GET /api/v1/companies                         every company in the snapshot with its validation level
GET /api/v1/companies/{SYMBOL}/results        results card; every number carries its source
GET /api/v1/companies/{SYMBOL}/transcripts    earnings-call transcript inventory (metadata only)
GET /api/v1/companies/{SYMBOL}/filings        stored NSE announcements and the last completed EOD session
GET /api/v1/companies/{SYMBOL}/promises       Management Promise Ledger (validated quotes, outcomes, verdicts)
GET /api/v1/signals?window=24h&move_pct=5&volume_x=2&lookback=20&watch=..&mute=..&symbols=..
                                              ranked Signal Inbox over the snapshot (finn/signals.py)
GET /api/v1/diagnostics/connectivity          live NSE / Yahoo reachability from THIS host; needs the
                                              X-Finn-Diagnostics-Token header (FINN_DIAG_TOKEN), never CORS-enabled
GET /                                         the mobile web app (web/), served from the same origin

Requests never call an LLM and never fetch live data, except the diagnostics endpoint, which is explicit about it.
Cross-origin reads are allowed only for origins listed in FINN_CORS_ORIGINS (comma-separated, exact match);
FINN_CORS_DEV=1 additionally allows http://localhost:<port> and http://127.0.0.1:<port> for local development.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qsl

from finn import http, service, signals, snapshot
from finn.adapters import nse_filings, nse_results, prices

VERSION = "0.4.0"
SYMBOL = re.compile(r"^[A-Z0-9&\-]{1,20}$")
DIAG_TTL_S = 600
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
STATIC = re.compile(r"^/([a-z0-9][a-z0-9_-]*\.(?:js|css|svg|webmanifest))$")
CONTENT_TYPES = {"js": "text/javascript; charset=utf-8", "css": "text/css; charset=utf-8", "svg": "image/svg+xml",
                 "webmanifest": "application/manifest+json", "html": "text/html; charset=utf-8"}
DEV_ORIGIN = re.compile(r"^http://(localhost|127\.0\.0\.1):\d{1,5}$")


def snapshot_path() -> Path:
    return Path(os.environ.get("FINN_SNAPSHOT", snapshot.DEFAULT_OUT))


def allowed_origin(origin: str | None) -> str | None:
    """Exact-match allowlist; never '*'. Returns the origin to echo, or None for no CORS headers."""
    if not origin:
        return None
    allow = {o.strip().rstrip("/") for o in os.environ.get("FINN_CORS_ORIGINS", "").split(",") if o.strip()}
    if origin in allow or (os.environ.get("FINN_CORS_DEV") == "1" and DEV_ORIGIN.match(origin)):
        return origin
    return None


def _cors(origin: str | None) -> list[tuple[str, str]]:
    return [("Access-Control-Allow-Origin", origin), ("Vary", "Origin")] if origin else [("Vary", "Origin")]


def _json(start_response, status: str, body: dict, extra: list[tuple[str, str]] = (), origin: str | None = None,
          cache: str = "public, max-age=300") -> list[bytes]:
    data = json.dumps(body, default=str, indent=1).encode()
    start_response(status, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(data))),
                            ("Cache-Control", cache), ("X-Content-Type-Options", "nosniff"),
                            *_cors(origin), *extra])
    return [data]


def _static(start_response, name: str, method: str) -> list[bytes]:
    path = WEB_DIR / name
    if not path.is_file() or path.resolve().parent != WEB_DIR.resolve():
        return _json(start_response, "404 Not Found", {"error": "no such file"})
    data = path.read_bytes()
    headers = [("Content-Type", CONTENT_TYPES[name.rsplit(".", 1)[1]]), ("Content-Length", str(len(data))),
               ("Cache-Control", "no-cache"), ("X-Content-Type-Options", "nosniff")]
    if name.endswith(".html"):
        headers += [("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; "
                                                "script-src 'self'; connect-src 'self'; base-uri 'none'; "
                                                "frame-ancestors 'none'; form-action 'none'"),
                    ("Referrer-Policy", "no-referrer")]
    start_response("200 OK", headers)
    return [b""] if method == "HEAD" else [data]


def _meta(con) -> dict:
    m = dict(con.execute("SELECT key, value FROM snapshot_meta").fetchall())
    for k in ("symbols", "transcript_symbols"):
        m[k] = json.loads(m.get(k, "[]"))
    return m


def _snapshot_ref(meta: dict) -> dict:
    return {"as_of": meta.get("as_of"), "content_digest": meta.get("content_digest"), "served_from": "committed snapshot"}


# --- handlers -------------------------------------------------------------------------------------------------

def health(con, _sym=None, _q=None):
    meta = _meta(con)
    digest = snapshot.content_digest(con)
    ok = digest == meta.get("content_digest")
    return ("200 OK" if ok else "503 Service Unavailable"), {
        "status": "ok" if ok else "degraded", "version": VERSION,
        "commit": os.environ.get("RENDER_GIT_COMMIT"),
        "snapshot": {**_snapshot_ref(meta), "verified": ok, "companies": len(meta["symbols"]),
                     "schema_version": meta.get("schema_version"),
                     "announcements_retrieved_at": meta.get("announcements_retrieved_at") or None,
                     "prices_retrieved_at": meta.get("prices_retrieved_at") or None},
        "llm": "disabled (no model is called in this phase)",
        "live_fetch": "only /api/v1/diagnostics/connectivity touches the network",
    }


def companies(con, _sym=None, _q=None):
    meta = _meta(con)
    rows = [dict(r) for r in con.execute("SELECT * FROM companies ORDER BY symbol")]
    for r in rows:
        r["groups"], r["integrity"] = json.loads(r["groups"]), json.loads(r["integrity"])
        r["transcripts_audited"] = r["symbol"] in meta["transcript_symbols"]
    return "200 OK", {"snapshot": _snapshot_ref(meta), "count": len(rows), "companies": rows,
                      "sector_note": "sector is FINN's own portfolio grouping, not a classification from a source"}


def _company(con, sym):
    return con.execute("SELECT * FROM companies WHERE symbol = ?", (sym,)).fetchone()


def _not_in_snapshot(con, sym):
    return "404 Not Found", {"symbol": sym, "status": "unavailable", "snapshot": _snapshot_ref(_meta(con)),
                             "reason": "symbol is not in the committed snapshot; on-demand research for unseen "
                                       "tickers is not served by this phase of the API"}


def results(con, sym, _q=None):
    c = _company(con, sym)
    if c is None:
        return _not_in_snapshot(con, sym)
    card = service.results_card(con, sym)
    card["validation"] = {"level": c["validation"], "golden_values_checked": c["golden_checked"],
                          "meaning": {"golden_verified": "values match figures hand-transcribed from the signed results PDF",
                                      "integrity_checked": "accounting identities hold; not compared with the PDF by hand",
                                      "integrity_failed": "an accounting identity failed; treat with caution",
                                      "unavailable": "no results could be ingested"}[c["validation"]]}
    card["snapshot"] = _snapshot_ref(_meta(con))
    return ("200 OK" if card["status"] == "ok" else "404 Not Found"), card


def filings(con, sym, _q=None):
    if _company(con, sym) is None:
        return _not_in_snapshot(con, sym)
    return "200 OK", {**signals.company_filings(con, sym), "snapshot": _snapshot_ref(_meta(con)),
                      "note": "NSE subject and headline verbatim; FINN has not read the attached documents"}


def signal_inbox(con, _sym=None, q=None):
    try:
        settings = signals.parse_settings(q or {})
        body = signals.inbox(con, settings)
    except ValueError as e:
        return "400 Bad Request", {"error": str(e)}
    return "200 OK", {**body, "snapshot": _snapshot_ref(_meta(con))}


def transcripts(con, sym, _q=None):
    meta = _meta(con)
    if sym not in meta["transcript_symbols"]:
        if _company(con, sym) is None:
            return _not_in_snapshot(con, sym)
        return "200 OK", {"symbol": sym, "status": "not_audited", "snapshot": _snapshot_ref(meta),
                          "reason": "transcripts for this company were not retrieved for the snapshot", "quarters": []}
    quarters = [dict(r) for r in con.execute(
        "SELECT period_end, fiscal_quarter, status, seq_id, reason, duplicates FROM transcript_coverage "
        "WHERE symbol = ? ORDER BY period_end DESC", (sym,))]
    files = {r["seq_id"]: dict(r) for r in con.execute("SELECT * FROM transcript_filings WHERE symbol = ?", (sym,))}
    for f in files.values():
        f["quarter_votes"] = json.loads(f["quarter_votes"]) if f["quarter_votes"] else {}
        for k in ("scanned", "is_earnings_call", "quarter_ambiguous", "date_agrees"):
            f[k] = None if f[k] is None else bool(f[k])
    for q in quarters:
        q["duplicates"] = json.loads(q["duplicates"]) if q["duplicates"] else []
        q["document"] = files.get(q["seq_id"]) if q["seq_id"] else None
    used = {q["seq_id"] for q in quarters}
    return "200 OK", {"symbol": sym, "status": "ok", "snapshot": _snapshot_ref(meta),
                      "available": sum(q["status"] == "available" for q in quarters), "requested": len(quarters),
                      "quarters": quarters, "other_transcripts": [f for k, f in files.items() if k not in used],
                      "note": "metadata only; transcript text is not stored or served"}


def ledger_path() -> Path:
    return snapshot_path().parent / "promise_ledger.json"


_ledger_cache: dict = {}


def _ledger() -> dict | None:
    p = ledger_path()
    try:
        mtime = p.stat().st_mtime_ns
    except OSError:
        return None
    if _ledger_cache.get("key") != (str(p), mtime):
        _ledger_cache.update(key=(str(p), mtime), body=json.loads(p.read_text()))
    return _ledger_cache["body"]


def promises(con, sym, _q=None):
    if _company(con, sym) is None:
        return _not_in_snapshot(con, sym)
    meta = _meta(con)
    led = _ledger()
    if led is None:
        return "200 OK", {"symbol": sym, "status": "unavailable", "snapshot": _snapshot_ref(meta), "records": [],
                          "reason": "the promise ledger file is not present next to the snapshot"}
    co = led["companies"].get(sym)
    if co is None:
        return "200 OK", {"symbol": sym, "status": "not_audited", "snapshot": _snapshot_ref(meta), "records": [],
                          "reason": "management commitments were not extracted for this company; transcripts were "
                                    "audited for " + ", ".join(sorted(led["companies"]))}
    stale = led["built_from"]["snapshot_digest"] != meta.get("content_digest")
    return "200 OK", {"symbol": sym, "status": "stale" if stale else "ok", "stale": stale, "snapshot": _snapshot_ref(meta),
                      "ledger": {**led["built_from"], "version": led["ledger_version"], "audited_by": led["audited_by"],
                                 "method": led["method"]},
                      **({"stale_reason": "the ledger was built from a different snapshot; outcomes may be out of date"}
                         if stale else {}),
                      "records": co["records"], "excluded": co["excluded"], "counts": co["counts"],
                      "transcripts": co["transcripts"], "analyst_pointers": len(co["analyst_pointers"]),
                      "note": "short validated excerpts only; the transcripts themselves are not served"}


_diag_lock = threading.Lock()
_diag_cache: dict = {}


def _check(name: str, url: str, parse: Callable[[bytes], str]) -> dict:
    p = http.probe(url)
    out = {"name": name, "url": url, "reachable": p.ok, "http_status": p.status, "latency_ms": p.latency_ms,
           "bytes": p.bytes, "content_type": p.content_type, "parsed": False, "detail": p.reason}
    if p.ok:
        try:
            out["detail"], out["parsed"] = parse(p.body), True
        except Exception as e:                  # e.g. a 200 HTML block page instead of JSON
            out["detail"] = f"reachable but unparseable: {type(e).__name__}: {str(e)[:120]}"
    return out


def _nonempty(n: int, what: str) -> str:
    if n == 0:
        raise ValueError(f"0 {what}: empty response cannot be told apart from a silent block")
    return f"{n} {what}"


def connectivity(con, _sym=None, _q=None):
    with _diag_lock:
        cached = _diag_cache.get("result")
        if cached and time.monotonic() - _diag_cache["at"] < DIAG_TTL_S:
            return "200 OK", {**cached, "cached_for_s": DIAG_TTL_S, "age_s": int(time.monotonic() - _diag_cache["at"])}
        meta = _meta(con)
        sym = meta["symbols"][0]
        xbrl = con.execute("SELECT s.url FROM observations o JOIN sources s ON s.id = o.source_id WHERE o.symbol = ? "
                           "ORDER BY o.period_end DESC LIMIT 1", (sym,)).fetchone()["url"]
        today = datetime.now(snapshot.IST).date()
        now = datetime.now(timezone.utc)
        checks = [
            # 30 days, not 7: an empty list is also what a quietly blocked host might get, so it must not pass
            _check("nse_announcements", nse_filings.ANN_URL.format(symbol=sym, start=today - timedelta(days=30), end=today),
                   lambda b: _nonempty(len(nse_filings.parse_announcements(b, fetched_at=now, url='', sha=None, provenance='live')),
                                       "filings in 30 days")),
            _check("nse_results_listing", nse_results.LIST_URL.format(symbol=sym),
                   lambda b: f"{len(nse_results.parse_listing(b, sym))} result filings listed"),
            _check("nse_archives_xbrl", xbrl,
                   lambda b: f"{len(nse_results.parse_instance(b)['facts'])} XBRL facts"),
            _check("yahoo_chart", prices.CHART_URL.format(symbol=prices.yahoo_symbol(sym), range="5d"),
                   lambda b: f"{len(prices.parse_chart(b, fetched_at=now, url='', sha=None, provenance='live'))} daily bars"),
        ]
        result = {"tested_at": now.isoformat(timespec="seconds"), "host": os.environ.get("RENDER_SERVICE_NAME") or "unknown",
                  "symbol_used": sym, "all_ok": all(c["reachable"] and c["parsed"] for c in checks), "checks": checks,
                  "note": "live requests from the machine serving this API; nothing is cached to disk"}
        _diag_cache.update(result=result, at=time.monotonic())
        return "200 OK", {**result, "cached_for_s": DIAG_TTL_S, "age_s": 0}


ROUTES = [
    (re.compile(r"^/health/?$"), health),
    (re.compile(r"^/api/v1/companies/?$"), companies),
    (re.compile(r"^/api/v1/companies/([^/]+)/results/?$"), results),
    (re.compile(r"^/api/v1/companies/([^/]+)/transcripts/?$"), transcripts),
    (re.compile(r"^/api/v1/companies/([^/]+)/filings/?$"), filings),
    (re.compile(r"^/api/v1/companies/([^/]+)/promises/?$"), promises),
    (re.compile(r"^/api/v1/signals/?$"), signal_inbox),
    (re.compile(r"^/api/v1/diagnostics/connectivity/?$"), connectivity),
]
DIAG_HEADER = "HTTP_X_FINN_DIAGNOSTICS_TOKEN"


def _diag_denied(environ) -> tuple[str, dict] | None:
    """The live probe hits NSE and Yahoo from this host, so only an operator holding the token may trigger it."""
    token = os.environ.get("FINN_DIAG_TOKEN", "")
    if not token:
        return "403 Forbidden", {"error": "diagnostics are disabled: FINN_DIAG_TOKEN is not configured on this host"}
    if not hmac.compare_digest(environ.get(DIAG_HEADER, "").encode(), token.encode()):
        return "401 Unauthorized", {"error": "diagnostics need the X-Finn-Diagnostics-Token header"}
    return None


def app(environ, start_response):
    path = environ.get("PATH_INFO") or "/"
    method = environ.get("REQUEST_METHOD", "GET")
    if path in ("/", "/index.html") and method in ("GET", "HEAD"):
        return _static(start_response, "index.html", method)
    sm = STATIC.match(path)
    if sm and method in ("GET", "HEAD"):
        return _static(start_response, sm.group(1), method)
    if path.rstrip("/") == "/api/v1":
        return _json(start_response, "200 OK", {"service": "FINN API", "version": VERSION,
                                                 "endpoints": [r.pattern for r, _ in ROUTES]})
    for rx, handler in ROUTES:
        m = rx.match(path)
        if not m:
            continue
        is_diag = handler is connectivity
        origin = None if is_diag else allowed_origin(environ.get("HTTP_ORIGIN"))
        if method == "OPTIONS":                 # CORS preflight: answered only for allowlisted origins
            if origin is None:
                return _json(start_response, "403 Forbidden", {"error": "origin not allowed"})
            start_response("204 No Content", [*_cors(origin), ("Access-Control-Allow-Methods", "GET, HEAD"),
                                              ("Access-Control-Allow-Headers", "Accept"), ("Access-Control-Max-Age", "600"),
                                              ("Content-Length", "0")])
            return [b""]
        if method not in ("GET", "HEAD"):
            return _json(start_response, "405 Method Not Allowed", {"error": "read-only API: GET only"}, [("Allow", "GET, HEAD")],
                         origin=origin)
        if is_diag and (denied := _diag_denied(environ)):
            return _json(start_response, *denied, cache="no-store")
        sym = None
        if m.groups():
            sym = m.group(1).upper()
            if not SYMBOL.match(sym):
                return _json(start_response, "400 Bad Request", {"error": "symbol must be 1-20 of A-Z, 0-9, & or -"},
                             origin=origin)
        q = dict(parse_qsl(environ.get("QUERY_STRING", ""), keep_blank_values=False))
        try:
            con = snapshot.open_readonly(snapshot_path())
        except Exception as e:
            return _json(start_response, "503 Service Unavailable",
                         {"status": "unavailable", "reason": f"snapshot cannot be opened: {type(e).__name__}"}, origin=origin)
        try:
            status, body = handler(con, sym, q)
        except Exception as e:                  # never leak a traceback; say what failed
            status, body = "500 Internal Server Error", {"error": f"{type(e).__name__} while serving {path}"}
        finally:
            con.close()
        out = _json(start_response, status, body, origin=origin, cache="no-store" if is_diag else "public, max-age=300")
        return [b""] if method == "HEAD" else out
    return _json(start_response, "404 Not Found", {"error": "no such endpoint", "endpoints": [r.pattern for r, _ in ROUTES]})


if __name__ == "__main__":                      # local dev server: python -m finn.api [port]
    import sys
    from wsgiref.simple_server import make_server
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", "8000"))
    print(f"FINN API on http://127.0.0.1:{port}  (snapshot {snapshot_path()})")
    make_server("127.0.0.1", port, app).serve_forever()
