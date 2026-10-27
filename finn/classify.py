"""Announcement -> reference category (R §1).

Order: (1) NSE subject label, (2) keyword rules on the headline, (3) unresolved.
Unresolved items are *not* guessed: they go to the optional LLM step at ingest, and if
that is unavailable they surface as "needs review" at a neutral priority.

Observed 2026-10-27 (87 filings, TCS/HDFCBANK/POLYCAB, 60 days): 41% carried the vague labels
"General Updates"/"Updates", including an acquisition completion and an NCLT order.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional

from finn.models import Filing

CATEGORIES = ["results", "M&A", "fund_raise", "management_change", "litigation", "insider_trading", "earnings_call",
              "investor_meetings", "credit_rating", "dividend", "bonus_split", "capex", "press_release",
              "postal_ballot", "agm_egm", "pledging", "unclassified"]

DESC_MAP = {
    "Outcome of Board Meeting": None,          # could be results, dividend, fund raise: decide on text
    "Financial Result Updates": "results",
    "Acquisition": "M&A", "Amalgamation / Merger": "M&A", "Scheme of Arrangement": "M&A",
    "Change in Management": "management_change", "Change in Director(s)": "management_change",
    "Change in Directors/ Key Managerial Personnel/ Auditor/ Compliance Officer/ Share Transfer Agent": "management_change",
    "Resignation of Director": "management_change", "Appointment of Director": "management_change",
    "Corporate Insolvency Resolution Process": "litigation", "Litigation / Dispute / Regulatory Action(s)": "litigation",
    "Action(s) taken or orders passed": "litigation", "Preferential issue": "fund_raise",
    "Insider Trading / SAST": "insider_trading", "Disclosure under SEBI Takeover Regulations": "insider_trading",
    "Analysts/Institutional Investor Meet/Con. Call Updates": None,   # transcript vs. meeting: decide on text
    "Credit Rating": "credit_rating",
    "Dividend": "dividend", "Record Date": "dividend",
    "Bonus": "bonus_split", "Sub-division / Stock Split": "bonus_split",
    "Press Release": "press_release", "Bagging/Receiving of orders/contracts": "press_release",
    "Postal Ballot": "postal_ballot", "Shareholders meeting": "agm_egm",
    "Pledge": "pledging", "Disclosure of encumbrance": "pledging",
    "ESOP/ESOS/ESPS": "unclassified", "Copy of Newspaper Publication": "unclassified", "Trading Window": "unclassified",
    "Certificate under SEBI (Depositories and Participants) Regulations, 2018": "unclassified",
    "Loss of Share Certificates": "unclassified", "Duplicate Share Certificate": "unclassified",
}

# Keyword rules on the headline, applied in order. Deliberately conservative.
TEXT_RULES: list[tuple[str, str]] = [
    (r"financial results for the (period|quarter)|unaudited .*financial (results|statements)|earnings presentation", "results"),
    (r"\btranscript\b|link of recording|audio recording|earnings call|conference call", "earnings_call"),
    (r"analyst\(s\)/investor\(s\) meet|investor meet|analyst meet|investor conference|schedule of meet|"
     r"institutional investors meet", "investor_meetings"),
    (r"acqui|amalgamat|merger|demerger|joint venture|stake in", "M&A"),
    (r"\bnclt\b|\bnclat\b|insolvency|tribunal|show cause|penalty|regulatory action|litigation|court", "litigation"),
    (r"credit rating|rating agency|reaffirm", "credit_rating"),
    (r"qualified institution(al)? placement|qualified institutional|\bqip\b|rights issue|preferential allotment|buyback|commercial paper|non-convertible debenture", "fund_raise"),
    (r"dividend|record date", "dividend"),
    (r"resign|appoint|cessation|chief executive|chief financial|managing director|key managerial", "management_change"),
    (r"capacity expansion|new plant|capex|capital expenditure|greenfield|brownfield", "capex"),
    (r"pledge|encumbrance", "pledging"),
    (r"press release|wins|bags|order|partner|launch", "press_release"),
    (r"stock option|esop|restricted stock unit|newspaper|compliance certificate|trading window|dematerial", "unclassified"),
]


@dataclass(frozen=True)
class Classification:
    category: Optional[str]                 # None = unresolved
    method: Literal["nse_label", "headline_rule", "unresolved", "model"]
    rule: Optional[str] = None


def classify(f: Filing) -> Classification:
    mapped = DESC_MAP.get(f.nse_desc, "__unknown__")
    if mapped not in (None, "__unknown__"):
        return Classification(mapped, "nse_label", f.nse_desc)
    text = f.headline.lower()
    for pattern, cat in TEXT_RULES:
        if re.search(pattern, text):
            return Classification(cat, "headline_rule", pattern)
    return Classification(None, "unresolved")
