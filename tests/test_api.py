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


def call(path, method="GET"):
    env = {"PATH_INFO": path, "REQUEST_METHOD": method, "wsgi.input": io.BytesIO()}
    seen = {}

    def start_response(status, headers):
        seen["status"], seen["headers"] = status, dict(headers)
    body = b"".join(api.app(env, start_response))
    return int(seen["status"].split()[0]), seen["headers"], (json.loads(body) if body else None)


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
    code, _, body = call("/api/v1/diagnostics/connectivity")
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
    _, _, body = call("/api/v1/diagnostics/connectivity")
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
