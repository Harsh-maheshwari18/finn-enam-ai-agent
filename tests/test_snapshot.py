"""Snapshot build: validated, reproducible, small, and free of document text."""
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from finn import http, service, snapshot
from finn.adapters import nse_results

FIX = Path(__file__).parent / "fixtures" / "real"
ROOT = Path(__file__).parent.parent
SNAP = ROOT / "snapshot" / "finn_snapshot.db"
SYMS = ["TCS", "HDFCBANK", "POLYCAB"]


@pytest.fixture
def seeded_cache(tmp_path, monkeypatch):
    """Raw cache filled from the committed real NSE fixtures, so builds run offline."""
    monkeypatch.setenv("FINN_CACHE_DIR", str(tmp_path / "raw"))
    at = datetime(2026, 10, 27, 6, 0, tzinfo=timezone.utc)
    for sym in SYMS:
        listing = (FIX / f"nse_int_{sym}.json").read_bytes()
        http._write_cache(http.Fetched(True, nse_results.LIST_URL.format(symbol=sym), 200, listing, at, False, None))
        for x in json.loads(listing)["data"]:
            f = FIX / f"xbrl_{sym}_{x['qe_Date']}_C.xml"
            if x["consolidated"] == "Consolidated" and f.exists():
                http._write_cache(http.Fetched(True, x["xbrl"], 200, f.read_bytes(), at, False, None))
    return tmp_path


def _build(dirpath, name, **kw):
    out = Path(dirpath) / f"{name}.db"
    return out, snapshot.build(out, symbols=SYMS, transcript_symbols=[], as_of=date(2026, 10, 27), offline=True,
                               manifest_path=Path(dirpath) / f"{name}.json", **kw)


def test_build_is_reproducible(seeded_cache):
    _, a = _build(seeded_cache, "a")
    _, b = _build(seeded_cache, "b")
    assert a["content_digest"] == b["content_digest"]
    assert a["golden_values_checked"] == 44
    assert {c["validation"] for c in a["companies"].values()} == {"golden_verified"}


def test_build_refuses_on_golden_mismatch(seeded_cache):
    gold = json.loads((FIX / "golden_set.json").read_text())
    g = next(x for x in gold["observations"] if x["symbol"] == "TCS" and x["metric"] == "revenue")
    g["reported"] = str(float(g["reported"]) + 1)
    bad = seeded_cache / "bad_gold.json"
    bad.write_text(json.dumps(gold))
    out = seeded_cache / "refused.db"
    with pytest.raises(snapshot.BuildError, match="TCS .* revenue"):
        snapshot.build(out, symbols=SYMS, transcript_symbols=[], as_of=date(2026, 10, 27), offline=True,
                       golden_path=bad, manifest_path=seeded_cache / "refused.json")
    assert not out.exists() and not out.with_suffix(".building").exists()


def test_unreachable_symbol_is_recorded_not_fatal(seeded_cache):
    out = seeded_cache / "partial.db"
    m = snapshot.build(out, symbols=SYMS + ["NOTCACHED"], transcript_symbols=[], as_of=date(2026, 10, 27),
                       offline=True, manifest_path=seeded_cache / "partial.json")
    assert m["companies"]["NOTCACHED"]["validation"] == "unavailable"
    con = snapshot.open_readonly(out)
    assert con.execute("SELECT reason FROM unavailable WHERE symbol='NOTCACHED'").fetchone()


def test_committed_snapshot_matches_fixture_rebuild(seeded_cache):
    """The committed snapshot (built live) and a rebuild from the committed fixtures give the same numbers."""
    out, _ = _build(seeded_cache, "fx")
    a, b = snapshot.open_readonly(SNAP), snapshot.open_readonly(out)
    for sym in SYMS:
        ca, cb = service.results_card(a, sym), service.results_card(b, sym)
        strip = lambda c: [(r["metric"], r["value_cr"], r["qoq"]["pct"], r["yoy"]["pct"], r["source"]["url"], r["source"]["location"])
                           for r in c["rows"]]
        assert strip(ca) == strip(cb), sym
        assert ca["integrity"] == cb["integrity"]


def test_committed_snapshot_verifies():
    ok, msg = snapshot.verify(SNAP)
    assert ok, msg


def test_committed_snapshot_is_small_and_holds_no_documents():
    data = SNAP.read_bytes()
    assert len(data) < 1_000_000
    assert b"%PDF" not in data
    con = snapshot.open_readonly(SNAP)
    longest = con.execute("SELECT MAX(LENGTH(quarter_phrase)), MAX(LENGTH(nse_headline)) FROM transcript_filings").fetchone()
    assert all(v is None or v < 300 for v in longest)
