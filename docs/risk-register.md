# FINN — Risk Register

Updated 2026-10-27 (Prompt 3). Ordered by priority (likelihood × impact, our judgment). Δ shows the latest change. No risk has been removed.

| # | Risk | L | I | Δ / evidence | Early warning | Mitigation (status) |
|---|---|---|---|---|---|---|
| R1 | **Not enough time** (≈4.5 days) | H | H | Unchanged. The data spine took most of day 1 | M3 not deployed by Thu night | Hard scope freeze; deploy on day 3 (planned) |
| R2 | NSE blocks the deployment host's IP | **M** | H | **First measurement: not blocked.** One probe from Render Singapore, 2026-10-27 08:29 UTC: all 4 sources 200 and parsed [E]. One sample only; blocking can be rate- or time-dependent | `all_ok: false` from `/api/v1/diagnostics/connectivity` | Snapshot endpoints never touch NSE; re-probe before the demo; refresh-by-commit if blocked |
| R3 | No LLM key / quota | **H** | M | Credentials still absent [E]. Impact lowered: the numbers path needs no LLM [E] | — | No-LLM mode implemented and tested [E]; needs a key to test extraction at all |
| R4 | Wrong financial number shown | M | H | 44/44 golden [E]. **Prompt 3 screener cross-check of 22 companies found 2 real defects** (excise-inflated revenue, NBFC EBITDA), both fixed; 0 unexplained differences remain [E] | Integrity `fail`/`warn`; cross-check differences | Golden tests, integrity identities, conventions pinned to signed PDFs (ADR-022); rerun the cross-check after every snapshot rebuild |
| R5 | Promise Ledger noisy or fabricates quotes | M | H | Quote gate + speaker attribution 10/10 on real text [E]; no model output tested yet | Quote-reject rate >10% on real LLM output | Exact/normalised-only matching (ADR-013); analyst filter; deterministic verdicts |
| R5b | **Promise Ledger too sparse to impress** | **H** | M | **New.** Only 1 of 10 real statements is checkable against XBRL today. TCS/HDFCBANK guide mostly in aspirations | <3 checkable items for a demo company | Feature POLYCAB-style guiders; surface "not reaffirmed" and "unverifiable" as findings; add segment / working-capital actuals only if cheap |
| R6 | Free-host cold start | **H** | M | **Measured**: 23.6 s for the first request after idle; 0.34–0.45 s warm [E] | >10s first load | Warm the URL before a demo; the frontend should show a loading state, not a blank screen |
| R7 | screener rate limit / HTML change | **L** | **L** | **Lowered**: screener is now off the critical path (ADR-005). 429 at 1.2s [E]; 8s spacing worked [E] | — | Throttle 8s (implemented); NSE is primary |
| R8 | Scanned PDFs | L | M | Lowered: 0/7 scanned [E] | `looks_scanned()` true | Mark unparseable (implemented); no OCR |
| R9 | Unseen-ticker research too slow | L | M | Lowered for numbers: ≈4s [E]. Transcripts + LLM latency unmeasured | >60s | Background task only if measured |
| R10 | Lenders break the template | M | **M** | Banks handled [E]. **NBFC found**: BAJFINANCE showed a 71% EBITDA margin; now not applicable (ADR-021) [E]. Insurers untested | Missing tags; implausible margins | Bank metric set (ADR-008); NBFC tag detection (ADR-021) |
| R11 | Looks like generic AI output | M | H | Unchanged | Prose-heavy screens | Numbers-first cards |
| R12 | AI build history missing | L | H | Unchanged | — | Export sessions daily |
| R13 | ToS / redistribution | L | M | Raw data git-ignored; only small real fixtures committed; Yahoo trimmed to 30 bars [E] | — | ADR-015 |
| R14 | Secrets leaked | L | H | `.gitignore` covers `.env*`; `.env.example` has empty values [E] | — | Scan before first push |
| R15 | **Filer XBRL mis-tagging beyond the detected pattern** | M | H | **New.** HDFCBANK tagged minority interest as an exceptional item in 2 of 3 quarters [E]. Other patterns surely exist | Integrity `fail`; YoY jumps that don't match the PDF | Integrity identities on every filing (implemented); show the warning; spot-check 3 more companies against PDFs |
| R16 | **Intraday bar treated as EOD** | L | M | **New**, now mitigated [E] | — | `provisional` flag + exclusion (implemented, tested) |
| R17 | **20% of filings unclassifiable from headline** | H | M | **New** [E] (17/87) | "needs review" bucket large in demo | PDF first-page keyword pass; LLM only if a key arrives |
| R18 | Transcript history unverified | **L** | H | **Mitigated**: 12/12 quarters available and audited for 3 companies [E] | — | `transcript-coverage.md`; quarter read from the text, not the date |
| R19 | **Results season timing**: some portfolio names have not reported Q2 FY27 yet (BEL, CAMS latest is Jun-26) | — | L | **New** [E]. It's an opportunity: live results land during evaluation week | — | Card always states the period; ingest on schedule |
| R20 | Model choice / cost routing undecided | M | M | **New.** Default `claude-opus-5-5`; Haiku 5.5 is ~40× cheaper per listed price | — | User decision (ADR-009) |
| R21 | **Snapshot goes stale during results season** | H | M | Re-confirmed with fresh NSE listings at 2026-10-27 08:39 UTC: 17 of 22 companies' latest filed quarter is Jun-26 (Sep-26 not yet filed) [E] | Card `period_end` older than the latest NSE listing | Card states period and snapshot date; `python -m finn.snapshot build --refresh` (≈1 min) + commit before submission |
| R22 | **NBFC detection is a heuristic from one company** | M | M | **New** [E]: 1 NBFC, 19 non-lenders tested | A lender with a high "EBITDA margin" | Tag rule + regression tests; also check NSE's `NBFC` file naming if another case appears |
| R23 | Deployment not done before review | — | — | **Closed**: deployed 2026-10-27, commit `c9ccac0` [E] | — | — |
| R24 | **Quarter detection tuned on 13 documents** | M | M | **New.** First version mis-read TCS Q3 FY26 [E] | Date cross-check disagrees; `quarter_ambiguous` true | Real-phrase regression tests; date cross-check stored per file |
| R25 | **Regrouped / restated comparatives** | M | M | **New** [E]: BAJFINANCE Sep-25 revenue regrouped by 188.48 cr; XBRL is silent about it | Cross-check difference only in a prior-period column | Disclosed on every card (ADR-023); fix needs comparatives parsed from the current PDF |
| R26 | **Timestamps shown in the wrong timezone** | — | M | **New, fixed** [E]: NSE times were served without an offset; now +05:30 (ADR-024). Live Render still serves the old snapshot until redeployed | A `published_at`/`broadcast_at` without an offset | `tests/test_timezones.py`; API tests assert offsets |
