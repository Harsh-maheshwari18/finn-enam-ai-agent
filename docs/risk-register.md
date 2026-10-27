# FINN — Risk Register

Updated 2026-10-27 (Prompt 2). Ordered by priority (likelihood × impact, our judgment). Δ shows the change since Prompt 1. No risk has been removed.

| # | Risk | L | I | Δ / evidence | Early warning | Mitigation (status) |
|---|---|---|---|---|---|---|
| R1 | **Not enough time** (≈4.5 days) | H | H | Unchanged. The data spine took most of day 1 | M3 not deployed by Thu night | Hard scope freeze; deploy on day 3 (planned) |
| R2 | NSE blocks the deployment host's IP | H | H | **Still untested.** Works locally without cookies [E] | 401/403 from host in the first smoke test | Offline replay + raw cache implemented [E]; committed snapshot (ADR-014, planned) |
| R3 | No LLM key / quota | **H** | M | Credentials still absent [E]. Impact lowered: the numbers path needs no LLM [E] | — | No-LLM mode implemented and tested [E]; needs a key to test extraction at all |
| R4 | Wrong financial number shown | M | H | Lowered by 44/44 golden matches [E], but a **new failure class was found**: filer XBRL mis-tagging (R15) | Integrity check `fail`/`warn` | Golden tests, integrity identities, bank mis-tag detector (implemented) |
| R5 | Promise Ledger noisy or fabricates quotes | M | H | Quote gate + speaker attribution 10/10 on real text [E]; no model output tested yet | Quote-reject rate >10% on real LLM output | Exact/normalised-only matching (ADR-013); analyst filter; deterministic verdicts |
| R5b | **Promise Ledger too sparse to impress** | **H** | M | **New.** Only 1 of 10 real statements is checkable against XBRL today. TCS/HDFCBANK guide mostly in aspirations | <3 checkable items for a demo company | Feature POLYCAB-style guiders; surface "not reaffirmed" and "unverifiable" as findings; add segment / working-capital actuals only if cheap |
| R6 | Free-host cold start | M | M | Unchanged | >10s first load | Snapshot reads (planned) |
| R7 | screener rate limit / HTML change | **L** | **L** | **Lowered**: screener is now off the critical path (ADR-005). 429 at 1.2s [E]; 8s spacing worked [E] | — | Throttle 8s (implemented); NSE is primary |
| R8 | Scanned PDFs | L | M | Lowered: 0/7 scanned [E] | `looks_scanned()` true | Mark unparseable (implemented); no OCR |
| R9 | Unseen-ticker research too slow | L | M | Lowered for numbers: ≈4s [E]. Transcripts + LLM latency unmeasured | >60s | Background task only if measured |
| R10 | Banks break the template | M | L | Handled for one bank [E]; NBFC/insurer untested | Missing tags | Bank metric set (ADR-008); NBFC to test |
| R11 | Looks like generic AI output | M | H | Unchanged | Prose-heavy screens | Numbers-first cards |
| R12 | AI build history missing | L | H | Unchanged | — | Export sessions daily |
| R13 | ToS / redistribution | L | M | Raw data git-ignored; only small real fixtures committed; Yahoo trimmed to 30 bars [E] | — | ADR-015 |
| R14 | Secrets leaked | L | H | `.gitignore` covers `.env*`; `.env.example` has empty values [E] | — | Scan before first push |
| R15 | **Filer XBRL mis-tagging beyond the detected pattern** | M | H | **New.** HDFCBANK tagged minority interest as an exceptional item in 2 of 3 quarters [E]. Other patterns surely exist | Integrity `fail`; YoY jumps that don't match the PDF | Integrity identities on every filing (implemented); show the warning; spot-check 3 more companies against PDFs |
| R16 | **Intraday bar treated as EOD** | L | M | **New**, now mitigated [E] | — | `provisional` flag + exclusion (implemented, tested) |
| R17 | **20% of filings unclassifiable from headline** | H | M | **New** [E] (17/87) | "needs review" bucket large in demo | PDF first-page keyword pass; LLM only if a key arrives |
| R18 | **Transcript history unverified** (only latest quarter fetched) | M | H | **New** [A] | Fewer than 4 calls retrievable for a demo company | Fetch 4 quarters for 3 companies first thing in Prompt 3 |
| R19 | **Results season timing**: some portfolio names have not reported Q2 FY27 yet (BEL, CAMS latest is Jun-26) | — | L | **New** [E]. It's an opportunity: live results land during evaluation week | — | Card always states the period; ingest on schedule |
| R20 | Model choice / cost routing undecided | M | M | **New.** Default `claude-opus-5-5`; Haiku 5.5 is ~40× cheaper per listed price | — | User decision (ADR-009) |
