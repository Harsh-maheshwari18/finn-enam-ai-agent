"""Price + announcement adapters, classifier, HTTP failure behaviour."""
import io
import json
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from finn import http
from finn.adapters import nse_filings, prices
from finn.classify import classify

FIX = Path(__file__).parent / "fixtures" / "real"
IST = timezone(timedelta(hours=5, minutes=30))


# ---------- prices ----------

def real_bars(fetched_at):
    return prices.parse_chart((FIX / "yahoo_TCS.NS_excerpt.json").read_bytes(), fetched_at=fetched_at,
                              url="fixture", sha=None, provenance="fixture")


def test_real_excerpt_parses():
    bars = real_bars(datetime(2026, 10, 28, 9, 0, tzinfo=IST))
    assert len(bars) == 30 and bars[-1].day.isoformat() == "2026-10-27"
    assert all(b.close > 0 for b in bars) and len({b.day for b in bars}) == 30


def test_intraday_bar_marked_provisional_and_excluded():
    """The fixture was captured at 11:41 IST on 27-Oct: its last bar is a live session."""
    bars = real_bars(datetime(2026, 10, 27, 11, 41, tzinfo=IST))
    assert bars[-1].provisional and not bars[-2].provisional
    sig = prices.eod_signals(bars)
    assert sig["day"].isoformat() == "2026-10-26" and sig["provisional_bar_excluded"]


def synth(closes, vols, start=datetime(2026, 9, 1, 9, 15, tzinfo=IST)):
    """SYNTHETIC series for edge cases, never shown as market data."""
    ts = [int((start + timedelta(days=i)).timestamp()) for i in range(len(closes))]
    return json.dumps({"chart": {"result": [{"meta": {"symbol": "SYN.NS", "currency": "INR"}, "timestamp": ts,
             "indicators": {"quote": [{"open": closes, "high": closes, "low": closes, "close": closes, "volume": vols}]}}],
             "error": None}}).encode()


def parse_synth(closes, vols):
    return prices.parse_chart(synth(closes, vols), fetched_at=datetime(2026, 12, 1, tzinfo=IST), url="synthetic://",
                              sha=None, provenance="fixture")


def test_null_close_skipped_and_zero_volume_flagged():
    bars = parse_synth([100, None, 101, 102], [10, 10, 0, 10])
    assert len(bars) == 3 and bars[1].volume_suspect and not bars[0].volume_suspect


def test_volume_threshold_boundary():
    base = [100] * 21
    at = prices.eod_signals(parse_synth(base, [1000] * 20 + [2000]))
    below = prices.eod_signals(parse_synth(base, [1000] * 20 + [1990]))
    assert prices.check_alerts(at) == ["volume_spike"] and prices.check_alerts(below) == []


def test_zero_volume_excluded_from_average():
    sig = prices.eod_signals(parse_synth([100] * 21, [1000] * 10 + [0] * 10 + [2000]))
    assert sig["lookback_used"] == 10 and sig["avg_volume"] == 1000


def test_price_move_threshold_configurable():
    sig = prices.eod_signals(parse_synth([100] * 20 + [104], [1000] * 21))
    assert prices.check_alerts(sig) == [] and prices.check_alerts(sig, move_pct=4.0) == ["price_move"]


def test_insufficient_history_gives_no_volume_ratio():
    sig = prices.eod_signals(parse_synth([100, 101, 102], [1, 1, 5]))
    assert sig["volume_ratio"] is None


@pytest.mark.parametrize("body", [b"<html>", b'{"chart":{"result":null,"error":{"code":"Not Found"}}}', b'{"chart":{"result":[]}}'])
def test_bad_price_payloads_raise_typed_error(body):
    with pytest.raises(prices.PriceParseError):
        prices.parse_chart(body, fetched_at=datetime.now(timezone.utc), url="x", sha=None, provenance="fixture")


# ---------- announcements ----------

def filings(sym):
    return nse_filings.parse_announcements((FIX / f"nse_ann_{sym}.json").read_bytes(),
                                           fetched_at=datetime.now(timezone.utc), url="fixture", sha=None, provenance="fixture")


def test_real_announcements_have_required_fields():
    for sym in ("TCS", "HDFCBANK", "POLYCAB"):
        for f in filings(sym):
            assert f.seq_id and f.symbol == sym and f.isin and f.broadcast_at and f.nse_desc
            assert f.attachment_url is None or f.attachment_url.startswith("https://")


def test_duplicate_attachment_collapsed():
    rows = json.loads((FIX / "nse_ann_TCS.json").read_text())
    dup = dict(rows[0], seq_id="999999999", an_dt="20-Oct-2026 09:00:00")
    out = nse_filings.parse_announcements(json.dumps(rows + [dup]).encode(), fetched_at=datetime.now(timezone.utc),
                                          url="x", sha=None, provenance="fixture")
    assert len(out) == len(rows) and "999999999" not in {f.seq_id for f in out}


@pytest.mark.parametrize("sym,needle,category", [
    ("TCS", "completion of acquisition", "M&A"),                      # filed under "General Updates"
    ("POLYCAB", "NCLT order", "litigation"),                          # filed under "General Updates"
    ("POLYCAB", "Corporate Insolvency", "litigation"),
    ("HDFCBANK", "change in Management", "management_change"),
    ("TCS", "financial results for the period ended September 30, 2026", "results"),
    ("TCS", "about Transcript", "earnings_call"),
    ("HDFCBANK", "Grant of stock options", "unclassified"),
])
def test_classifier_on_real_filings(sym, needle, category):
    f = next(f for f in filings(sym) if needle in f.headline)
    assert classify(f).category == category


def test_unresolved_is_not_guessed():
    f = next(f for f in filings("HDFCBANK") if f.headline.endswith("about General Updates"))
    c = classify(f)
    assert c.category is None and c.method == "unresolved"


def test_transcript_detection():
    assert sum(nse_filings.is_transcript(f) for f in filings("POLYCAB")) == 1


# ---------- http failure behaviour ----------

@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("FINN_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(http, "MIN_INTERVAL", {})
    return tmp_path


def test_offline_cache_miss_is_reported(cache):
    f = http.fetch("https://example.invalid/x", offline=True)
    assert not f.ok and "offline" in f.reason


def test_403_not_retried_and_reported(cache, monkeypatch):
    calls = []

    def deny(req, timeout):
        calls.append(req.full_url)
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b""))
    monkeypatch.setattr(http.urllib.request, "urlopen", deny)
    f = http.fetch("https://www.nseindia.com/api/x")
    assert (f.ok, f.status, len(calls)) == (False, 403, 1)


def test_stale_cache_served_when_live_fails(cache, monkeypatch):
    url = "https://www.nseindia.com/api/y"
    http._write_cache(http.Fetched(True, url, 200, b"old", datetime(2026, 10, 1, tzinfo=timezone.utc), False, None))

    def boom(req, timeout):
        raise urllib.error.HTTPError(url, 429, "Too Many", {}, io.BytesIO(b""))
    monkeypatch.setattr(http.urllib.request, "urlopen", boom)
    f = http.fetch(url, max_age_s=60)
    assert f.ok and f.from_cache and f.body == b"old" and "HTTP 429" in f.reason and "2026-10-01" in f.reason
