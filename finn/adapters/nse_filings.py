"""NSE corporate announcements (api/corporate-announcements). Verified reachable 2026-10-27."""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Optional

from finn import tz
from finn.models import Filing, SourceRef

ANN_URL = ("https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={symbol}"
           "&from_date={start:%d-%m-%Y}&to_date={end:%d-%m-%Y}")
ANNUAL_REPORTS_URL = "https://www.nseindia.com/api/annual-reports?index=equities&symbol={symbol}"


def parse_announcements(body: bytes, *, fetched_at: datetime, url: str, sha: Optional[str],
                        provenance: str) -> list[Filing]:
    rows = json.loads(body)
    if isinstance(rows, dict):          # NSE sometimes wraps lists; be tolerant, not silent
        rows = rows.get("data", [])
    seen: dict[str, Filing] = {}
    for x in rows:
        seq = str(x.get("seq_id") or "")
        at = x.get("an_dt") or x.get("sort_date")
        if not seq or not at:
            continue
        when = tz.parse_nse(at, "%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S")   # naive IST on the wire
        if when is None:
            raise ValueError(f"unrecognised NSE timestamp {at!r} (seq_id {seq})")
        att = x.get("attchmntFile") or None
        f = Filing(
            seq_id=seq, symbol=x.get("symbol", ""), isin=x.get("sm_isin"), company=x.get("sm_name", ""),
            nse_desc=(x.get("desc") or "").strip(), headline=(x.get("attchmntText") or "").strip(),
            broadcast_at=when, attachment_url=att, attachment_size=x.get("attFileSize"),
            has_xbrl=str(x.get("hasXbrl")).lower() == "true",
            source=SourceRef(doc_type="announcement", url=url, retrieved_at=fetched_at, content_hash=sha,
                             provenance=provenance, title=x.get("desc"), published_at=when),
        )
        seen[seq] = f
    # NSE re-broadcasts occasionally carry a new seq_id but the same attachment: keep the earliest.
    by_att: dict[str, Filing] = {}
    for f in sorted(seen.values(), key=lambda f: f.broadcast_at):
        key = f.attachment_url or f"seq:{f.seq_id}"
        by_att.setdefault(key, f)
    return sorted(by_att.values(), key=lambda f: f.broadcast_at, reverse=True)


def is_transcript(f: Filing) -> bool:
    return f.nse_desc.startswith("Analysts/Institutional Investor Meet") and "transcript" in f.headline.lower()


def parse_annual_reports(body: bytes) -> list[dict]:
    d = json.loads(body)
    rows = d.get("data", d) if isinstance(d, dict) else d
    return [{"from_year": r.get("fromYr"), "to_year": r.get("toYr"), "url": r.get("fileName"),
             "broadcast": r.get("broadcast_dttm")} for r in rows if r.get("fileName")]
