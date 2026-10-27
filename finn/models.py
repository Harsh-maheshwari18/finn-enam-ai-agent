"""Data contracts. Field meanings follow docs/data-and-evidence-standard.md."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

Provenance = Literal["live", "cached", "fixture", "unavailable"]
Basis = Literal["consolidated", "standalone"]


@dataclass(frozen=True)
class SourceRef:
    doc_type: str                 # xbrl_result | announcement | announcement_pdf | transcript | annual_report | price_feed
    url: Optional[str]
    retrieved_at: datetime
    content_hash: Optional[str]
    provenance: Provenance
    title: Optional[str] = None
    published_at: Optional[datetime] = None
    location: Optional[str] = None  # "context OneD / in-capmkt:ProfitBeforeTax", "p.7"


@dataclass(frozen=True)
class Unavailable:
    """A source that could not be read. Carried to the UI verbatim, never hidden."""
    source: str
    reason: str
    url: Optional[str] = None
    http_status: Optional[int] = None
    last_good_at: Optional[datetime] = None


@dataclass(frozen=True)
class PriceBar:
    symbol: str                   # Yahoo symbol, e.g. TCS.NS
    day: date
    open: Optional[float]
    high: Optional[float]
    low: Optional[float]
    close: float
    volume: Optional[int]         # None = not reported; 0 is kept but flagged
    provisional: bool             # session not yet closed when fetched
    volume_suspect: bool          # volume == 0 on a bar with a price (stale fill)
    source: SourceRef


@dataclass(frozen=True)
class Filing:
    seq_id: str
    symbol: str
    isin: Optional[str]
    company: str
    nse_desc: str                 # NSE's own subject label, kept verbatim
    headline: str                 # attchmntText, kept verbatim
    broadcast_at: datetime        # IST, naive
    attachment_url: Optional[str]
    attachment_size: Optional[str]
    has_xbrl: bool
    source: SourceRef


@dataclass(frozen=True)
class ResultFilingRef:
    symbol: str
    period_end: date
    basis: Basis
    audited: bool
    taxonomy: Literal["indas", "banking", "other"]
    broadcast_at: Optional[datetime]
    xbrl_url: Optional[str]
    html_url: Optional[str]
    seq_id: Optional[str]
    revised: bool


@dataclass(frozen=True)
class Observation:
    symbol: str
    metric: str                   # revenue | other_income | finance_costs | dna | pbt | pat | ebitda | total_income | ppop | ...
    value: Optional[Decimal]      # absolute INR; None only with status != "extracted"/"derived"
    period_start: date
    period_end: date
    basis: Basis
    status: Literal["extracted", "derived", "missing", "not_applicable"]
    source: SourceRef
    reported_tag: Optional[str] = None   # XBRL element the value came from
    reported_rounding: Optional[str] = None
    formula: Optional[str] = None
    note: Optional[str] = None

    @property
    def months(self) -> int:
        return (self.period_end.year - self.period_start.year) * 12 + self.period_end.month - self.period_start.month + 1


def to_jsonable(obj):
    """dataclass -> JSON-safe dict (Decimal -> str to keep exactness)."""
    if hasattr(obj, "__dataclass_fields__"):
        return {k: to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    return obj
