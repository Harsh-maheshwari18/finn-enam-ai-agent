"""NSE timestamps are naive IST on the wire; FINN must attach +05:30 without shifting the wall clock,
and must leave already-aware values alone. Fixture rows are real NSE responses retrieved 2026-10-27."""
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from finn import store, tz
from finn.adapters import nse_filings, nse_results
from finn.models import Observation, SourceRef

FIX = Path(__file__).parent / "fixtures" / "real"
UTC = timezone.utc
IST_OFFSET = timedelta(hours=5, minutes=30)


def test_naive_value_keeps_wall_clock_and_gains_ist_offset():
    got = tz.as_ist(datetime(2026, 10, 23, 22, 50, 22))
    assert got.isoformat() == "2026-10-23T22:50:22+05:30"
    assert got.utcoffset() == IST_OFFSET


def test_aware_utc_value_is_not_converted_again():
    utc = datetime(2026, 10, 23, 17, 20, 22, tzinfo=UTC)          # the same instant as 22:50:22 IST
    got = tz.as_ist(utc)
    assert got is utc and got.isoformat() == "2026-10-23T17:20:22+00:00"
    assert got == tz.as_ist(datetime(2026, 10, 23, 22, 50, 22))   # equal instants, no extra 5h30 shift


def test_aware_ist_value_is_unchanged():
    ist = datetime(2026, 10, 8, 22, 7, 33, tzinfo=timezone(IST_OFFSET))
    assert tz.as_ist(ist) is ist


def test_none_passes_through():
    assert tz.as_ist(None) is None and tz.parse_nse("", "%d-%b-%Y") is None


def test_announcement_broadcast_at_and_published_at_are_ist():
    """Real row: an_dt '23-Oct-2026 22:50:22'; its covering letter is dated October 23, 2026."""
    body = (FIX / "nse_ann_HDFCBANK.json").read_bytes()
    rows = nse_filings.parse_announcements(body, fetched_at=datetime(2026, 10, 27, 6, tzinfo=UTC), url="u", sha=None,
                                           provenance="fixture")
    f = next(r for r in rows if "23102026224657" in (r.attachment_url or ""))
    assert f.broadcast_at.isoformat() == "2026-10-23T22:50:22+05:30"
    assert f.source.published_at.isoformat() == "2026-10-23T22:50:22+05:30"
    assert all(r.broadcast_at.utcoffset() == IST_OFFSET for r in rows)


def test_results_listing_published_at_is_ist():
    """Real row: broadcast_Date '08-Oct-2026 22:07:33' for TCS consolidated Q2 FY27."""
    refs = nse_results.parse_listing((FIX / "nse_int_TCS.json").read_bytes(), "TCS")
    ref = next(r for r in refs if r.period_end == date(2026, 9, 30) and r.basis == "consolidated")
    assert ref.broadcast_at.isoformat() == "2026-10-08T22:07:33+05:30"
    src = nse_results.source_for(ref, datetime(2026, 10, 27, 6, tzinfo=UTC), None, "fixture")
    assert src.published_at.isoformat() == "2026-10-08T22:07:33+05:30"
    assert src.retrieved_at.isoformat() == "2026-10-27T06:00:00+00:00"   # our own clock stays UTC


def test_unrecognised_announcement_timestamp_raises():
    body = json.dumps([{"seq_id": "1", "an_dt": "yesterday", "symbol": "X"}]).encode()
    with pytest.raises(ValueError, match="unrecognised NSE timestamp"):
        nse_filings.parse_announcements(body, fetched_at=datetime.now(UTC), url="u", sha=None, provenance="fixture")


def _obs(published_at):
    src = SourceRef("xbrl_result", "https://example.invalid/x.xml", datetime(2026, 10, 27, 6, tzinfo=UTC), "h",
                    "fixture", published_at=published_at, location="context OneD / Revenue")
    return Observation(symbol="X", metric="revenue", value=Decimal("1"), period_start=date(2026, 7, 1),
                       period_end=date(2026, 9, 30), basis="consolidated", status="extracted", source=src)


def test_store_round_trip_preserves_offset():
    con = store.connect(":memory:")
    store.put_observations(con, [_obs(tz.as_ist(datetime(2026, 10, 8, 22, 7, 33)))], "indas")
    o = store.row_to_observation(store.get_observations(con, "X")[0])
    assert o.source.published_at.isoformat() == "2026-10-08T22:07:33+05:30"


def test_legacy_naive_row_is_read_as_ist():
    """Databases written before the fix stored NSE times without an offset."""
    con = store.connect(":memory:")
    store.put_observations(con, [_obs(datetime(2026, 10, 8, 22, 7, 33))], "indas")
    assert con.execute("SELECT published_at FROM sources").fetchone()[0] == "2026-10-08T22:07:33"
    o = store.row_to_observation(store.get_observations(con, "X")[0])
    assert o.source.published_at.isoformat() == "2026-10-08T22:07:33+05:30"
