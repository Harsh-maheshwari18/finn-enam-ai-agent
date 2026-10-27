"""Earnings-call transcript inventory: which quarters exist on NSE, and does each PDF hold up to an audit.

The quarter a transcript covers is read from its own text (e.g. "Q2 FY27", "quarter ended September 30, 2026").
The filing date is only a cross-check, because companies also file transcripts of analyst days and
special calls under the same NSE label (observed: TCS 23-Dec-2025, HDFCBANK 19-Mar-2026).
Only metadata and short evidence phrases leave this module; transcript text is never stored in the snapshot.
"""
from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, timedelta
from typing import Optional

from finn import http, transcripts
from finn.adapters import nse_filings
from finn.models import Filing

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], start=1)}
ORDINAL = {"first": 1, "second": 2, "third": 3, "fourth": 4, "1st": 1, "2nd": 2, "3rd": 3, "4th": 4}


def quarter_end(fq: int, fy: int) -> date:
    """Indian fiscal year: FY27 runs Apr-2026 to Mar-2027, so Q1 FY27 ends 30-Jun-2026."""
    return {1: date(fy - 1, 6, 30), 2: date(fy - 1, 9, 30), 3: date(fy - 1, 12, 31), 4: date(fy, 3, 31)}[fq]


def fiscal_label(period_end: date) -> str:
    fq = {6: 1, 9: 2, 12: 3, 3: 4}[period_end.month]
    fy = period_end.year + (0 if period_end.month == 3 else 1)
    return f"Q{fq} FY{fy % 100:02d}"


def _fy(s: str) -> int:
    n = int(s)
    return n + 2000 if n < 100 else n


def recent_quarter_ends(as_of: date, n: int = 4) -> list[date]:
    """The n most recent quarter ends on or before as_of, newest first."""
    out, d = [], as_of
    while len(out) < n:
        for m, day in ((12, 31), (9, 30), (6, 30), (3, 31)):
            q = date(d.year, m, day)
            if q <= d and (not out or q < out[-1]):
                out.append(q)
                break
        else:
            d = date(d.year - 1, 12, 31)
            continue
        d = out[-1] - timedelta(days=1)
    return out


_BETWEEN = r"(?:\s+and\s+[a-z\s\-]+?)?"      # "quarter and nine -month period ended", "quarter and half year ended"
_PATTERNS = [
    # "Q2 FY27", "Q3FY26", "Q3 FY '26", "Q2 of FY27"
    (re.compile(r"\bQ\s?([1-4])\s?(?:of\s)?(?:FY|F\.Y\.)\s?'?(\d{2,4})\b", re.I),
     lambda m: quarter_end(int(m.group(1)), _fy(m.group(2)))),
    # "second quarter of FY 2027", "third quarter of fiscal year FY2026", "first quarter of financial year 2026-27"
    (re.compile(r"\b(first|second|third|fourth|1st|2nd|3rd|4th)\s+quarter\s+(?:of\s+|for\s+)?(?:the\s+)?"
                r"(?:fiscal\s+year\s+|fiscal\s+|financial\s+year\s+)?(?:FY\s?)?'?(\d{2,4})(?:\s?[-–]\s?(\d{2,4}))?\b", re.I),
     lambda m: quarter_end(ORDINAL[m.group(1).lower()], _fy(m.group(3)) if m.group(3) else _fy(m.group(2)))),
    # "quarter ended September 30, 2026", "quarter ... that ended on December 31st, 2025"
    (re.compile(r"\bquarter" + _BETWEEN + r"\s+(?:[a-z\s]{0,40}?\s)?ended\s+(?:on\s+)?([A-Z][a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", re.I),
     lambda m: _month_end(m.group(1), int(m.group(3)))),
    # "quarter ended 30th September 2026"
    (re.compile(r"\bquarter" + _BETWEEN + r"\s+ended\s+(?:on\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+([A-Z][a-z]+),?\s+(\d{4})", re.I),
     lambda m: _month_end(m.group(2), int(m.group(3)))),
]


def _month_end(month: str, year: int) -> Optional[date]:
    m = MONTHS.get(month.lower())
    ends = {3: 31, 6: 30, 9: 30, 12: 31}
    return date(year, m, ends[m]) if m in ends else None


@dataclass(frozen=True)
class QuarterEvidence:
    period_end: Optional[date]
    phrase: Optional[str]        # the matched words, verbatim from the PDF text
    page: Optional[int]
    votes: dict                  # period_end iso -> count over the pages scanned
    ambiguous: bool


def detect_quarter(pages: list[str], scan_pages: int = 5) -> QuarterEvidence:
    """Vote over every quarter reference on the opening pages. The covering letter and the IR opening
    (pages 1-2) name the call's own quarter; later pages also cite comparison quarters, so they count less.
    A runner-up with at least half the winner's weight marks the result ambiguous rather than guessing."""
    votes: Counter = Counter()
    first: dict[date, tuple[str, int]] = {}
    for pno, page in enumerate(pages[:scan_pages], start=1):
        text = re.sub(r"\s+", " ", transcripts.normalise_glyphs(page))
        weight = 3 if pno <= 2 else 1
        for rx, to_date in _PATTERNS:
            for m in rx.finditer(text):
                try:
                    d = to_date(m)
                except (KeyError, ValueError):
                    continue
                if d is None:
                    continue
                votes[d] += weight
                first.setdefault(d, (m.group(0), pno))
    if not votes:
        return QuarterEvidence(None, None, None, {}, False)
    ranked = votes.most_common()
    best, n = ranked[0]
    ambiguous = len(ranked) > 1 and ranked[1][1] * 2 >= n
    return QuarterEvidence(best, first[best][0], first[best][1], {d.isoformat(): c for d, c in ranked}, ambiguous)


def quarter_by_filing_date(broadcast: date) -> date:
    """Cross-check only: the latest quarter that ended at least 7 days before the transcript was filed."""
    return recent_quarter_ends(broadcast - timedelta(days=7), 1)[0]


@dataclass
class TranscriptAudit:
    symbol: str
    seq_id: str
    broadcast_at: str
    url: Optional[str]
    nse_headline: str
    status: str                          # ok | unreadable | unavailable
    reason: Optional[str] = None
    sha256: Optional[str] = None
    bytes: Optional[int] = None
    pages: Optional[int] = None
    text_chars: Optional[int] = None
    scanned: Optional[bool] = None
    speaker_turns: Optional[int] = None
    management_named: Optional[int] = None
    is_earnings_call: Optional[bool] = None
    period_end: Optional[str] = None     # from the text
    fiscal_quarter: Optional[str] = None
    quarter_phrase: Optional[str] = None
    quarter_page: Optional[int] = None
    quarter_ambiguous: Optional[bool] = None
    quarter_votes: dict = field(default_factory=dict)
    filing_date_quarter: Optional[str] = None
    date_agrees: Optional[bool] = None
    retrieved_at: Optional[str] = None
    provenance: Optional[str] = None


def _is_earnings_call(pages: list[str]) -> bool:
    head = transcripts.normalise(" ".join(pages[:2]))
    return bool(re.search(r"(earnings|results|quarterly|financial results)\W+(conference\s+)?call|earnings conference", head))


def audit_filing(f: Filing, *, offline: bool = False) -> TranscriptAudit:
    a = TranscriptAudit(f.symbol, f.seq_id, f.broadcast_at.isoformat(), f.attachment_url, f.headline, "unavailable")
    a.filing_date_quarter = quarter_by_filing_date(f.broadcast_at.date()).isoformat()
    if not f.attachment_url:
        a.reason = "filing has no attachment"
        return a
    r = http.fetch(f.attachment_url, offline=offline)       # filed PDFs are immutable: any cached copy is valid
    if not r.ok:
        a.reason = r.reason
        return a
    a.sha256, a.bytes, a.retrieved_at = r.sha256, len(r.body), r.fetched_at.isoformat()
    a.provenance = "cached" if r.from_cache else "live"
    try:
        pages = transcripts.pdf_pages(io.BytesIO(r.body))
    except Exception as e:                                   # not a PDF, truncated, encrypted
        a.status, a.reason = "unreadable", f"PDF could not be parsed: {type(e).__name__}"
        return a
    a.pages, a.text_chars = len(pages), sum(len(p) for p in pages)
    a.scanned = transcripts.looks_scanned(pages)
    if a.scanned:
        a.status, a.reason = "unreadable", "no text layer on most pages (scanned); OCR is out of scope"
        return a
    a.speaker_turns = len(transcripts.speaker_turns(pages))
    a.management_named = len(transcripts.management_names(pages))
    a.is_earnings_call = _is_earnings_call(pages)
    q = detect_quarter(pages)
    if q.period_end:
        a.period_end, a.fiscal_quarter = q.period_end.isoformat(), fiscal_label(q.period_end)
        a.quarter_phrase, a.quarter_page, a.quarter_ambiguous, a.quarter_votes = q.phrase, q.page, q.ambiguous, q.votes
        a.date_agrees = a.period_end == a.filing_date_quarter
    a.status = "ok"
    return a


def find_transcript_filings(symbol: str, start: date, end: date, *, offline: bool = False,
                            window_days: int = 90) -> tuple[list[Filing], list[str]]:
    """NSE announcements in windows of <= window_days (the 60-90 day windows used in testing all returned 200)."""
    found: dict[str, Filing] = {}
    problems = []
    s = start
    while s <= end:
        e = min(s + timedelta(days=window_days - 1), end)
        url = nse_filings.ANN_URL.format(symbol=symbol, start=s, end=e)
        r = http.fetch(url, offline=offline, max_age_s=12 * 3600)
        if not r.ok:
            problems.append(f"announcements {s}..{e}: {r.reason}")
        else:
            for fl in nse_filings.parse_announcements(r.body, fetched_at=r.fetched_at, url=url, sha=r.sha256,
                                                      provenance="cached" if r.from_cache else "live"):
                if nse_filings.is_transcript(fl):
                    found[fl.seq_id] = fl
        s = e + timedelta(days=1)
    return sorted(found.values(), key=lambda f: f.broadcast_at), problems


def coverage(symbol: str, as_of: date, *, quarters: int = 4, offline: bool = False) -> dict:
    """Up to `quarters` most recent quarters, each matched to an audited earnings-call transcript or marked missing."""
    targets = recent_quarter_ends(as_of, quarters)
    # Calls for the oldest target happen weeks after it ends; search from its quarter end onwards.
    filings, problems = find_transcript_filings(symbol, targets[-1], as_of, offline=offline)
    audits = [audit_filing(f, offline=offline) for f in filings]
    used: set[str] = set()
    rows = []
    for q in targets:
        hits = [a for a in audits if a.status == "ok" and a.is_earnings_call and a.period_end == q.isoformat()]
        if hits:
            best = hits[-1]                                  # latest filing wins if a corrected copy was re-filed
            used.update(a.seq_id for a in hits)
            rows.append({"period_end": q.isoformat(), "fiscal_quarter": fiscal_label(q), "status": "available",
                         "seq_id": best.seq_id, "duplicates": [a.seq_id for a in hits[:-1]]})
            continue
        bad = [a for a in audits if a.status != "ok" and a.filing_date_quarter == q.isoformat()]
        if bad:
            rows.append({"period_end": q.isoformat(), "fiscal_quarter": fiscal_label(q), "status": "unreadable",
                         "seq_id": bad[-1].seq_id, "reason": bad[-1].reason})
            used.add(bad[-1].seq_id)
            continue
        reason = (f"no earnings-call transcript filed on NSE between {targets[-1]} and {as_of} names this quarter"
                  if not problems else f"not found; announcement search incomplete: {'; '.join(problems)}")
        rows.append({"period_end": q.isoformat(), "fiscal_quarter": fiscal_label(q), "status": "missing", "reason": reason})
    other = [a.seq_id for a in audits if a.seq_id not in used]
    return {"symbol": symbol, "as_of": as_of.isoformat(), "searched_from": targets[-1].isoformat(),
            "quarters": rows, "other_transcripts": other, "search_problems": problems,
            "audits": [asdict(a) for a in audits]}
