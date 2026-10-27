"""Signal Inbox ranking rules (finn/signals.py).

SYNTHETIC FIXTURES: the filings and price bars built in this file are invented to pin the rules exactly
(window edges, thresholds, insufficient history). They are not real observations and are never written to the
snapshot. Behaviour on real data is tested against the committed snapshot in tests/test_api.py.
"""
import json
from datetime import date, datetime, timedelta, timezone

import pytest

from finn import signals, snapshot, store, tz
from finn.models import Filing, PriceBar, SourceRef

UTC = timezone.utc
END = datetime(2026, 10, 27, 10, 0, tzinfo=UTC)          # 15:30 IST
SYN = "https://example.invalid/synthetic"


def _src(doc_type="announcement", url=SYN + "/ann"):
    return SourceRef(doc_type, url, END, "synthetic-hash", "fixture")


def _filing(seq, sym, desc, headline, at_ist):
    return Filing(seq_id=seq, symbol=sym, isin=None, company=f"{sym} Synthetic Ltd", nse_desc=desc, headline=headline,
                  broadcast_at=at_ist, attachment_url=f"{SYN}/{seq}.pdf", attachment_size=None, has_xbrl=False,
                  source=_src())


def _bars(sym, closes, volumes, last_day=date(2026, 10, 27)):
    days = [last_day - timedelta(days=len(closes) - 1 - i) for i in range(len(closes))]
    src = _src("price_feed", SYN + "/prices")
    return [PriceBar(sym, d, c, c, c, c, v, False, v == 0, src) for d, c, v in zip(days, closes, volumes)]


@pytest.fixture
def con():
    c = store.connect(":memory:")
    c.executescript(snapshot.EXTRA_SCHEMA)
    meta = {"announcements_retrieved_at": END.isoformat(), "prices_retrieved_at": END.isoformat(), "as_of": "2026-10-27",
            "portfolio": json.dumps(["AAA", "BBB"]), "symbols": json.dumps(["AAA", "BBB", "CCC"])}
    c.executemany("INSERT INTO snapshot_meta VALUES (?,?)", list(meta.items()))
    for s in ("AAA", "BBB", "CCC"):
        c.execute("INSERT INTO companies (symbol, groups, status, validation, golden_checked, integrity, name) "
                  "VALUES (?,?,?,?,?,?,?)", (s, "[]", "ok", "integrity_checked", 0, "[]", f"{s} Synthetic Ltd"))
    ist = lambda *a: datetime(*a, tzinfo=tz.IST)
    rows = [
        ("1", "AAA", "Change in Management", "Appointment of CFO", ist(2026, 10, 27, 12, 0)),      # in 24h
        ("2", "AAA", "Copy of Newspaper Publication", "Newspaper ad", ist(2026, 10, 27, 11, 0)),     # routine
        ("3", "BBB", "General Updates", "General Updates", ist(2026, 10, 26, 16, 0)),                # unresolved
        ("4", "BBB", "Credit Rating", "Rating reaffirmed", ist(2026, 10, 22, 9, 0)),                 # 7d only
        ("5", "BBB", "Credit Rating", "Rating reaffirmed again", ist(2026, 10, 2, 9, 0)),            # 30d only
        ("6", "CCC", "Acquisition", "Acquires a stake", ist(2026, 10, 27, 9, 0)),                    # not in portfolio
    ]
    for seq, sym, desc, head, at in rows:
        f = _filing(seq, sym, desc, head, at)
        from finn.classify import classify
        k = classify(f)
        store.put_filing(c, f, k.category, k.method)
    # AAA: flat for 25 sessions, then +6% on the last session with 3x volume. BBB: only 4 sessions (too short).
    store.put_price_bars(c, "AAA", _bars("AAA.NS", [100.0] * 25 + [106.0], [1000] * 25 + [3000]))
    store.put_price_bars(c, "BBB", _bars("BBB.NS", [50.0, 50.5, 51.0, 51.5], [10, 10, 10, 10]))
    c.commit()
    return c


def ids(r):
    return {s["id"] for s in r["signals"]}


def test_window_is_anchored_to_snapshot_not_viewer_clock(con):
    r = signals.inbox(con, signals.parse_settings({}))
    assert r["window"]["end"] == "2026-10-27T15:30:00+05:30" and r["window"]["hours"] == 24


def test_24h_window_ranks_material_and_folds_routine(con):
    r = signals.inbox(con, signals.parse_settings({"window": "24h"}))
    assert "ann-1" in ids(r) and "ann-3" in ids(r)
    assert [f["id"] for f in r["folded"]] == ["ann-2"]
    assert "ann-4" not in ids(r)
    assert "ann-6" not in ids(r), "companies outside the portfolio stay out of the inbox"


def test_wider_windows_add_older_records(con):
    assert "ann-4" in ids(signals.inbox(con, signals.parse_settings({"window": "7d"})))
    assert "ann-5" in ids(signals.inbox(con, signals.parse_settings({"window": "30d"})))
    assert "ann-5" not in ids(signals.inbox(con, signals.parse_settings({"window": "7d"})))


def test_score_is_sum_of_explained_parts_and_order_is_by_score(con):
    r = signals.inbox(con, signals.parse_settings({"window": "24h"}))
    for s in r["signals"]:
        assert s["score"] == sum(p["points"] for p in s["score_parts"]) and all(p["why"] for p in s["score_parts"])
    scores = [s["score"] for s in r["signals"]]
    assert scores == sorted(scores, reverse=True)


def test_unresolved_category_is_not_guessed(con):
    s = next(x for x in signals.inbox(con, signals.parse_settings({"window": "24h"}))["signals"] if x["id"] == "ann-3")
    assert s["category"] == "needs_review" and s["priority"] == "low" and "unresolved" in s["unknowns"][0].lower()


def test_price_and_volume_thresholds_fire_and_are_configurable(con):
    r = signals.inbox(con, signals.parse_settings({"window": "24h"}))
    kinds = {s["category"] for s in r["signals"] if s["symbol"] == "AAA" and s["kind"] == "price"}
    assert kinds == {"price_move", "volume_spike"}
    pm = next(s for s in r["signals"] if s["category"] == "price_move")
    assert pm["stats"]["move_pct"] == 6.0 and "100.00" in pm["calculation"]
    strict = signals.inbox(con, signals.parse_settings({"window": "24h", "move_pct": "7", "volume_x": "3.5"}))
    assert not [s for s in strict["signals"] if s["kind"] == "price"]


def test_volume_ratio_needs_history_and_says_so(con):
    r = signals.inbox(con, signals.parse_settings({"window": "24h", "move_pct": "0.5"}))
    bbb = next(c for c in r["price_coverage"] if c["symbol"] == "BBB")
    assert bbb["volume_evaluable"] is False and "prior sessions" in bbb["reason"]
    assert not [s for s in r["signals"] if s["symbol"] == "BBB" and s["category"] == "volume_spike"]
    assert [s for s in r["signals"] if s["symbol"] == "BBB" and s["category"] == "price_move"], "price rule still works"


def test_lookback_changes_the_average(con):
    short = signals.inbox(con, signals.parse_settings({"window": "24h", "lookback": "5"}))
    vs = next(s for s in short["signals"] if s["category"] == "volume_spike")
    assert vs["stats"]["lookback_used"] == 5


def test_mute_hides_and_counts_watch_adds_points(con):
    base = signals.inbox(con, signals.parse_settings({"window": "24h"}))
    muted = signals.inbox(con, signals.parse_settings({"window": "24h", "mute": "management_change,price_move"}))
    assert "ann-1" not in ids(muted) and muted["counts"]["muted"] == 2
    watched = signals.inbox(con, signals.parse_settings({"window": "24h", "watch": "needs_review"}))
    a = next(s for s in base["signals"] if s["id"] == "ann-3")
    b = next(s for s in watched["signals"] if s["id"] == "ann-3")
    assert b["score"] == a["score"] + signals.WATCH_POINTS


def test_symbols_override_and_unknown_symbol_rejected(con):
    r = signals.inbox(con, signals.parse_settings({"window": "24h", "symbols": "ccc"}))
    assert ids(r) == {"ann-6"}
    with pytest.raises(ValueError, match="not in the snapshot"):
        signals.inbox(con, signals.parse_settings({"symbols": "ZZZ"}))


@pytest.mark.parametrize("q, msg", [({"window": "1y"}, "window"), ({"move_pct": "abc"}, "number"),
                                    ({"volume_x": "0.5"}, "between"), ({"lookback": "500"}, "between"),
                                    ({"mute": "everything"}, "unknown category")])
def test_bad_settings_rejected(q, msg):
    with pytest.raises(ValueError, match=msg):
        signals.parse_settings(q)


def test_provisional_bar_never_stored(monkeypatch):
    """ingest_prices drops a bar whose session had not closed when fetched (real fixture, fetched 11:41 IST)."""
    from pathlib import Path
    from finn import http, service
    body = (Path(__file__).parent / "fixtures" / "real" / "yahoo_TCS.NS_excerpt.json").read_bytes()
    fetched = datetime(2026, 10, 27, 6, 11, tzinfo=UTC)
    monkeypatch.setattr(http, "fetch", lambda *a, **k: http.Fetched(True, "u", 200, body, fetched, False, "h"))
    c = store.connect(":memory:")
    assert service.ingest_prices(c, "TCS") == []
    days = [r[0] for r in c.execute("SELECT day FROM price_bars ORDER BY day")]
    assert days and "2026-10-27" not in days
