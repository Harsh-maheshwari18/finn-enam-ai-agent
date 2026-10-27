"""Deterministic financial metrics. No model ever produces a number shown by FINN.

Definitions: docs/data-and-evidence-standard.md §3-4.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal, Optional

from finn.models import Observation, SourceRef

CRORE = Decimal(10_000_000)
LAKH = Decimal(100_000)

# XBRL element -> our metric, per taxonomy. First tag found wins; order matters.
TAGS = {
    "indas": {
        "revenue": ["RevenueFromOperations"],
        "other_income": ["OtherIncome"],
        "total_income": ["Income"],
        "finance_costs": ["FinanceCosts"],
        "dna": ["DepreciationDepletionAndAmortisationExpense"],
        "pbt_pre_exceptional": ["ProfitBeforeExceptionalItemsAndTax"],
        "exceptional": ["ExceptionalItemsBeforeTax"],
        "pbt": ["ProfitBeforeTax"],
        "tax": ["TaxExpense"],
        "pat_continuing": ["ProfitLossForPeriodFromContinuingOperations"],
        "pat": ["ProfitLossForPeriod"],
        "pat_owners": ["ProfitOrLossAttributableToOwnersOfParent"],
    },
    "banking": {
        "interest_earned": ["InterestEarned"],
        "interest_expended": ["InterestExpended"],
        "other_income": ["OtherIncome"],
        "total_income": ["Income"],
        "opex": ["OperatingExpenses"],
        "ppop": ["OperatingProfitBeforeProvisionAndContingencies"],
        "provisions": ["ProvisionsOtherThanTaxAndContingencies"],
        "exceptional": ["ExceptionalItems"],
        "pbt_reported": ["ProfitLossFromOrdinaryActivitiesBeforeTax"],
        "tax": ["TaxExpense"],
        "minority": ["ProfitLossOfMinorityInterest"],
        "pat_after_tax": ["ProfitLossFromOrdinaryActivitiesAfterTax"],
        # Bank P&L format: "Net profit for the period" is AFTER minority interest (HDFCBANK PDF line 16).
        # This tag matched the signed PDF in all 3 tested quarters; ProfitLossForThePeriod did not.
        "pat": ["ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates"],
    },
}
TOLERANCE = Decimal("0.02") * CRORE   # integrity checks allow 2 lakh of rounding noise

# The four headline rows a results card shows, per taxonomy. Banks get honest substitutes
# with different labels, never a relabelled "Revenue" or a computed "EBITDA".
HEADLINE = {
    "indas": ["revenue", "ebitda", "pbt", "pat"],
    "banking": ["total_income", "nii", "ppop", "pbt", "pat"],
}
LABELS = {
    "revenue": "Revenue", "ebitda": "EBITDA", "pbt": "PBT", "pat": "PAT",
    "total_income": "Total income", "nii": "Net interest income", "ppop": "Pre-provision op. profit",
}
EBITDA_FORMULA = "pbt_pre_exceptional + finance_costs + dna - other_income"
NII_FORMULA = "interest_earned - interest_expended"
BANK_PBT_FORMULA = "ppop - provisions"


def extract(parsed: dict, ctx: str, taxonomy: str, *, symbol: str, basis: str,
            source: SourceRef, rounding: Optional[str] = None) -> dict[str, Observation]:
    """Pull tagged facts for one context into Observations; derive EBITDA / NII deterministically."""
    c = parsed["contexts"][ctx]
    facts = parsed["facts"]
    out: dict[str, Observation] = {}

    def obs(metric, value, status, tag=None, formula=None, note=None):
        loc = f"context {ctx} / {tag}" if tag else f"context {ctx} / derived"
        src = SourceRef(**{**source.__dict__, "location": loc})
        return Observation(symbol=symbol, metric=metric, value=value, period_start=c["start"], period_end=c["end"],
                           basis=basis, status=status, source=src, reported_tag=tag, reported_rounding=rounding,
                           formula=formula, note=note)

    for metric, tags in TAGS.get(taxonomy, {}).items():
        for tag in tags:
            v = facts.get((tag, ctx))
            if isinstance(v, Decimal):
                out[metric] = obs(metric, v, "extracted", tag=tag)
                break
        else:
            out[metric] = obs(metric, None, "missing", note=f"none of {tags} present in filing")

    def v(k):
        o = out.get(k)
        return o.value if o is not None and o.status in ("extracted", "derived") else None

    if taxonomy == "indas":
        # EBITDA excludes exceptional items. Verified: TCS Jun-26 has a -668 cr exceptional item;
        # pre-exceptional EBITDA (18,556) reconciles to screener, post-exceptional (17,888) does not.
        base, base_note = v("pbt_pre_exceptional"), None
        if base is None and v("pbt") is not None:
            base, base_note = v("pbt"), "pre-exceptional PBT not tagged; EBITDA may include exceptional items"
        parts = {"finance_costs": v("finance_costs"), "dna": v("dna"), "other_income": v("other_income")}
        if base is not None and all(x is not None for x in parts.values()):
            out["ebitda"] = obs("ebitda", base + parts["finance_costs"] + parts["dna"] - parts["other_income"], "derived",
                                formula=EBITDA_FORMULA,
                                note=base_note or "Not reported by companies; derived from reported P&L lines, before exceptional items")
        else:
            miss = [k for k, x in parts.items() if x is None] + (["pbt"] if base is None else [])
            out["ebitda"] = obs("ebitda", None, "missing", formula=EBITDA_FORMULA, note=f"cannot derive; missing {miss}")
    elif taxonomy == "banking":
        out["ebitda"] = obs("ebitda", None, "not_applicable",
                            note="EBITDA is not meaningful for lenders: interest is their cost of goods. "
                                 "Shown instead: Net interest income and pre-provision operating profit.")
        if v("interest_earned") is not None and v("interest_expended") is not None:
            out["nii"] = obs("nii", v("interest_earned") - v("interest_expended"), "derived", formula=NII_FORMULA)
        else:
            out["nii"] = obs("nii", None, "missing", formula=NII_FORMULA, note="interest lines missing")
        out["pbt"] = _bank_pbt(out, obs, v, basis)
    return out


def _bank_pbt(out, obs, v, basis) -> Observation:
    """Bank PBT. Normally the reported tag. But HDFCBANK Sep-25 and Sep-26 XBRL book minority interest
    (a post-tax item) as a pre-tax "ExceptionalItems" with ProfitLossOfMinorityInterest = 0, which
    understates PBT vs. the signed PDF. When that pattern appears we use ppop - provisions and say so.
    """
    exc, mi = v("exceptional"), v("minority")
    reported = out["pbt_reported"]
    # Only consolidated: a standalone bank has no minority interest, so its exceptional items are real.
    if basis == "consolidated" and exc and (mi is None or mi == 0) and v("ppop") is not None and v("provisions") is not None:
        return obs("pbt", v("ppop") - v("provisions"), "derived", formula=BANK_PBT_FORMULA,
                   note=f"XBRL shows an 'exceptional item' of {to_crore(exc)} cr with zero minority interest; this "
                        "pattern matched mis-tagged minority interest in tested filings. PBT shown before it; "
                        "verify against the results PDF.")
    return obs("pbt", reported.value, reported.status, tag=reported.reported_tag, note=reported.note)


def integrity_checks(o: dict[str, Observation], taxonomy: str) -> list[dict]:
    """Arithmetic identities that must hold inside one filing. A failure is shown, not hidden."""
    def val(k):
        x = o.get(k)
        return x.value if x is not None and x.status in ("extracted", "derived") else None

    rules = {
        "indas": [
            ("total_income = revenue + other_income", "total_income", ["revenue", "other_income"], [1, 1]),
            ("pbt = pbt_pre_exceptional + exceptional", "pbt", ["pbt_pre_exceptional", "exceptional"], [1, 1]),
            ("pat_continuing = pbt - tax", "pat_continuing", ["pbt", "tax"], [1, -1]),
        ],
        "banking": [
            ("total_income = interest_earned + other_income", "total_income", ["interest_earned", "other_income"], [1, 1]),
            ("ppop = total_income - interest_expended - opex", "ppop", ["total_income", "interest_expended", "opex"], [1, -1, -1]),
        ],
    }
    out = []
    for name, lhs, terms, signs in rules.get(taxonomy, []):
        vals = [val(t) for t in terms]
        if val(lhs) is None or any(x is None for x in vals):
            out.append({"check": name, "status": "skipped"})
            continue
        rhs = sum(s * x for s, x in zip(signs, vals))
        diff = val(lhs) - rhs
        out.append({"check": name, "status": "pass" if abs(diff) <= TOLERANCE else "fail", "diff_crore": str(to_crore(diff))})
    if taxonomy == "banking" and o.get("pbt") is not None and o["pbt"].formula == BANK_PBT_FORMULA:
        out.append({"check": "minority interest tagged as exceptional item", "status": "warn"})
    return out


# ---------- comparisons ----------

ChangeStatus = Literal["ok", "missing", "zero_base", "sign_change", "negative_base", "misaligned", "not_applicable"]


@dataclass(frozen=True)
class Change:
    pct: Optional[Decimal]        # percentage points, e.g. Decimal("1.26") for +1.26%
    status: ChangeStatus
    current: Optional[Decimal]
    previous: Optional[Decimal]
    note: Optional[str] = None


def pct_change(current: Optional[Decimal], previous: Optional[Decimal]) -> Change:
    """(curr - prev) / |prev| * 100, refusing cases where a % would mislead.

    - either side missing -> "missing" (a valid 0 is NOT missing)
    - prev == 0           -> "zero_base"
    - sign flip           -> "sign_change" (e.g. loss to profit), show absolutes instead
    - both negative       -> "negative_base": % computed on |prev| so a shrinking loss is positive,
                             but flagged because readers misread it
    """
    if current is None or previous is None:
        return Change(None, "missing", current, previous)
    if previous == 0:
        return Change(None, "zero_base", current, previous)
    if (current < 0) != (previous < 0) and current != 0:
        return Change(None, "sign_change", current, previous, "sign changed; % not meaningful")
    pct = ((current - previous) / abs(previous) * 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
    if previous < 0:
        return Change(pct, "negative_base", current, previous, "both periods negative; % is change in loss")
    return Change(pct, "ok", current, previous)


def margin(numerator: Optional[Decimal], revenue: Optional[Decimal]) -> Optional[Decimal]:
    """Margin in % (2dp). None if either input missing or revenue <= 0."""
    if numerator is None or revenue is None or revenue <= 0:
        return None
    return (numerator / revenue * 100).quantize(Decimal("0.01"), ROUND_HALF_UP)


def _quarter_before(d: date) -> date:
    """Quarter-end date immediately before the quarter ending on d (e.g. 30 Sep -> 30 Jun)."""
    m = d.month - 2                       # first month of d's quarter
    y = d.year if m > 0 else d.year - 1
    m = m if m > 0 else m + 12
    return date(y, m, 1) - timedelta(days=1)


def expected_prior(period_end: date, kind: Literal["qoq", "yoy"]) -> date:
    if kind == "qoq":
        return _quarter_before(period_end)
    try:
        return period_end.replace(year=period_end.year - 1)
    except ValueError:              # 29 Feb
        return period_end.replace(year=period_end.year - 1, day=28)


def align(curr: Observation, prev: Optional[Observation], kind: Literal["qoq", "yoy"]) -> Optional[str]:
    """Return None if `prev` is a valid comparator for `curr`, else the reason it is not."""
    if prev is None:
        return "comparator period not available"
    if curr.metric != prev.metric:
        return f"metric mismatch {curr.metric} vs {prev.metric}"
    if curr.basis != prev.basis:
        return f"basis mismatch {curr.basis} vs {prev.basis}"
    if curr.months != 3 or prev.months != 3:
        return "both periods must be single quarters (YTD never used)"
    if prev.period_end != expected_prior(curr.period_end, kind):
        return f"expected period ending {expected_prior(curr.period_end, kind)}, got {prev.period_end}"
    return None


def compare(curr: Observation, prev: Optional[Observation], kind: Literal["qoq", "yoy"]) -> Change:
    why = align(curr, prev, kind)
    if why:
        return Change(None, "misaligned" if prev is not None else "missing", curr.value,
                      prev.value if prev else None, why)
    return pct_change(curr.value, prev.value)


def to_crore(v: Optional[Decimal]) -> Optional[Decimal]:
    return None if v is None else (v / CRORE).quantize(Decimal("0.01"), ROUND_HALF_UP)


def from_reported(v: Decimal, rounding: str) -> Decimal:
    """Convert a figure as printed in a PDF (in lakhs/crores/millions) to absolute INR."""
    scale = {"lakhs": LAKH, "lakh": LAKH, "crores": CRORE, "crore": CRORE,
             "millions": Decimal(1_000_000), "million": Decimal(1_000_000), "units": Decimal(1)}
    try:
        return v * scale[rounding.strip().lower()]
    except KeyError:
        raise ValueError(f"unknown rounding level {rounding!r}") from None
