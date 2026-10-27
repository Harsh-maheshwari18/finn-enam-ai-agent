# FINN — Financial Golden Set

Fixture: `tests/fixtures/real/golden_set.json` (values), `tests/fixtures/real/xbrl_*.xml` (inputs), `manifest.json` (URLs + sha256).
Test: `tests/test_golden.py`. **Result 2026-10-27: 44/44 observations reproduced from XBRL. 9/9 integrity identity sets pass. 6/6 EBITDA reconcile to screener within ₹1 cr.**

## Method
1. **Authority:** the company's signed results PDF, filed on NSE. I read the values by hand from the printed consolidated statement, noting page and unit.
2. **System path:** the NSE XBRL instance for the same quarter is parsed by `finn.adapters.nse_results` → `finn.metrics.extract`. No LLM is involved.
3. **Test:** both sides are converted to absolute INR (`from_reported` for the PDF unit) and compared at 0.01 crore.
4. **Secondary cross-check:** screener.in's quarterly table. It is recorded and explained, but it **never overrides** the PDF.

## Coverage
| Company | Type | Doc / page / unit | Quarters | Metrics |
|---|---|---|---|---|
| TCS | IT services, Ind-AS | Q2 FY27 results PDF p.8, ₹ crore | Sep-26, Jun-26, Sep-25 (all three columns on one page) | revenue, other income, finance costs, D&A, PBT pre-exceptional, PBT, PAT, PAT owners |
| POLYCAB | Cables, Ind-AS | Q2 FY27 results PDF p.4, **₹ million** | same | revenue, other income, finance costs, D&A, PBT, PAT |
| HDFCBANK | Bank, banking taxonomy | Q2 FY27 results PDF p.9, ₹ crore | same | interest earned/expended, total income, PPOP, provisions, PBT, PAT |

## Findings that changed the design
1. **EBITDA must exclude exceptional items.** TCS Jun-26 had a −₹668 cr exceptional item. With PBT after exceptional, EBITDA = 17,888, which matches nothing. With PBT before exceptional, EBITDA = **18,556**, matching screener's Operating Profit. The same holds for Sep-25 (−1,135 exceptional → 17,978 ✓). The formula is now `pbt_pre_exceptional + finance_costs + dna − other_income`. The Prompt-1 formula was wrong.
2. **XBRL can be wrong; the PDF wins.** In HDFCBANK Sep-26 and Sep-25, minority interest (837.06 / 753.10 cr, a *post-tax* item) is tagged as pre-tax `ExceptionalItems`, with `ProfitLossOfMinorityInterest = 0`. The XBRL PBT (27,825.48) is therefore ₹837 cr below the signed PDF (28,662.54). Jun-26 is tagged correctly (minority 1,137.98).
   - **Handling:** for consolidated bank filings showing that pattern, PBT = PPOP − provisions, with a visible warning. A standalone filing is never reinterpreted.
3. **Bank PAT = "Net profit for the period" after minority interest** (PDF line 16), tag `ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates`. It matched the PDF in 3/3 quarters, while `ProfitLossForThePeriod` matched in only 2/3.
4. **Screener's "Net Profit" for HDFCBANK is *before* minority interest** (21,537 vs 20,700). That gives QoQ PAT growth of 5.7% instead of the correct 7.6%. This shows why an aggregator cannot be the source of record.
5. **Units are not uniform**: TCS and HDFCBANK print crores, POLYCAB prints millions. XBRL values are always absolute INR. `LevelOfRounding` only describes the PDF.
6. **The latest-quarter XBRL has no comparative columns**, so QoQ/YoY come from the prior filings (also verified). The PDFs *do* carry comparatives, which made the three-period check possible from one document.

## Calculations verified by hand
| Calculation | Inputs (₹ cr) | Result |
|---|---|---|
| TCS revenue QoQ | 73,188 vs 72,275 | +1.26% |
| TCS revenue YoY | 73,188 vs 65,799 | +11.23% |
| TCS EBITDA QoQ | 18,815 vs 18,556 | +1.40% |
| TCS EBITDA margin | 18,815 / 73,188 | 25.71% |
| HDFCBANK PAT QoQ | 20,700.03 vs 19,244.71 | +7.56% |
| POLYCAB EBITDA (from PDF, ₹ mn) | 13,062.20 + 936.04 + 1,110.41 − 883.67 = 14,224.98 mn | ₹1,422.50 cr |

## Generalisation cross-check (not in the golden fixture)
Run live with no code change on two tickers outside every list, then compared with screener. **This is a secondary check only, not PDF-verified.**

| Symbol | Latest quarter | Revenue | EBITDA | PBT | PAT | Screener |
|---|---|---|---|---|---|---|
| BEL | Jun-26 | 5,546.98 (QoQ −45.75%, YoY +24.94%) | 1,388.40 | 1,396.25 | 1,054.53 | 5,547 / 1,388 / 1,396 / 1,055 ✓ (Mar-26 revenue 10,224 confirms the seasonal QoQ drop) |
| CAMS | Jun-26 | 395.03 | 182.74 | 173.29 | 127.10 | 395 / 182 / 173 / 127 ✓ (EBITDA within screener rounding) |

## Known gaps
- Restatements are not exercised: none of the 9 filings had `revised_Date`.
- No NBFC or insurer tested. The banking path was tested on one bank only.
- Discontinued operations and share of associates are present as tags but are zero in all tested filings.
