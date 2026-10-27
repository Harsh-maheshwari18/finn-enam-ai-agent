# FINN: API and Data Verification Report

Run 2026-10-27, local development machine, gunicorn 23.0.0 with the exact Render start command. Snapshot digest `3c15b9d5437d9589…`, 22 companies. **Not yet run on Render.**

## 1. Does the API work?

| Request | Status | Size | Time |
|---|---|---|---|
| `GET /health` | 200 | 422 B | 21 ms (recomputes the snapshot digest) |
| `GET /api/v1/companies` | 200 | 6,255 B | 8 ms |
| `GET /api/v1/companies/TCS/results` | 200 | 3,803 B | 9 ms |
| `GET /api/v1/companies/ITC/results` | 200 | 4,054 B | 10 ms |
| `GET /api/v1/companies/HDFCBANK/results` | 200 | 5,770 B | 10 ms |
| `GET /api/v1/companies/BAJFINANCE/results` | 200 | 4,384 B | 9 ms |
| `GET /api/v1/companies/POLYCAB/transcripts` | 200 | 5,020 B | 8 ms |
| `GET /api/v1/companies/NOSUCH/results` | 404, with the reason | 351 B | 7 ms |
| `GET /api/v1/companies/A;B/results` | 400, symbol rejected | 55 B | <1 ms |
| `POST /api/v1/companies/TCS/results` | 405, read-only | — | — |

`/health`: `status ok · verified true · companies 22 · llm disabled`. The gunicorn error log had no errors or tracebacks.

Live connectivity probe **from this machine** (Render untested): NSE announcements 200 (19 filings in 30 days), NSE results listing 200, NSE XBRL archive 200 (280 facts), Yahoo 200 (5 bars). All four parsed.

## 2. Is the data reliable?

Three independent checks.

**a. Signed PDFs (golden set).** 44 of 44 figures match for TCS, HDFCBANK and POLYCAB, asserted against the committed snapshot in `tests/test_api.py`.

**b. Arithmetic identities** inside each filing. All 22 companies pass. The only warning is HDFCBANK's known minority-interest mis-tag.

**c. Independent cross-check against screener.in** (secondary source, whole crores, tolerance ±1 cr). Every value served for all 22 companies, for the current quarter and both comparison quarters:

| Result | Count |
|---|---|
| Exact match | 219 |
| Different, and reconciled to a documented convention | 36 |
| Different, unexplained | **0** |
| No screener counterpart (bank NII, PPOP, total income) | 9 |

The first run had 42 differences. Each was traced to a cause in the filings themselves:

| Cause | Companies | What FINN does now | Reconciliation example |
|---|---|---|---|
| **Excise duty inside "Revenue from operations"**, filed only as an itemised other expense | ITC, RELIANCE | **Fixed**: revenue shown net of excise (gross kept as `revenue_gross`); net is never compared with gross | ITC Jun-26: 29,523.30 − 10,408.93 (signed PDF p.6) = 19,114.37; screener 19,114 |
| **PBT before the share of associates/JVs** (NSE adds it after tax) | 10 companies | PBT stays as filed; the row's note gives the associates amount | MARUTI: 4,343.50 + 97.70 = 4,441.20; screener 4,441 |
| **Lending finance cost inside operating expenses** | LT | Kept as an operating cost (like a lender's interest); amount disclosed on the EBITDA row | 6,116.48 + 2,032.66 = 8,149.14; screener 8,149 |
| **Profit before vs after minority interest** | HDFCBANK | Unchanged: FINN matches the signed PDF | Jun-26: 19,244.71 + 1,137.98 = 20,382.69; screener 20,383 |
| **Prior quarter regrouped by the company** | BAJFINANCE | Disclosed on every card (`comparison_basis`); not corrected | Sep-25 revenue: 20,178.90 as filed vs 19,990.42 regrouped (Sep-26 PDF p.14). YoY 21.64% vs 22.79% like-for-like |

The excise fix changed served numbers. Before it, ITC revenue YoY read **+27.6%**; net of excise it is **−11.07%**, the same as screener's series. ITC's own note 5 says the excise rise from 1 Feb 2026 makes gross revenue "not strictly comparable".

The BAJFINANCE regrouping is the one place where FINN still shows a different YoY than a like-for-like comparison. It is counted above as reconciled, because the cause is proven, but **the number is not corrected**. NSE's latest XBRL has no comparative columns, and BAJFINANCE's XBRL notes do not mention the regrouping, so it cannot be detected automatically.

## 3. What this does not prove
- **Render.** The service has not been created, so cloud-host access to NSE and Yahoo is unmeasured.
- **19 of 22 companies** are checked by identities and against screener, not against their signed PDFs by hand.
- **LT's results PDF is image-only.** Its lending-cost line is checked against XBRL and screener, not the PDF.
- **Insurers, and restatements other than the one found,** are not tested.
- **Large swings are reproduced, not explained.** Some cards show them: DEEPAKNTR PAT +207% YoY; DIXON PBT +140% while EBITDA is −4%. Both match screener. The card does not yet explain why; that is the job of the filings and transcript layers.

## Reproduce
```
.venv/bin/python -m pytest -q                 # 240 tests, offline
.venv/bin/python -m finn.snapshot verify      # digest check
.venv/bin/gunicorn finn.api:app --bind 127.0.0.1:8000
```
The screener cross-check script and its output are kept outside the repo, because screener is not a primary source (ADR-005).
