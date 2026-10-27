"""Management-guidance contract (Promise Ledger input).

Feasibility verdict 2026-10-27 (docs/source-feasibility-report.md §6): workable only with a strict
statement-kind taxonomy, speaker attribution, verbatim-quote validation, and an explicit
"unverifiable" outcome. Analyst paraphrases of guidance are recorded as pointers, never as guidance.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Optional

from finn.models import SourceRef
from finn.transcripts import locate_quote

StatementKind = Literal[
    "explicit_numeric",        # metric + number/range (+ ideally a period): "EBITDA margin 11-13% till FY30"
    "measurable_qualitative",  # checkable direction without a number: "working capital to trend towards 45-50 days"
    "commentary",              # aspiration / tone: "we will endeavor to inch up margins"
    "analyst_claim",           # an analyst describing guidance; a pointer to look for the original
]
Verification = Literal["met", "partly_met", "missed", "pending", "not_reaffirmed", "unverifiable"]


@dataclass(frozen=True)
class GuidanceItem:
    symbol: str
    quote: str                         # exactly as extracted from the PDF text layer
    kind: StatementKind
    speaker: Optional[str]
    speaker_role: Literal["management", "analyst", "unknown"]
    said_on: date
    source: SourceRef                  # transcript URL, content hash, location "p.7"
    metric: Optional[str] = None       # ebitda_margin | ebit_margin | revenue_growth | wc_days | capex | ...
    target_low: Optional[float] = None
    target_high: Optional[float] = None
    target_unit: Optional[str] = None  # "%", "days", "INR cr"
    forecast_period: Optional[str] = None   # "FY30", "exit FY27", None if not stated
    conditions: Optional[str] = None
    verification: Verification = "pending"
    verification_reason: Optional[str] = None


GUIDANCE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["quote", "page", "kind", "speaker", "metric", "target_low", "target_high", "target_unit",
                     "forecast_period", "conditions"],
        "properties": {
            "quote": {"type": "string"}, "page": {"type": "integer"},
            "kind": {"type": "string", "enum": ["explicit_numeric", "measurable_qualitative", "commentary", "analyst_claim"]},
            "speaker": {"type": ["string", "null"]}, "metric": {"type": ["string", "null"]},
            "target_low": {"type": ["number", "null"]}, "target_high": {"type": ["number", "null"]},
            "target_unit": {"type": ["string", "null"]}, "forecast_period": {"type": ["string", "null"]},
            "conditions": {"type": ["string", "null"]},
        }}}},
}

EXTRACTION_PROMPT_VERSION = "guidance-v0"
EXTRACTION_SYSTEM = (
    "You extract forward-looking statements from an Indian listed company's earnings-call transcript. "
    "Use ONLY the transcript text provided. Copy each quote exactly as it appears, including odd spacing. "
    "Classify kind: explicit_numeric (metric with a number or range), measurable_qualitative (checkable "
    "direction, no number), commentary (aspiration/tone), analyst_claim (an analyst describing guidance). "
    "Never convert vague language into a number. If no period is stated, forecast_period is null."
)


def admit(item: GuidanceItem, pages: list[str], hint_page: Optional[int]) -> tuple[bool, str]:
    """Gate every extracted statement before storage."""
    q = locate_quote(item.quote, pages, hint_page)
    if not q.ok:
        return False, "quote not found in source text"
    if item.kind == "explicit_numeric" and item.target_low is None and item.target_high is None:
        return False, "explicit_numeric without a target"
    if item.kind != "analyst_claim" and item.speaker_role == "analyst":
        return False, "analyst speech cannot be management guidance"
    return True, f"quote located on p.{q.page} ({q.method})"


def judge_band(actual: Optional[float], low: Optional[float], high: Optional[float], period_closed: bool) -> tuple[Verification, str]:
    """Deterministic verdict for a numeric band. The model never decides met/missed for numbers."""
    if actual is None:
        return "unverifiable", "no reported actual for this metric/period"
    if not period_closed:
        inside = (low is None or actual >= low) and (high is None or actual <= high)
        return "pending", f"period still open; latest actual {actual:g} is {'inside' if inside else 'outside'} the band"
    if (low is None or actual >= low) and (high is None or actual <= high):
        return "met", f"actual {actual:g} within [{low}, {high}]"
    return "missed", f"actual {actual:g} outside [{low}, {high}]"
