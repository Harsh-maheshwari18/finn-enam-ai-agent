"""The deployed API serves the committed, validated snapshot with no network and no LLM."""
import io
import json
import socket
import sys
import urllib.request
from decimal import Decimal as D
from pathlib import Path

import pytest

from finn import api, metrics, snapshot

ROOT = Path(__file__).parent.parent
SNAP = ROOT / "snapshot" / "finn_snapshot.db"
MANIFEST = json.loads((ROOT / "snapshot" / "manifest.json").read_text())
GOLD = json.loads((ROOT / "tests" / "fixtures" / "real" / "golden_set.json").read_text())


NET_ATTEMPTS: list = []


@pytest.fixture(autouse=True)
def no_network_no_llm(monkeypatch, request):
    """Any network attempt fails like a real outage (OSError) and is recorded; only the diagnostics test may try."""
    NET_ATTEMPTS.clear()

    def refuse(*a, **k):
        NET_ATTEMPTS.append(a[:1])
        raise OSError("network blocked by test")
    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("FINN_LLM_DISABLED", "1")
    monkeypatch.setenv("FINN_SNAPSHOT", str(SNAP))
    yield
    if "allow_network_attempts" not in request.keywords:
        assert NET_ATTEMPTS == [], f"unexpected network access: {NET_ATTEMPTS}"


DIAG_TOKEN = "test-token-not-a-secret"


def call(path, method="GET", headers=None, query=""):
    env = {"PATH_INFO": path, "REQUEST_METHOD": method, "wsgi.input": io.BytesIO(), "QUERY_STRING": query}
    for k, v in (headers or {}).items():
        env["HTTP_" + k.upper().replace("-", "_")] = v
    seen = {}

    def start_response(status, headers):
        seen["status"], seen["headers"] = status, dict(headers)
    body = b"".join(api.app(env, start_response))
    ctype = seen["headers"].get("Content-Type", "")
    return int(seen["status"].split()[0]), seen["headers"], (json.loads(body) if body and ctype.startswith("application/json") else body)


def diag_call(monkeypatch):
    monkeypatch.setenv("FINN_DIAG_TOKEN", DIAG_TOKEN)
    return call("/api/v1/diagnostics/connectivity", headers={"X-Finn-Diagnostics-Token": DIAG_TOKEN})


def test_health_reports_verified_snapshot():
    code, headers, body = call("/health")
    assert code == 200 and body["status"] == "ok"
    assert body["snapshot"]["verified"] is True
    assert body["snapshot"]["content_digest"] == MANIFEST["content_digest"]
    assert headers["Content-Type"].startswith("application/json")


def test_tcs_results_card_served_offline():
    code, _, card = call("/api/v1/companies/TCS/results")
    assert code == 200 and card["status"] == "ok"
    assert (card["period_end"], card["basis"], card["taxonomy"]) == ("2026-09-30", "consolidated", "indas")
    rows = {r["metric"]: r for r in card["rows"]}
    assert [rows[m]["value_cr"] for m in ("revenue", "ebitda", "pbt", "pat")] == ["73188.00", "18815.00", "18638.00", "13934.00"]
    assert rows["revenue"]["qoq"]["pct"] == "1.26" and rows["revenue"]["yoy"]["pct"] == "11.23"
    assert rows["pat"]["qoq"]["pct"] == "3.83" and rows["pat"]["yoy"]["pct"] == "14.86"
    assert card["ebitda_margin_pct"] == "25.71"
    assert card["validation"]["level"] == "golden_verified"
    assert card["snapshot"]["content_digest"] == MANIFEST["content_digest"]


def test_every_served_number_carries_its_source():
    _, _, card = call("/api/v1/companies/TCS/results")
    for r in card["rows"]:
        s = r["source"]
        assert s["url"].startswith("https://nsearchives.nseindia.com/corporate/xbrl/")
        assert s["location"].startswith("context ") and s["retrieved_at"] and s["provenance"] == "snapshot"


def test_lowercase_symbol_is_accepted():
    assert call("/api/v1/companies/tcs/results")[0] == 200


@pytest.mark.parametrize("g", GOLD["observations"], ids=lambda g: f"{g['symbol']}-{g['period_end']}-{g['metric']}")
def test_snapshot_holds_golden_values(g):
    con = snapshot.open_readonly(SNAP)
    r = con.execute("SELECT value FROM observations WHERE symbol=? AND metric=? AND period_end=? AND basis='consolidated'",
                    (g["symbol"], g["metric"], g["period_end"])).fetchone()
    expected = metrics.from_reported(D(g["reported"]), GOLD["documents"][g["doc"]]["unit"])
    assert r is not None and metrics.to_crore(D(r["value"])) == metrics.to_crore(expected), g["line"]


def test_bank_card_keeps_bank_metrics_and_warning():
    _, _, card = call("/api/v1/companies/HDFCBANK/results")
    rows = {r["metric"]: r for r in card["rows"]}
    assert rows["pbt"]["value_cr"] == "28662.54" and rows["pat"]["qoq"]["pct"] == "7.56"
    assert rows["ebitda"]["status"] == "not_applicable"
    assert any(c["status"] == "warn" for c in card["integrity"])


def test_companies_lists_universe_with_validation():
    _, _, body = call("/api/v1/companies")
    by = {c["symbol"]: c for c in body["companies"]}
    assert body["count"] == len(MANIFEST["companies"]) >= 18
    assert {by[s]["validation"] for s in ("TCS", "HDFCBANK", "POLYCAB")} == {"golden_verified"}
    assert all(c["validation"] != "integrity_failed" for c in body["companies"])


def test_transcript_inventory():
    code, _, body = call("/api/v1/companies/TCS/transcripts")
    assert code == 200 and body["requested"] == 4
    for q in body["quarters"]:
        assert q["status"] in ("available", "missing", "unreadable")
        if q["status"] == "available":
            d = q["document"]
            assert d["url"].startswith("https://nsearchives.nseindia.com/") and d["sha256"] and d["pages"] > 0
            assert d["fiscal_quarter"] == q["fiscal_quarter"] and d["is_earnings_call"] is True
        else:
            assert q["reason"]


def test_transcripts_not_audited_is_explicit():
    code, _, body = call("/api/v1/companies/ITC/transcripts")
    assert code == 200 and body["status"] == "not_audited" and body["quarters"] == []


def test_unknown_symbol_is_honest_404():
    code, _, body = call("/api/v1/companies/NOSUCHCO/results")
    assert code == 404 and body["status"] == "unavailable" and "not in the committed snapshot" in body["reason"]


@pytest.mark.parametrize("path", ["/api/v1/companies/..%2Fetc/results", "/api/v1/companies/A;DROP/results",
                                  "/api/v1/companies/" + "X" * 21 + "/results"])
def test_bad_symbol_rejected(path):
    assert call(path)[0] == 400


def test_write_methods_refused():
    code, headers, _ = call("/api/v1/companies/TCS/results", method="POST")
    assert code == 405 and headers["Allow"] == "GET, HEAD"


def test_unknown_path_404():
    assert call("/api/v1/nope")[0] == 404


def test_missing_snapshot_is_503_not_crash(monkeypatch, tmp_path):
    monkeypatch.setenv("FINN_SNAPSHOT", str(tmp_path / "absent.db"))
    code, _, body = call("/api/v1/companies/TCS/results")
    assert code == 503 and body["status"] == "unavailable"


def test_snapshot_is_opened_read_only():
    con = snapshot.open_readonly(SNAP)
    with pytest.raises(Exception):
        con.execute("DELETE FROM observations")


@pytest.mark.allow_network_attempts
def test_connectivity_reports_failure_instead_of_crashing(monkeypatch):
    api._diag_cache.clear()
    monkeypatch.setattr(api.http, "_throttle", lambda host: None)
    code, _, body = diag_call(monkeypatch)
    assert code == 200 and body["all_ok"] is False
    assert {c["name"] for c in body["checks"]} == {"nse_announcements", "nse_results_listing", "nse_archives_xbrl", "yahoo_chart"}
    assert all(not c["reachable"] and c["detail"] for c in body["checks"])
    assert len(NET_ATTEMPTS) == 4                # one live attempt per check, no retries, no cache fallback
    api._diag_cache.clear()


def test_no_llm_sdk_loaded():
    for p in ("/health", "/api/v1/companies/TCS/results", "/api/v1/companies/TCS/transcripts"):
        call(p)
    assert "anthropic" not in sys.modules


def test_empty_nse_answer_does_not_count_as_reachable(monkeypatch):
    """A host that NSE silently blocks may get 200 with an empty list; diagnostics must not report that as working."""
    api._diag_cache.clear()

    def fake_probe(url, timeout=15):
        body = b"[]" if "corporate-announcements" in url else b"not json"
        return api.http.Probe(url, True, 200, 5, len(body), "application/json", body, None)
    monkeypatch.setattr(api.http, "probe", fake_probe)
    _, _, body = diag_call(monkeypatch)
    ann = next(c for c in body["checks"] if c["name"] == "nse_announcements")
    assert ann["reachable"] is True and ann["parsed"] is False and "silent block" in ann["detail"]
    assert body["all_ok"] is False
    api._diag_cache.clear()


def test_card_states_comparison_basis():
    _, _, card = call("/api/v1/companies/BAJFINANCE/results")
    assert "as originally filed" in card["comparison_basis"]


def test_excise_netted_revenue_served_for_itc():
    """ITC signed PDF p.6: excise duty 10,408.93 cr is inside Revenue from operations; the card shows revenue net of it."""
    _, _, card = call("/api/v1/companies/ITC/results")
    rev = next(r for r in card["rows"] if r["metric"] == "revenue")
    assert rev["value_cr"] == "19114.37" and rev["formula"] == "revenue_from_operations - excise_duty"
    assert rev["qoq"]["status"] == rev["yoy"]["status"] == "ok"


def test_served_timestamps_carry_offsets():
    """published_at is NSE time (IST, +05:30); retrieved_at is our clock (UTC). Neither may be naive."""
    _, _, card = call("/api/v1/companies/TCS/results")
    rev = next(r for r in card["rows"] if r["metric"] == "revenue")
    assert rev["source"]["published_at"] == "2026-10-08T22:07:33+05:30"     # NSE broadcast_Date '08-Oct-2026 22:07:33'
    for r in card["rows"]:
        assert r["source"]["published_at"].endswith("+05:30") and r["source"]["retrieved_at"].endswith("+00:00")


def test_transcript_broadcast_at_carries_ist_offset():
    _, _, body = call("/api/v1/companies/POLYCAB/transcripts")
    q2 = next(q for q in body["quarters"] if q["fiscal_quarter"] == "Q2 FY27")
    assert q2["document"]["broadcast_at"] == "2026-10-19T16:39:28+05:30"     # NSE an_dt '19-Oct-2026 16:39:28'


@pytest.mark.parametrize("sym", ["TCS", "POLYCAB", "HDFCBANK"])
def test_four_quarter_transcript_coverage(sym):
    """Availability only: says nothing about whether the calls contain checkable guidance."""
    _, _, body = call(f"/api/v1/companies/{sym}/transcripts")
    assert [q["fiscal_quarter"] for q in body["quarters"]] == ["Q2 FY27", "Q1 FY27", "Q4 FY26", "Q3 FY26"]
    seen = set()
    for q in body["quarters"]:
        d = q["document"]
        assert q["status"] == "available" and q["duplicates"] == []
        assert d["is_earnings_call"] and not d["scanned"] and d["fiscal_quarter"] == q["fiscal_quarter"] and d["date_agrees"]
        assert d["url"].startswith("https://nsearchives.nseindia.com/corporate/") and len(d["sha256"]) == 64
        assert d["retrieved_at"].endswith("+00:00") and d["broadcast_at"].endswith("+05:30")
        assert d["pages"] > 0 and d["text_chars"] > 10_000 and d["speaker_turns"] > 0 and d["quarter_phrase"]
        seen.add(d["sha256"])
    assert len(seen) == 4                                                    # four distinct documents


# ---------------------------------------------------------------- Signal Inbox (Prompt 4)

def _db():
    import sqlite3
    return sqlite3.connect(SNAP)


def test_signals_served_from_real_snapshot_records():
    code, headers, body = call("/api/v1/signals", query="window=30d")
    assert code == 200 and body["status"] == "ok"
    seqs = {r[0] for r in _db().execute("SELECT seq_id FROM filings")}
    portfolio = set(json.loads(dict(_db().execute("SELECT key, value FROM snapshot_meta").fetchall())["portfolio"]))
    for s in body["signals"] + body["folded"]:
        assert s["symbol"] in portfolio
        assert s["score"] == sum(p["points"] for p in s["score_parts"])
        if s["kind"] == "announcement":
            assert s["id"].removeprefix("ann-") in seqs                 # every card is a stored NSE filing
            assert s["published_at"].endswith("+05:30") and s["source"]["retrieved_at"].endswith("+00:00")
            assert s["source"]["listing_url"].startswith("https://www.nseindia.com/api/corporate-announcements")
        else:
            assert s["kind"] == "price" and s["source"]["listing_url"].startswith("https://query1.finance.yahoo.com/")
    assert body["window"]["end"].endswith("+05:30") and "not the viewer's clock" in body["window"]["anchored_to"]


def test_results_signal_carries_verified_numbers_only_when_same_day():
    _, _, body = call("/api/v1/signals", query="window=30d")
    res = [s for s in body["signals"] if s["category"] == "results"]
    assert res, "the 30-day window holds results filings"
    for s in res:
        n = s["numbers"]
        if n and n["matches_filing"]:
            _, _, card = call(f"/api/v1/companies/{s['symbol']}/results")
            assert [r["value_cr"] for r in n["rows"]] == [r["value_cr"] for r in card["rows"]]
        else:
            assert not (n and n["rows"]) and any("not ingested" in u for u in s["unknowns"])


def test_signals_window_narrows_records():
    counts = [call("/api/v1/signals", query=f"window={w}")[2]["counts"] for w in ("24h", "3d", "7d", "30d")]
    totals = [c["ranked"] + c["folded"] for c in counts]
    assert totals == sorted(totals)


@pytest.mark.parametrize("query", ["window=1y", "move_pct=x", "volume_x=99", "lookback=1", "mute=nope", "symbols=NOSUCH"])
def test_signals_bad_settings_are_400(query):
    code, _, body = call("/api/v1/signals", query=query)
    assert code == 400 and body["error"]


def test_company_filings_endpoint():
    code, _, body = call("/api/v1/companies/POLYCAB/filings")
    assert code == 200 and body["count"] == len(body["filings"])
    assert all(f["published_at"].endswith("+05:30") for f in body["filings"])
    assert body["last_session"] is None or body["last_session"]["retrieved_at"].endswith("+00:00")
    assert call("/api/v1/companies/NOSUCH/filings")[0] == 404


def test_snapshot_price_bars_are_completed_sessions_with_sources():
    rows = _db().execute("SELECT COUNT(*), COUNT(DISTINCT symbol), MAX(day) FROM price_bars").fetchone()
    built = MANIFEST["built_at"]
    assert rows[0] > 0 and rows[1] == MANIFEST["signals"]["price_bars"]["companies"]
    assert rows[2] <= built[:10]                                         # no session after the build date
    assert _db().execute("SELECT COUNT(*) FROM price_bars p LEFT JOIN sources s ON s.id = p.source_id "
                         "WHERE s.url IS NULL").fetchone()[0] == 0


def test_companies_carry_nse_name_and_labelled_sector():
    _, _, body = call("/api/v1/companies")
    tcs = next(c for c in body["companies"] if c["symbol"] == "TCS")
    assert tcs["name"] == "Tata Consultancy Services Limited" and tcs["sector"] == "IT services"
    assert "FINN's own" in body["sector_note"] and tcs["transcripts_audited"] is True


# ---------------------------------------------------------------- cross-origin, diagnostics, static app

def test_no_wildcard_cors_by_default(monkeypatch):
    monkeypatch.delenv("FINN_CORS_ORIGINS", raising=False)
    _, headers, _ = call("/api/v1/companies", headers={"Origin": "https://evil.example"})
    assert "Access-Control-Allow-Origin" not in headers and headers["Vary"] == "Origin"


def test_allowlisted_origin_and_preflight(monkeypatch):
    monkeypatch.setenv("FINN_CORS_ORIGINS", "https://finn-web.onrender.com, https://other.example")
    _, headers, _ = call("/api/v1/signals", headers={"Origin": "https://finn-web.onrender.com"})
    assert headers["Access-Control-Allow-Origin"] == "https://finn-web.onrender.com"
    code, headers, _ = call("/api/v1/signals", method="OPTIONS", headers={"Origin": "https://finn-web.onrender.com"})
    assert code == 204 and headers["Access-Control-Allow-Methods"] == "GET, HEAD"
    assert call("/api/v1/signals", method="OPTIONS", headers={"Origin": "https://finn-web.onrender.com.evil.example"})[0] == 403


def test_dev_origins_only_in_dev_mode(monkeypatch):
    monkeypatch.delenv("FINN_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("FINN_CORS_DEV", raising=False)
    assert "Access-Control-Allow-Origin" not in call("/health", headers={"Origin": "http://localhost:5173"})[1]
    monkeypatch.setenv("FINN_CORS_DEV", "1")
    assert call("/health", headers={"Origin": "http://localhost:5173"})[1]["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert "Access-Control-Allow-Origin" not in call("/health", headers={"Origin": "http://localhost.evil.example:80"})[1]


def test_diagnostics_need_token_and_never_get_cors(monkeypatch):
    api._diag_cache.clear()
    monkeypatch.delenv("FINN_DIAG_TOKEN", raising=False)
    assert call("/api/v1/diagnostics/connectivity")[0] == 403                 # not configured: disabled
    monkeypatch.setenv("FINN_DIAG_TOKEN", DIAG_TOKEN)
    monkeypatch.setenv("FINN_CORS_ORIGINS", "https://finn-web.onrender.com")
    code, headers, _ = call("/api/v1/diagnostics/connectivity", headers={"Origin": "https://finn-web.onrender.com"})
    assert code == 401 and "Access-Control-Allow-Origin" not in headers
    assert call("/api/v1/diagnostics/connectivity", headers={"X-Finn-Diagnostics-Token": "wrong"})[0] == 401
    assert call("/api/v1/diagnostics/connectivity", method="OPTIONS", headers={"Origin": "https://finn-web.onrender.com"})[0] == 403
    assert NET_ATTEMPTS == [] and api._diag_cache == {}                       # nothing probed


def test_web_app_served_with_csp():
    code, headers, body = call("/")
    assert code == 200 and headers["Content-Type"].startswith("text/html") and b"FINN" in body
    assert "script-src 'self'" in headers["Content-Security-Policy"] and "unsafe" not in headers["Content-Security-Policy"]
    for f in ("app.js", "styles.css", "config.js", "icon.svg"):
        assert call("/" + f)[0] == 200
    assert call("/../finn/api.py")[0] == 404 and call("/snapshot.db")[0] == 404 and call("/.env")[0] == 404
    code, _, body = call("/api/v1")
    assert code == 200 and any("signals" in e for e in body["endpoints"])
