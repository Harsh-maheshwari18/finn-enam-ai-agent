# FINN: API and Data Verification Report

Run 2026-10-27. Sections 1–3: local development machine, gunicorn 23.0.0 with the exact Render start command, snapshot `3c15b9d5…`. Section 4: the deployed Render service. Section 5: timestamp correction, snapshot `ff4868ac…` (deployed as commit `ec315b3`, 09:16 UTC).

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
- **Render.** When sections 1–3 ran, the service did not exist yet. See sections 4–5 for the deployed service: two connectivity samples, not long-run access.
- **19 of 22 companies** are checked by identities and against screener, not against their signed PDFs by hand.
- **LT's results PDF is image-only.** Its lending-cost line is checked against XBRL and screener, not the PDF.
- **Insurers, and restatements other than the one found,** are not tested.
- **Promise Ledger: deployed and checked live (commit `8b4db28`, 2026-10-27).** `GET /api/v1/companies/{SYM}/promises` (API 0.4.0) serves the ledger for TCS, POLYCAB and HDFCBANK (17 records, deployed as `fdb7599` and checked live). Every quote is re-checked against the cited PDF page and speaker (`promise-ledger.md`). The ledger is labelled `stale` if it was built from a different snapshot. It is tested offline (`tests/test_promises.py`, 35) and in the browser (3 UI tests).
  - **Live check:** the API returned records identical to the committed ledger. The live `index.html`, `app.js` and `styles.css` were byte-identical to `web/`. The cards showed 50 source links (one per statement and follow-up). The 10 cited transcripts and 3 XBRL filings each returned HTTP 200 on a single GET, and every transcript matched its recorded sha256.
  - **Deployed and checked live (`2d8707d`):** the POLYCAB working-capital target and the exports audit note.
  - **Deployed and checked live (`fdb7599`):** the review-preparation corrections (17th record, TCS and C&W verdicts; see `promise-ledger.md`). 54/54 live checks passed: API records identical to the commit, frontend byte-identical, 17 cards with every source link, 11 transcripts and 3 XBRL filings reachable with matching hashes.
  - **Not yet deployed:** the two human-review changes (TCS 26–28% horizon wording and analyst question; POLYCAB exports Q2 FY27 figure).
  - **Review:** the audit was done by Claude. A person has reviewed 1 of 17 records (R01, accepted); the other 16 are not reviewed by a person. The review pack is `promise-ledger-human-review.md`.
- **Large swings are reproduced, not explained.** Some cards show them: DEEPAKNTR PAT +207% YoY; DIXON PBT +140% while EBITDA is −4%. Both match screener. The card does not yet explain why; that is the job of the filings and transcript layers.

## Reproduce
```
.venv/bin/python -m pytest -q                 # 254 tests, offline
.venv/bin/python -m finn.snapshot verify      # digest check
.venv/bin/gunicorn finn.api:app --bind 127.0.0.1:8000
```
The screener cross-check script and its output are kept outside the repo, because screener is not a primary source (ADR-005).

## 4. Render deployment (observed 2026-10-27)

Service https://finn-api-9z4q.onrender.com, commit `c9ccac0`, snapshot `3c15b9d5…` (the version before the timestamp fix).

| Request (from the development machine) | Result |
|---|---|
| `GET /health` | 200, `verified: true`. First call after idle took **23.6 s** (cold start); later calls 0.34–0.53 s |
| Companies, TCS / ITC / HDFCBANK results, POLYCAB transcripts | 200; values identical to the local run and the golden set |
| Unknown ticker / POST | 404 / 405 |

**Connectivity measured from the Render host at 2026-10-27 08:29:57 UTC** (`/api/v1/diagnostics/connectivity`, one sample):

| Source | HTTP | Latency | Parsed |
|---|---|---|---|
| NSE announcements | 200 | 1,232 ms | 19 filings in 30 days |
| NSE results listing | 200 | 188 ms | 14 filings |
| NSE archives XBRL | 200 | 124 ms | 280 facts |
| Yahoo chart | 200 | 45 ms | 5 bars |

A point-in-time observation: the Render IP was not blocked at that moment. It is not a guarantee against rate- or time-dependent blocking.

## 5. Timestamp correction (snapshot `ff4868ac…`, deployed)

**Defect:** `published_at` (results) and `broadcast_at` (announcements and transcripts) were served without an offset, e.g. `2026-10-08T22:07:33`, while `retrieved_at` was UTC.

**Source representation:** NSE sends naive wall-clock strings (`broadcast_Date: "08-Oct-2026 22:07:33"`, `an_dt: "23-Oct-2026 22:50:22"`). These are IST. HDFCBANK's 22:50:22 broadcast carries a covering letter dated October 23, 2026, which would be wrong if the time were UTC (04:20 IST on the 24th). NSE's own upload stamp in the file name (`…_23102026224657_…`) agrees to within 3.5 minutes.

**Fix (`finn/tz.py`, ADR-024):** attach Asia/Kolkata to the naive value, keeping the wall clock. No UTC reinterpretation; values that already have an offset pass through unchanged.

**Evidence:**
- **Served response:** TCS revenue `published_at` = `2026-10-08T22:07:33+05:30`; POLYCAB Q2 FY27 transcript `broadcast_at` = `2026-10-19T16:39:28+05:30`.
- **Snapshot diff (old against new):** the only changed columns are `sources.published_at` (66 rows) and `transcript_filings.broadcast_at` (13 rows). Every new value equals the old wall clock plus `+05:30`. 0 values lack an offset. All 942 observations, 66 integrity rows, 22 company rows and 12 coverage rows are unchanged.
- **Tests:** `tests/test_timezones.py` (9 tests, including a UTC-aware value that must not be shifted, and a legacy naive database row), plus 5 API tests.
- **Deployed service** (commit `ec315b3`, checked 2026-10-27 09:16–09:20 UTC from the development machine): `/health` digest `ff4868ac…`, `verified: true`, 22 companies; TCS revenue `73188.00`, 4 of 4 `published_at` with `+05:30`; POLYCAB transcripts `broadcast_at` with `+05:30` (Q2 FY27 `2026-10-19T16:39:28+05:30`). A second connectivity probe from Render at 09:17:49 UTC passed all four checks (NSE announcements 827 ms, results listing 197 ms, XBRL 200 ms, Yahoo 53 ms). Not re-checked after the redeploy: 404/405 responses (unchanged code) and cold start (service was warm; 23.6 s on the first deploy).
- **At the deployed commit:** 254 tests passed offline; `snapshot verify` OK.
