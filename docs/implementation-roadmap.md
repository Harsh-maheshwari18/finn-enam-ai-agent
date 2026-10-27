# FINN — Implementation Roadmap (27 Oct → 1 Nov 2026)

Time available: about 4.5 days. Internal deadline: **submit Sun 1 Nov 12:00 IST** (official time of day unstated).
Rule: Tier 1 must be deployed and working by the end of **Fri 30 Oct**. Saturday is for the differentiator polish, unseen-ticker proof and the write-up, not for new plumbing.

## F. Scope freeze

### Tier 1 — Must work
| Feature | User value | Depends on | Complexity | Failure modes | Acceptance |
|---|---|---|---|---|---|
| Ingest: announcements, prices, results iXBRL for 18 tickers | Everything | NSE/Yahoo reachability | M | IP block, schema drift | `finn ingest` populates the DB for ≥16/18 tickers; failures logged with reason |
| Deterministic metrics: Rev/EBITDA/PBT/PAT, QoQ/YoY | S4 "example we love" | iXBRL + prior quarters | M | Basis mix, unit errors, missing comparatives | Golden tests on 5 companies match filings; n/m rules tested |
| Classifier (rule map + LLM fallback) | Prioritisation | NSE `desc` | S | Mislabels | ≥90% agreement on a hand-labelled sample of 50 real filings |
| Today screen: window, ranked cards, folded routine, alerts strip | Push core | Ranker | M | Clutter | Real 24h/7d windows render at 360px; routine folded |
| Configurable thresholds (price %, vol ×, lookback, categories) | S2 | prices | S | — | Unit tests + UI change re-ranks without reload |
| Signal sheet with receipt + source link | Trust | store | S | Dead links | Every card opens a source; receipt shows rule and freshness |
| Mgmt-change card with filing-extracted profile | S3 | PDF text + LLM | S | Profile missing | Honest fallback text; tested on ≥3 real filings |
| Company page: Promise Ledger (4 quarters) for ≥3 companies | S6, signature | transcripts, LLM, actuals | L | Extraction noise, period mismatch | ≥4 calls processed per company; audited quotes verbatim; verdicts have calc or reason |
| Search any NSE symbol → company page (or honest partial state) | M5 | full pipeline | M | Slow, missing docs | Unseen ticker works without code change |
| Deployment with committed snapshot | M1 | host | S | Cold start, blocked IP | Link works on a phone with all live sources down |

### Tier 2 — Differentiators (only once Tier 1 is green)
Attention budget slider · Numbers tab (8Q trajectory + margin) · "Ask the transcripts" scoped Q&A with citations · Cash-quality strip from AR (CFO/PAT) · restatement flag · revised-guidance linking · one-line summaries for press releases/orders.

### Tier 3 — Deferred (named in the write-up as deliberate omissions)
Contradiction detector · evidence graph · voice · real push notifications/PWA install · Bull vs Bear prose · LinkedIn enrichment · BSE source · multi-user auth · embeddings/vector DB · full balance-sheet module.

## J. Milestones

| # | When | Objective | Artefacts | Depends on | Acceptance | Dims | Likely blockers | Fallback if it slips |
|---|---|---|---|---|---|---|---|---|
| M0 | Tue 27 Oct | Blueprint + feasibility spike | `docs/*` | — | Docs exist; spike facts recorded | all | — | — |
| M1 | Wed 28 AM | Repo skeleton, adapters, SQLite, recorded fixtures | `finn/adapters/*`, `store.py`, `tests/fixtures` | LLM key not needed | `finn ingest --symbols TCS,POLYCAB` works; tests replay offline | G, I, K | NSE schema quirks | Drop legacy XBRL; use screener quarterly table only as a **labelled cross-check**, not a source |
| M2 | Wed 28 PM | Metrics engine + classifier + ranker | `metrics.py`, `classify.py`, `signals.py` + tests | M1 | Golden tests pass on 5 companies; ranker pure-function tests | E, C, K | Bank taxonomy | Mark lenders' EBITDA n/m; exclude bank-specific lines |
| M3 | Thu 29 | Today screen + signal sheet + settings, deployed early | `web/*`, `api.py`, host config | M2 | Phone test on deployed URL; thresholds re-rank | C, H, I | Host can't reach NSE | Ship a committed snapshot (ingested locally); show freshness honestly |
| M4 | Fri 30 | Transcripts → guidance → actuals → Promise Ledger; mgmt-change profile | `guidance.py`, `people.py`, `llm.py`, company page | M1, LLM key | 3 companies × ≥4 calls; quote validation ≥90% | B, D, E, F, J | Scanned PDFs, quota | Reduce to 3 companies; pick ones with text PDFs; precompute at ingest |
| M5 | Sat 31 AM | Unseen-ticker generalisation + failure states | search flow, partial states, test log | M4 | Unseen ticker run recorded; blocked-source test passes | D, G, I | Live ingest too slow for request | Background job + progress UI; else document CLI run with logged output |
| M6 | Sat 31 PM | Tier 2 picks, polish, density pass | — | M3–M5 | No regressions; 360px check | A, H | Scope creep | Skip Tier 2 entirely |
| M7 | Sun 1 Nov by 12:00 IST | Submission | README, write-up, build history export, email | all | Fresh-phone dry run; checklist ticked | L | Export of AI history | Include session transcripts as markdown in `docs/build-history/` |

## Test strategy
- **Financial arithmetic & period alignment:** pytest golden cases from real filings (recorded), QoQ/YoY with negative and zero bases, mixed basis rejected, lakh/crore conversion.
- **Classification:** labelled sample of 50 real NSE announcements (stored as a fixture) with an agreement metric.
- **Thresholds/alerts:** parametric tests on synthetic price series (labelled synthetic) at the boundaries (1.99× vs 2.0×).
- **Duplicates/missing data:** the same filing appearing twice (NSE re-broadcast) is deduped on `(symbol, attachment URL)`. A missing prior quarter → "—".
- **Traceability:** a test asserts that every API response object with a value has a non-null `source`.
- **Guidance vs outcome:** hand-audited 10 rows per company, with results recorded in the scorecard.
- **Unseen ticker:** a scripted run on a symbol not in `config.py`, with the output log committed.
- **Retrieval failures:** adapters tested against mocked 403/timeout/empty responses; the UI shows the reason.
- **Mobile:** manual check at 360×780 and on a real device. Lighthouse mobile run.
- **Deployment / first use:** open the link on a phone that wasn't used for development, with no login.

## Definition of done (per feature)
The code is merged, tests pass offline, behaviour has been verified on the deployed URL on a phone, the scorecard row is updated with evidence, and known limitations are written down. "Works on my machine" is **In progress**, not Verified.
