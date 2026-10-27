"""Read-only HTTP API over the committed snapshot. Plain WSGI, no framework: `gunicorn finn.api:app`.

GET /health                                   snapshot identity and whether it verifies
GET /api/v1/companies                         every company in the snapshot with its validation level
GET /api/v1/companies/{SYMBOL}/results        results card; every number carries its source
GET /api/v1/companies/{SYMBOL}/transcripts    earnings-call transcript inventory (metadata only)
GET /api/v1/diagnostics/connectivity          live NSE / Yahoo reachability from THIS host (rate limited)

Requests never call an LLM and never fetch live data, except the diagnostics endpoint, which is explicit about it.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from finn import http, service, snapshot
from finn.adapters import nse_filings, nse_results, prices

VERSION = "0.2.0"
SYMBOL = re.compile(r"^[A-Z0-9&\-]{1,20}$")
DIAG_TTL_S = 600


def snapshot_path() -> Path:
    return Path(os.environ.get("FINN_SNAPSHOT", snapshot.DEFAULT_OUT))


def _json(start_response, status: str, body: dict, extra: list[tuple[str, str]] = ()) -> list[bytes]:
    data = json.dumps(body, default=str, indent=1).encode()
    start_response(status, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(data))),
                            ("Cache-Control", "public, max-age=300"), ("X-Content-Type-Options", "nosniff"),
                            ("Access-Control-Allow-Origin", "*"), *extra])
    return [data]


def _meta(con) -> dict:
    m = dict(con.execute("SELECT key, value FROM snapshot_meta").fetchall())
    for k in ("symbols", "transcript_symbols"):
        m[k] = json.loads(m.get(k, "[]"))
    return m


def _snapshot_ref(meta: dict) -> dict:
    return {"as_of": meta.get("as_of"), "content_digest": meta.get("content_digest"), "served_from": "committed snapshot"}


# --- handlers -------------------------------------------------------------------------------------------------

def health(con, _sym=None):
    meta = _meta(con)
    digest = snapshot.content_digest(con)
    ok = digest == meta.get("content_digest")
    return ("200 OK" if ok else "503 Service Unavailable"), {
        "status": "ok" if ok else "degraded", "version": VERSION,
        "commit": os.environ.get("RENDER_GIT_COMMIT"),
        "snapshot": {**_snapshot_ref(meta), "verified": ok, "companies": len(meta["symbols"]),
                     "schema_version": meta.get("schema_version")},
        "llm": "disabled (no model is called in this phase)",
        "live_fetch": "only /api/v1/diagnostics/connectivity touches the network",
    }


def companies(con, _sym=None):
    rows = [dict(r) for r in con.execute("SELECT * FROM companies ORDER BY symbol")]
    for r in rows:
        r["groups"], r["integrity"] = json.loads(r["groups"]), json.loads(r["integrity"])
    return "200 OK", {"snapshot": _snapshot_ref(_meta(con)), "count": len(rows), "companies": rows}


def _company(con, sym):
    return con.execute("SELECT * FROM companies WHERE symbol = ?", (sym,)).fetchone()


def _not_in_snapshot(con, sym):
    return "404 Not Found", {"symbol": sym, "status": "unavailable", "snapshot": _snapshot_ref(_meta(con)),
                             "reason": "symbol is not in the committed snapshot; on-demand research for unseen "
                                       "tickers is not served by this phase of the API"}


def results(con, sym):
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


def transcripts(con, sym):
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


def connectivity(con, _sym=None):
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
    (re.compile(r"^/api/v1/diagnostics/connectivity/?$"), connectivity),
]


def app(environ, start_response):
    path = environ.get("PATH_INFO") or "/"
    method = environ.get("REQUEST_METHOD", "GET")
    if path == "/":
        return _json(start_response, "200 OK", {"service": "FINN API", "version": VERSION,
                                                 "endpoints": [r.pattern for r, _ in ROUTES]})
    for rx, handler in ROUTES:
        m = rx.match(path)
        if not m:
            continue
        if method not in ("GET", "HEAD"):
            return _json(start_response, "405 Method Not Allowed", {"error": "read-only API: GET only"}, [("Allow", "GET, HEAD")])
        sym = None
        if m.groups():
            sym = m.group(1).upper()
            if not SYMBOL.match(sym):
                return _json(start_response, "400 Bad Request", {"error": "symbol must be 1-20 of A-Z, 0-9, & or -"})
        try:
            con = snapshot.open_readonly(snapshot_path())
        except Exception as e:
            return _json(start_response, "503 Service Unavailable",
                         {"status": "unavailable", "reason": f"snapshot cannot be opened: {type(e).__name__}"})
        try:
            status, body = handler(con, sym)
        except Exception as e:                  # never leak a traceback; say what failed
            status, body = "500 Internal Server Error", {"error": f"{type(e).__name__} while serving {path}"}
        finally:
            con.close()
        out = _json(start_response, status, body)
        return [b""] if method == "HEAD" else out
    return _json(start_response, "404 Not Found", {"error": "no such endpoint", "endpoints": [r.pattern for r, _ in ROUTES]})


if __name__ == "__main__":                      # local dev server: python -m finn.api [port]
    import sys
    from wsgiref.simple_server import make_server
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", "8000"))
    print(f"FINN API on http://127.0.0.1:{port}  (snapshot {snapshot_path()})")
    make_server("127.0.0.1", port, app).serve_forever()
