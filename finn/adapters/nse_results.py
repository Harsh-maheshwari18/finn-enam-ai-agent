"""NSE integrated-filing results: listing + XBRL instance parsing.

Endpoint verified 2026-10-27: api/integrated-filing-results returns, per quarter and basis,
an XBRL XML (machine-readable) and an iXBRL HTML rendering. Values in the XML are absolute
INR; `LevelOfRounding` only describes how the company presented the PDF.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from finn.models import ResultFilingRef, SourceRef

LIST_URL = ("https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol={symbol}"
            "&period_ended=all&type=Integrated%20Filing-%20Financials")

XBRLI = "{http://www.xbrl.org/2003/instance}"


def _d(s: str, fmt: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s.strip(), fmt)
    except (ValueError, AttributeError):
        return None


def parse_listing(body: bytes, symbol: str) -> list[ResultFilingRef]:
    data = json.loads(body).get("data", [])
    out = []
    for x in data:
        pe = _d(x.get("qe_Date", ""), "%d-%b-%Y")
        if not pe:
            continue
        url = x.get("xbrl") or ""
        tax = "banking" if "_BANKING_" in url else "indas" if "_INDAS_" in url else "other"
        out.append(ResultFilingRef(
            symbol=symbol,
            period_end=pe.date(),
            basis="consolidated" if x.get("consolidated", "").lower().startswith("consol") else "standalone",
            audited=x.get("audited", "").lower() == "audited",
            taxonomy=tax,
            broadcast_at=_d(x.get("broadcast_Date", ""), "%d-%b-%Y %H:%M:%S"),
            xbrl_url=url if url.endswith(".xml") else None,
            html_url=x.get("ixbrl"),
            seq_id=str(x.get("seq_Id")) if x.get("seq_Id") else None,
            revised=bool(x.get("revised_Date")),
        ))
    out.sort(key=lambda r: (r.period_end, r.basis), reverse=True)
    return out


def parse_instance(body: bytes) -> dict:
    """Parse an XBRL instance into {"contexts": {id: {...}}, "facts": {(local_name, ctx): Decimal|str}}.

    Only non-dimensional facts are kept: dimensional contexts (segments, expense breakdowns)
    are never mixed into headline metrics.
    """
    root = ET.fromstring(body)
    contexts = {}
    for c in root.iter(f"{XBRLI}context"):
        cid = c.get("id")
        period = c.find(f"{XBRLI}period")
        start = period.findtext(f"{XBRLI}startDate")
        end = period.findtext(f"{XBRLI}endDate")
        instant = period.findtext(f"{XBRLI}instant")
        has_dims = c.find(f"{XBRLI}entity/{XBRLI}segment") is not None or c.find(f"{XBRLI}scenario") is not None
        contexts[cid] = {
            "start": date.fromisoformat(start) if start else None,
            "end": date.fromisoformat(end) if end else (date.fromisoformat(instant) if instant else None),
            "instant": instant is not None,
            "dimensional": has_dims,
        }
    facts = {}
    for el in root.iter():
        ctx = el.get("contextRef")
        if not ctx or ctx not in contexts or contexts[ctx]["dimensional"]:
            continue
        name = el.tag.split("}")[-1]
        text = (el.text or "").strip()
        if el.get("unitRef") is not None:
            try:
                facts[(name, ctx)] = Decimal(text)
            except InvalidOperation:
                continue
        else:
            facts[(name, ctx)] = text
    return {"contexts": contexts, "facts": facts}


def quarter_context(parsed: dict, period_end: date) -> Optional[str]:
    """Find the non-dimensional ~3-month duration context ending on period_end.

    We select by actual dates, not by NSE's context naming ("OneD"), so a renamed
    context does not silently shift the period.
    """
    best = None
    for cid, c in parsed["contexts"].items():
        if c["dimensional"] or c["instant"] or c["end"] != period_end or not c["start"]:
            continue
        days = (c["end"] - c["start"]).days
        if 85 <= days <= 95:
            if best is not None:
                raise ValueError(f"ambiguous quarter contexts: {best}, {cid}")
            best = cid
    return best


def source_for(ref: ResultFilingRef, fetched_at: datetime, sha: Optional[str], provenance: str) -> SourceRef:
    return SourceRef(
        doc_type="xbrl_result", url=ref.xbrl_url, retrieved_at=fetched_at, content_hash=sha,
        provenance=provenance, title=f"{ref.symbol} {ref.basis} results, quarter ended {ref.period_end.isoformat()}",
        published_at=ref.broadcast_at,
    )
