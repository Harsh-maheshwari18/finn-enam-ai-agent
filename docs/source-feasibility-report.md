# FINN — Source Feasibility Report (Prompt 2)

Date: 2026-10-27. Environment: local WSL2 machine, Python 3.12.3, pypdf 6.21.2, pytest 9.1.1. **No deployment host tested. No LLM call made.**

Labels: **[E]** verified by execution · **[S]** supported by source inspection · **[I]** implemented, not executed · **[A]** assumed/unverified · **[B]** blocked

## 1. Verdict
The data path is viable. Every P0 question has an executed answer from this machine:

| Priority | Question | Answer |
|---|---|---|
| P0 | Usable price, volume, announcement, filing data? | **Yes [E]** (NSE + Yahoo) |
| P0 | Correct, traceable numbers without an LLM? | **Yes [E]**: 44/44 PDF-verified values reproduced. One filer mis-tag class found and handled |
| P0 | Runs without live data or an LLM? | **Yes [E]**: offline replay, no-LLM mode, all failures typed and tested |
| P1 | Transcripts and ARs retrievable with usable text? | **Yes [E]** for 3 companies' latest transcript and 2 ARs |
| P1 | Unseen ticker? | **Yes [E]**: BEL and CAMS, no code change, ≈4s each |
| P1 | Deployment host access? | **Unknown [A]**. Designed around it (ADR-014) |
| P2 | Cost / latency | XBRL ingest ≈4s per company with zero LLM cost [E]. AR text extraction 24s each [E]. LLM cost not measured [B] |

## 2. Prices [E]
- Sample: TCS.NS, HDFCBANK.NS, POLYCAB.NS, ITC.NS, TCS.BO. All returned 200 at 06:11 UTC, with 495 daily bars from 2024-10-28 to 2026-10-27, fields OHLCV + adjclose, currency INR, exchange NSI/BSE.
- **Trap:** the 2026-10-27 bar is the *live session* (TCS close 2,480.10, volume 1.80 M at 11:41 IST against 4.33 M the prior day). Treated as EOD, it would distort volume ratios. It is now flagged `provisional` when fetched before 16:00 IST on that day and excluded.
- Zero-volume rows on 2025-03-18 and 2026-01-15 with a carried price, which looks like a stale fill on non-trading days [S]. These are flagged and excluded from averages.
- TCS.BO had 3 null bars (e.g. 2026-10-26). They are skipped, not zero-filled. NSE (.NS) is the default.
- No throttling seen at ~1 request/s.

## 3. Announcements [E]
- NSE `api/corporate-announcements`, 3 symbols, 60 days: 31 / 30 / 26 records. Each has `seq_id`, symbol, ISIN, broadcast timestamp, NSE subject (`desc`), headline text and PDF URL. No duplicate attachments in the sample.
- Mapping to the reference categories (R §1): 34/87 by NSE label, 36/87 by headline rule, **17/87 unresolved** (20%). Most unresolved items are HDFCBANK "about General Updates" or "Disclosure under Regulation 30", where the headline carries no information. Resolving these needs the PDF's first page, which is the planned LLM/keyword step.
- The categories that matter can be distinguished:
  - TCS "completion of acquisition" is filed as *General Updates* and maps to M&A.
  - POLYCAB NCLT/NCLAT insolvency proceedings map to litigation (a live, material demo item).
  - HDFCBANK "Change in Management" ×2 and "Change in Director(s)".
  - Results ("financial results for the period ended…").
  - Routine items: ESOP, newspaper ads, trading window.
- BSE API: Access Denied (Akamai) [B]. It was not retried.

## 4. Results data [E]
- NSE has moved to **Integrated Filing** XBRL (`api/integrated-filing-results`). The older endpoint stops at Dec-2024 for TCS.
- XBRL XML is preferred over the iXBRL HTML. It has explicit period contexts (`OneD` = quarter, `FourD` = YTD), non-dimensional facts, and values in absolute INR. Contexts are selected **by dates, not names**.
- Two taxonomies: `INDAS` and `BANKING`. Banking has no revenue or EBITDA concept (ADR-008).
- The latest filing carries only current-quarter and YTD figures. Comparatives come from earlier filings; 7 quarters are listed per company.
- Details and the defects found are in `financial-golden-set.md`.

## 5. Documents [E]
| Document | Source | Pages | Text | Notes |
|---|---|---|---|---|
| TCS Q2 FY27 transcript | NSE announcement | 29 | ✓ | ligature and "Ư" artefacts |
| HDFCBANK Q2 FY27 transcript | NSE | 17 | ✓ | |
| POLYCAB Q2 FY27 transcript | NSE | 20 | ✓ | sentences broken across lines |
| TCS / HDFCBANK / POLYCAB Q2 FY27 results PDFs | NSE | 22 / 24 / 14 | ✓ | units differ; HDFCBANK prints "O" for 0 |
| TCS AR FY26 | NSE `api/annual-reports` | 361 | ✓ (24s) | 17 MB |
| HDFCBANK AR FY26 | NSE | 678 | ✓ (24s) | 12.7 MB; 9 near-empty pages |

0 of 7 PDFs looked scanned. HEAD requests to NSE archives return 503 while GET works, so we don't probe with HEAD. Only the **latest** transcript per company was tested. Four quarters of history per company is still **[A]**, though screener lists 27–66 transcripts per company and NSE keeps announcement history.

## 6. Management-guidance experiment [E, human-labelled]
Ten statements from 3 transcripts, labelled by hand (`tests/fixtures/real/guidance_experiment.json`).

| Kind | Count | Example |
|---|---|---|
| explicit_numeric | 2 | POLYCAB: "sustaining medium-to long-term EBITDA margins within our guided range of 11% to 13%" (p.7, Aditya Nathany), horizon FY30 per p.9. **This is the Wires & Cables segment margin** (see the correction under item 5) |
| measurable_qualitative | 3 | POLYCAB working capital "towards… 45 to 50 days" (no date) |
| commentary | 3 | TCS CFO: "long-term aspiration… 26% to 28%" (no period) |
| analyst_claim | 2 | TCS analyst: "margin commitment… exiting FY27, at 25% plus EBIT margin" |

Findings:
1. **10/10 quotes locate on their cited page** via exact or reversible normalisation. 1/1 paraphrase is rejected. A quote spanning a line break needs normalisation.
2. **Speaker attribution: 10/10** match the verified speaker. Turns carry across page breaks, and POLYCAB/HDFCBANK list management in a header. **My own first labels were wrong** for 4 POLYCAB items, and tracing the p.5 handover corrected them. Attribution must therefore come from code, not reading one page.
3. **The most "guidance-sounding" sentences are often analysts.** Without a speaker filter, 2/10 would have become false guidance.
4. **Real analytical signal exists:** TCS's CFO answered the "25% exit FY27" question with "uphill task… endeavor to inch up on our margins", which is a softening. The ledger needs a `not_reaffirmed` state, and must find the *original* commitment in an earlier transcript.
5. **Verifiability:** only 1/10 (POLYCAB group EBITDA margin band) can be checked against XBRL today. Its Q2 FY27 actual is 14.37%, *above* the 11–13% band, so the verdict is pending with the period open to FY30. Segment guidance (FMEG 8–10%) and working-capital days need data we don't extract.

   > **Correction (2026-10-27, Prompt 5; see `promise-ledger.md`).** The sentence above is wrong and is kept only as a record of what was concluded at the time. POLYCAB's 11–13% is the **Wires & Cables segment** EBITDA margin, not the company's consolidated margin. The Q2 FY27 statement sits in the Wires & Cables paragraph, right after "EBIT margins in the Wires and Cables segment stood at 14.2%" (p.7), and Q1 FY27 p.5 says "for this business". The consolidated 14.37% is therefore **not** a like-for-like actual, and no verdict, pending or otherwise, can be drawn from it. FINN's snapshot has no segment results, so **none of the 10** statements in this experiment (5 POLYCAB, 4 TCS, 1 HDFCBANK) can be checked like-for-like against filed numbers. Even the segment figure management reports is EBIT, while the guidance is EBITDA. The one checkable target found later is TCS's 25% exit operating margin (management's own words were located later, at Q1 FY27 p.23; the `analyst_claim` example in the table above is only a pointer to it).

**Conclusion:** the Promise Ledger is feasible but will be **sparse**, about 1–3 checkable promises per company per quarter. It is most valuable for companies that guide numerically (POLYCAB-style), and less so for TCS/HDFCBANK, which mostly speak in aspirations. The product should present "unverifiable" and "not reaffirmed" as findings, not hide them.

## 7. LLM [B]
`ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN`: **not set** (checked by name only). The `anthropic` SDK is not installed. `AnthropicProvider` is **[I]**: written against the documented SDK surface but never executed. The no-LLM mode, schema validation, retry, cache-by-hash and every degradation path are **[E]** with a fake provider.

## 8. Deployment host [A]
No host was chosen or tested. ADR-014 proposes local (or scheduled) ingest → validated SQLite snapshot → read-only deployed app, with the freshness labels from `data-failure-behaviour.md`. Live refresh from the host is best-effort and must be smoke-tested in Prompt 3 before any claim.

## 9. Vertical slice [E]
`python -m finn.cli ingest TCS` → `card TCS`. Live: listing + 3 XBRL files + announcements in ≈4s. Output is the Revenue / EBITDA / PBT / PAT card with QoQ/YoY, EBITDA margin, integrity checks, and per-row source URL, XBRL location, retrieval time, publication time and provenance. The same path works offline from the cache (tests) and on unseen tickers.
