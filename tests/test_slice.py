"""End-to-end vertical slice, offline, from real cached responses."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from finn import http, service, store
from finn.adapters import nse_results

FIX = Path(__file__).parent / "fixtures" / "real"
ROOT = Path(__file__).parent.parent


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setenv("FINN_CACHE_DIR", str(tmp_path / "raw"))
    at = datetime(2026, 10, 27, 6, 0, tzinfo=timezone.utc)
    for sym in ("TCS", "HDFCBANK", "POLYCAB"):
        listing = (FIX / f"nse_int_{sym}.json").read_bytes()
        http._write_cache(http.Fetched(True, nse_results.LIST_URL.format(symbol=sym), 200, listing, at, False, None))
        for x in json.loads(listing)["data"]:
            f = FIX / f"xbrl_{sym}_{x['qe_Date']}_C.xml"
            if x["consolidated"] == "Consolidated" and f.exists():
                http._write_cache(http.Fetched(True, x["xbrl"], 200, f.read_bytes(), at, False, None))
    return store.connect(":memory:")


def test_tcs_card(con):
    assert service.ingest_results(con, "TCS", offline=True) == []
    card = service.results_card(con, "TCS")
    rows = {r["metric"]: r for r in card["rows"]}
    assert (card["period_end"], card["basis"], card["taxonomy"]) == ("2026-09-30", "consolidated", "indas")
    assert [rows[m]["value_cr"] for m in ("revenue", "ebitda", "pbt", "pat")] == ["73188.00", "18815.00", "18638.00", "13934.00"]
    assert rows["revenue"]["qoq"] == {"pct": "1.26", "status": "ok", "prev_cr": "72275.00", "note": None}
    assert rows["revenue"]["yoy"]["pct"] == "11.23"
    assert card["ebitda_margin_pct"] == "25.71"


def test_provenance_survives_storage(con):
    service.ingest_results(con, "HDFCBANK", offline=True)
    card = service.results_card(con, "HDFCBANK")
    for r in card["rows"]:
        s = r["source"]
        assert s["url"].startswith("https://nsearchives.nseindia.com/corporate/xbrl/") and s["location"].startswith("context ")
        assert s["retrieved_at"].startswith("2026-10-27") and s["provenance"] == "cached"


def test_bank_card(con):
    service.ingest_results(con, "HDFCBANK", offline=True)
    rows = {r["metric"]: r for r in service.results_card(con, "HDFCBANK")["rows"]}
    assert rows["ebitda"]["status"] == "not_applicable" and rows["ebitda"]["value_cr"] is None
    assert rows["ebitda"]["qoq"]["status"] == rows["ebitda"]["yoy"]["status"] == "not_applicable"
    assert rows["pat"]["value_cr"] == "20700.03" and rows["pbt"]["value_cr"] == "28662.54"
    assert rows["pat"]["qoq"]["pct"] == "7.56"


def test_source_unavailable_does_not_crash(con):
    problems = service.ingest_results(con, "NOTCACHED", offline=True)
    assert problems and problems[0].source == "nse_results_listing"
    assert service.results_card(con, "NOTCACHED")["status"] == "unavailable"


def test_corrupt_xbrl_is_reported_not_raised(con, tmp_path):
    ref = next(r for r in nse_results.parse_listing((FIX / "nse_int_POLYCAB.json").read_bytes(), "POLYCAB")
               if r.basis == "consolidated" and r.period_end.isoformat() == "2026-06-30")
    http._write_cache(http.Fetched(True, ref.xbrl_url, 200, b"<xbrl><broken", datetime.now(timezone.utc), False, None))
    problems = service.ingest_results(con, "POLYCAB", offline=True)
    assert len(problems) == 1 and "unparseable XBRL" in problems[0].reason
    rows = {r["metric"]: r for r in service.results_card(con, "POLYCAB")["rows"]}
    assert rows["revenue"]["value_cr"] == "9898.90" and rows["revenue"]["qoq"]["status"] == "missing"


def test_engine_has_no_hardcoded_tickers():
    """Generalisation guard: tickers may appear in config and tests, never in engine code."""
    known = {"TCS", "HDFCBANK", "POLYCAB", "RELIANCE", "INFY", "BEL", "CAMS"}
    for py in (ROOT / "finn").rglob("*.py"):
        code = "\n".join(l for l in py.read_text().splitlines() if not l.strip().startswith("#"))
        code = re.sub(r'""".*?"""', "", code, flags=re.S)
        hits = {t for t in known if re.search(rf'["\']{t}(\.NS)?["\']', code)}
        assert not hits, f"{py.name}: {hits}"
