# FINN — Architecture Decision Records

ADR-001 to 004 are carried over from `architecture.md` (Prompt 1). Entries from ADR-005 on are new in Prompt 2 and were driven by evidence.

| ADR | Date | Decision | Evidence | Status |
|---|---|---|---|---|
| 001 | 10-27 | Results numbers from NSE XBRL, not LLM PDF reading | 44/44 golden values reproduced | **Kept, amended by 006/007** |
| 002 | 10-27 | Management bio from the filing, not LinkedIn | — | Kept; sampling still to do |
| 003 | 10-27 | No vector DB / embeddings | Transcripts 17–29 pages; AR is the only large document | Kept |
| 004 | 10-27 | LLM work at ingest only | — | Kept; implemented in `CachedExtractor` |
| 005 | 10-27 | **NSE is the source for transcripts and annual reports. screener.in is demoted to cross-check / backfill index** | NSE files transcripts as announcements and lists ARs via `api/annual-reports`. screener 429'd at 1.2s spacing. The TCS transcript is byte-identical on both | **New: reverses Prompt-1 plan** |
| 006 | 10-27 | EBITDA = PBT **before exceptional items** + finance costs + D&A − other income | TCS Jun-26/Sep-25 reconcile only with the pre-exceptional figure | **New: corrects Prompt-1 definition** |
| 007 | 10-27 | XBRL is primary but **not infallible**: integrity identities run on every filing, a known bank mis-tag pattern is detected and corrected with a visible warning, and the signed PDF is the tie-breaker | HDFCBANK Sep-26/Sep-25 PBT off by the minority-interest amount | New |
| 008 | 10-27 | Banks show Total income / NII / PPOP / PBT / PAT. "Revenue" and "EBITDA" are never relabelled for lenders | Banking taxonomy has no revenue/EBITDA concept | New |
| 009 | 10-27 | LLM via the official `anthropic` SDK, imported lazily. Default model `claude-opus-5-5`, configurable by `FINN_LLM_MODEL`. Server-side refusal fallback on. **Open decision for the user:** route bulk guidance extraction to `claude-haiku-5-5` (listed at $0.10/$0.50 per MTok vs $4/$20 for Opus 5.5; skill reference cached 2026-10-06, verify before quoting) | Brief rewards routing (M p.3). The tool guidance used here says not to downgrade models for cost without the user's say-so | New; **needs your decision** |
| 010 | 10-27 | Prices via direct HTTP to Yahoo's chart endpoint, not `yfinance` | Same data; avoids pandas in deploy; intraday-bar issue handled explicitly | New |
| 011 | 10-27 | stdlib `urllib` + content-addressed raw cache (`data/raw/`) for all sources; per-host throttles (screener 8s, NSE 1.5s) | 429 observed; offline replay powers the tests | New |
| 012 | 10-27 | Guidance taxonomy: explicit_numeric / measurable_qualitative / commentary / analyst_claim. Verdicts met / partly_met / missed / pending / **not_reaffirmed** / unverifiable. Numeric verdicts are computed deterministically | TCS: analysts cite "25%+ EBIT exiting FY27" and the CFO does not reaffirm it | New |
| 013 | 10-27 | Quote validation is exact or reversible normalisation only (NFKC, "Ư"→ff, whitespace, hyphen spacing). **No fuzzy similarity** | A paraphrase must fail (`test_paraphrase_is_rejected`) | New: replaces the "≥0.95 similarity" rule in the evidence standard |
| 014 | 10-27 | Deployment reads a committed SQLite snapshot built by local ingest. Live refresh is best-effort | Host access untested; NSE datacentre blocking is a known risk | Proposed; verify in Prompt 3 |
| 015 | 10-27 | Raw source files are **not** committed (git-ignored `data/raw`). Only small real fixtures for tests (public exchange filings; Yahoo trimmed to 30 bars) | Redistribution caution | New |
