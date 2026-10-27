# FINN — Data & Evidence Standard

Status: v0.2 (2026-10-27, revised after Prompt 2 testing; changes are marked **[v0.2]**). These rules apply to every number and claim the product shows.

## 1. Non-negotiables
1. **Never fabricate** a number, quote, page reference, filing, person profile or source URL. When we don't know, we say so: `unavailable` is a first-class state.
2. **Numbers come from deterministic code** reading structured primary data (XBRL/iXBRL) or validated tables. The LLM never does arithmetic.
3. **Every rendered claim carries a `source_ref`.** A claim without one does not render.
4. **Four layers are always distinguishable in the UI:** Evidence (quoted/extracted) · Calculation (formula + inputs) · Interpretation (model output, labelled) · Uncertainty (what's missing/ambiguous).
5. **Pull side uses primary sources only.** LLM prompts contain retrieved document text and an instruction to answer only from it. Answers without a citation are rejected at validation.
6. Test fixtures live in `tests/fixtures/`, are labelled `fixture`, and are never served by the app.

## 2. Schemas (Pydantic, stored in SQLite)

```python
class SourceRef:
    doc_type: Literal["xbrl_result","results_pdf","announcement_pdf","transcript","annual_report","investor_ppt","price_feed"]
    url: str | None
    title: str | None
    published_at: datetime | None
    location: str | None          # "p.7", "Q&A, answer to 3rd question", "Statement of P&L"
    retrieved_at: datetime
    content_hash: str             # sha256 of the raw bytes we parsed
    provenance: Literal["live","cached","fixture","unavailable"]

class FinancialObservation:
    symbol: str; isin: str | None
    metric: Literal["revenue","other_income","finance_costs","dna","pbt","pat","ebitda"]
    value: Decimal | None          # always stored in INR (absolute), converted from filing rounding level
    unit: Literal["INR"]
    reported_rounding: Literal["lakhs","crores","millions","units"]
    period_start: date; period_end: date
    period_type: Literal["quarter","ytd","annual"]
    basis: Literal["consolidated","standalone"]
    derived: bool                  # True for EBITDA
    formula: str | None            # "pbt + finance_costs + dna - other_income"
    restated: bool = False
    source: SourceRef
    status: Literal["extracted","validated","failed","not_applicable"]
    note: str | None               # e.g. "EBITDA not meaningful for banks"

class GuidanceItem:
    symbol: str
    statement: str                 # verbatim quote (validated: must be a substring of source text after whitespace normalisation)
    speaker: str | None            # only if transcript labels it
    said_on: date                  # call date
    source: SourceRef              # transcript URL + page
    metric: str                    # "revenue_growth","ebitda_margin","capex","volume","other"
    target_kind: Literal["point","range","direction","qualitative"]
    target_low: Decimal | None; target_high: Decimal | None; target_unit: str | None   # "%", "INR cr", "x"
    forecast_period: str | None    # "FY27", "H2 FY27", "next 2-3 years"
    conditions: str | None         # "subject to demand recovery"
    measurable: bool
    extraction_model: str; extraction_status: Literal["validated","failed"]

class GuidanceOutcome:
    guidance_id: int
    verdict: Literal["met","partly_met","missed","pending","unverifiable"]
    actual_value: Decimal | None; actual_source: SourceRef | None
    calculation: str | None        # "FY26 revenue growth = (X − Y) / Y = 8.4%"
    judged_by: Literal["rule","model"]
    rationale: str                 # ≤ 30 words; model-generated rationale is labelled as interpretation
```

## 3. Metric definitions (from R §3, made operational)

| Metric | Definition used | Source field (Ind-AS iXBRL) | Notes |
|---|---|---|---|
| Revenue | Revenue from operations | `Revenue from operations` | Excludes other income (per R §3 "top line") |
| PBT | Profit before tax | `ProfitBeforeTax` | Use the P&L value, not the segment table. **[v0.2]** Correction: the TCS segment figure 18,815 cr is *segment result before finance costs*, not a second PBT. When exceptional items ≠ 0, show them separately (`ExceptionalItemsBeforeTax`) |
| PAT | Net profit for the period | `Net Profit Loss for the period` (continuing + discontinued) | Show PAT attributable to owners when present as secondary |
| EBITDA | **[v0.2] Derived:** PBT *before exceptional items* + Finance costs + D&A − Other income | `ProfitBeforeExceptionalItemsAndTax` etc. | The v0.1 formula (using PBT after exceptional items) failed on TCS Jun-26 (17,888 vs 18,556). The pre-exceptional form reconciles in 6/6 quarters. Labelled "derived" with the formula |
| EBITDA (banks) | **Not applicable** | — | **[v0.2]** Banks show Total income (`Income`), NII (derived: interest earned − interest expended), PPOP (`OperatingProfitBeforeProvisionAndContingencies`), PBT, PAT. NBFCs/insurers are untested |
| Bank PAT | **[v0.2]** Net profit after minority interest | `ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates` | Matched the signed PDF line 16 in 3/3 HDFCBANK quarters; `ProfitLossForThePeriod` did not |
| Bank PBT | **[v0.2]** Reported tag; if consolidated AND `ExceptionalItems` ≠ 0 AND minority = 0 → PPOP − provisions, with a warning | — | Detects the HDFCBANK mis-tag (minority interest booked as pre-tax exceptional) |

## 3b. Integrity checks [v0.2]
Every ingested filing runs arithmetic identities (Ind-AS: total income = revenue + other income; PBT = pre-exceptional PBT + exceptional; continuing PAT = PBT − tax. Banking: total income = interest earned + other income; PPOP = total income − interest expended − opex). A failure is shown on the card. 9/9 tested filings pass.

## 4. Calculation rules
- **Units:** convert using the filing's `Level of rounding` (lakh = 1e5, crore = 1e7) to absolute INR. Display in ₹ crore with fixed rounding.
- **QoQ:** quarter ending Q vs. the quarter ending immediately before, same basis. **YoY:** the same fiscal quarter a year earlier, same basis. Both must be 3-month periods; YTD columns are never used for QoQ.
- **Percent change:** `(curr − prev) / |prev|`. If `prev ≤ 0` or the sign flips → show "n/m" plus both absolute values (e.g. a loss turning to profit), never a misleading %.
- **Consolidated vs standalone:** prefer consolidated; fall back to standalone only if consolidated is absent. **Never mix bases** across the current/prior columns. Basis is shown on the card.
- **Restatements:** if a later filing reports a different value for a prior period, use the most recent filing's comparative where available and flag `restated=True`. (The integrated iXBRL lacks comparatives [F], so restatement detection is Tier 2.)
- **Missing values:** the cell shows "—" with a tooltip reason. Deltas depending on it show "—". No interpolation.
- **Margins:** computed only when both numerator and Revenue exist in the same filing and basis.
- **Volume spike:** `volume_today / mean(volume over prior N sessions, excluding today)`, default N=20, threshold default 2.0×. **Price move:** close-to-close % vs prior session close, default ±5%. All configurable.

## 5. Guidance handling
- **Measurable:** has a metric, a direction or number, and a period → matched to actuals by rule where possible (e.g. "double-digit revenue growth in FY26" vs computed FY26 growth).
- **Ambiguous / opinion** ("we remain confident", "demand is resilient") → stored `measurable=False` and shown in a collapsed "Commentary (not verifiable)" group. These are never given Met/Missed.
- **Period not yet reported** → `pending`.
- **No actual available** (e.g. segment KPI not in XBRL) → `unverifiable` with the reason. The model may not guess.
- **Conflicting statements across calls** → both kept; the later one is shown as "revised from …" (Tier 2 nicety).
- **Quote validation [v0.2]:** the quote must occur in the source text exactly, or after *reversible* normalisation only (NFKC, `Ư`→ff, whitespace, hyphen spacing). Fuzzy similarity was dropped because it would admit paraphrases (ADR-013).
- **Speaker [v0.2]:** attributed from speaker turns across page breaks. Analyst speech can only be stored as `analyst_claim`, a pointer to find the original management statement.
- **Verdicts [v0.2]:** met / partly_met / missed / pending / **not_reaffirmed** / unverifiable. Numeric verdicts are computed in code (`judge_band`), never by the model.

## 6. Classification evidence
Category is derived first from NSE's `desc` field through a mapping table (deterministic). Only ambiguous ones (`General Updates`, `Updates`, `Press Release`) go to a cheap LLM with the attachment text. The receipt shows whether the category came from a `rule` or the `model`.

## 7. People profiles (management change)
Extracted only from the filing text (person, role, appointment/cessation, effective date, profile paragraph). If the profile is absent, show "Profile not disclosed in filing" plus a search link. We do not scrape LinkedIn.
