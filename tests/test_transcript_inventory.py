"""Transcript quarter detection and coverage matching.

The phrases below are REAL excerpts from NSE-filed transcripts retrieved 2026-10-27 (source noted per case);
the surrounding page strings are synthetic scaffolding. The first three broke the initial detector.
"""
from datetime import date, datetime

import pytest

from finn import transcript_inventory as ti
from finn.models import Filing, SourceRef


@pytest.mark.parametrize("text,expected", [
    # TCS 16-Jan-2026 covering letter: hyphen spacing inside "nine -month"
    ("Sub: Transcript of the earnings conference call for the quarter and nine -month period ended December 31, 2025", date(2025, 12, 31)),
    # TCS 16-Jan-2026 IR opening: "fiscal year" and "FY" together, ordinal day
    ("financial results for the third quarter of ﬁscal year FY2026 that ended on December 31st, 2025", date(2025, 12, 31)),
    # TCS 14-Oct-2026
    ("results for the second quarter of FY 2027", date(2026, 9, 30)),
    # HDFCBANK 23-Oct-2026
    ("quarter and half-year ended September 30, 2026", date(2026, 9, 30)),
    # HDFCBANK 23-Jan-2026
    ("Q3 FY '26", date(2025, 12, 31)),
    # POLYCAB 20-Jul-2026
    ("Q1 FY27", date(2026, 6, 30)),
    # TCS 14-Apr-2026
    ("quarter and year ended March 31, 2026", date(2026, 3, 31)),
])
def test_detects_quarter_from_real_phrasing(text, expected):
    q = ti.detect_quarter([text])
    assert q.period_end == expected and q.page == 1 and not q.ambiguous


def test_opening_pages_outweigh_later_comparisons():
    # TCS 16-Jan-2026: page 3 cites the previous quarter ("Q2FY26") before the Q3 references appear
    pages = ["quarter and nine -month period ended December 31, 2025", "third quarter of fiscal year FY2026", "compared with Q2FY26"]
    q = ti.detect_quarter(pages)
    assert q.period_end == date(2025, 12, 31) and not q.ambiguous


def test_conflicting_references_are_ambiguous():
    q = ti.detect_quarter(["Q2 FY27 and Q1 FY27"])
    assert q.ambiguous


def test_no_quarter_reference():
    # HDFCBANK 19-Mar-2026 investor call: no quarter is named
    q = ti.detect_quarter(["Transcript of Analyst/ investor call in relation to the intimation made by HDFC Bank Limited"])
    assert q.period_end is None


def test_fiscal_calendar():
    assert ti.quarter_end(1, 2027) == date(2026, 6, 30) and ti.quarter_end(4, 2026) == date(2026, 3, 31)
    assert ti.fiscal_label(date(2026, 9, 30)) == "Q2 FY27" and ti.fiscal_label(date(2026, 3, 31)) == "Q4 FY26"
    assert ti.recent_quarter_ends(date(2026, 10, 27)) == [date(2026, 9, 30), date(2026, 6, 30), date(2026, 3, 31), date(2025, 12, 31)]
    assert ti.recent_quarter_ends(date(2026, 9, 30), 2) == [date(2026, 9, 30), date(2026, 6, 30)]
    assert ti.quarter_by_filing_date(date(2026, 10, 14)) == date(2026, 9, 30)
    assert ti.quarter_by_filing_date(date(2026, 10, 3)) == date(2026, 6, 30)


def _filing(seq, day):
    when = datetime.fromisoformat(day)
    return Filing(seq, "X", None, "X", "Analysts/Institutional Investor Meet/Con. Call Updates", "Transcript", when,
                  f"https://example.invalid/{seq}.pdf", None, False, SourceRef("announcement", None, when, None, "fixture"))


def test_coverage_marks_missing_and_other(monkeypatch):
    fs = [_filing("a", "2026-10-14T16:00:00"), _filing("b", "2026-07-15T19:00:00"), _filing("c", "2026-03-19T22:00:00")]
    monkeypatch.setattr(ti, "find_transcript_filings", lambda *a, **k: (fs, []))

    def fake_audit(f, offline=False):
        a = ti.TranscriptAudit("X", f.seq_id, f.broadcast_at.isoformat(), f.attachment_url, f.headline, "ok")
        a.is_earnings_call = f.seq_id != "c"
        a.period_end = {"a": "2026-09-30", "b": "2026-06-30"}.get(f.seq_id)
        a.filing_date_quarter = ti.quarter_by_filing_date(f.broadcast_at.date()).isoformat()
        return a
    monkeypatch.setattr(ti, "audit_filing", fake_audit)
    c = ti.coverage("X", date(2026, 10, 27))
    st = {r["fiscal_quarter"]: r["status"] for r in c["quarters"]}
    assert st == {"Q2 FY27": "available", "Q1 FY27": "available", "Q4 FY26": "missing", "Q3 FY26": "missing"}
    assert all(r["reason"] for r in c["quarters"] if r["status"] == "missing")
    assert c["other_transcripts"] == ["c"]


def test_search_failure_is_not_reported_as_absence(monkeypatch):
    monkeypatch.setattr(ti, "find_transcript_filings", lambda *a, **k: ([], ["announcements 2026-01-01..2026-03-31: HTTP 403"]))
    c = ti.coverage("X", date(2026, 10, 27))
    assert all(r["status"] == "missing" and "search incomplete" in r["reason"] for r in c["quarters"])
