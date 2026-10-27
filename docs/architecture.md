# FINN — Architecture

Status: v0.2 (2026-10-27). **Superseding decisions from Prompt 2 testing are in `architecture-decisions.md` (ADR-005 to ADR-015). Where they conflict, the ADRs win.** Summary of the changes: NSE (not screener) supplies transcripts and ARs; prices via direct Yahoo HTTP; EBITDA before exceptional items; bank metric set; official `anthropic` SDK, imported lazily; stdlib HTTP with a raw cache.

[F] verified · [A] assumption · [P] proposal

## 1. Shape: one Python service, one SQLite file, one static front end

```
                    ┌─────────────── ingest (CLI + scheduled) ────────────────┐
 Yahoo chart API ──►│ prices adapter ─┐                                        │
 NSE announcements ►│ filings adapter ├─► classify (rules → cheap LLM fallback)│
 NSE integrated    ►│ results adapter ├─► metrics (deterministic) ────────────┤──► SQLite (finn.db)
   iXBRL           │                 │                                        │      + raw doc cache
 screener.in docs ►│ docs adapter ───┴─► transcript text → guidance extract ──┤        (content-hashed)
 (transcripts/AR)  └─────────────────────────────────────────────────────────┘
                                                │
                       FastAPI (read API + on-demand ingest for new ticker)
                                                │
                     Mobile-first web app (static, served by same FastAPI)
```

No queues, no microservices, no vector DB, no agent framework. Each was considered and rejected because there is no concrete need at ~25 companies × ~5 documents.

## 2. Technology choices

| Concern | Choice [P] | Why | Simpler alternative | Risks / limits | External dependency & cost |
|---|---|---|---|---|---|
| Language/back end | **Python 3.12 + FastAPI** | Python is installed [F]; best PDF/XBRL/finance libs; brief points at yfinance | Flask | None material | Free |
| Storage | **SQLite** (single file, committed snapshot for demo) | Zero-ops; ships with the deploy; snapshot guarantees a working demo | JSON files | Concurrent writes (irrelevant at this scale) | Free |
| Prices | **Yahoo chart endpoint via `yfinance`** (or direct HTTP, verified) | Brief recommends it (M p.2); verified reachable [F] | NSE bhavcopy CSV | Unofficial, can rate-limit/break [A] | Free |
| Announcements | **NSE `api/corporate-announcements`** | Verified JSON with PDF links [F] | BSE (blocked [F]) | NSE may block datacentre IPs [A]; undocumented API | Free |
| Results | **NSE `api/integrated-filing-results` iXBRL** (+ older XBRL endpoint for history) | Primary, machine-readable, consolidated flag [F]; avoids LLM number extraction | Parse results PDF with LLM | Format variations (banks/NBFC taxonomy) [A]; history needs older endpoint | Free |
| Fundamentals docs | **screener.in document links** → PDFs (BSE/company IR) | Brief points here (M p.2); verified links [F] | Company IR sites | HTML scraping fragility; ToS sensitivity: low-volume, cached, polite UA | Free |
| PDF text | **pypdf** (fall back to pdfplumber for tables) | Pure-Python, light | — | Scanned PDFs have no text → mark "unparseable" | Free |
| LLM | **Provider-agnostic thin wrapper** (`finn/llm.py`). Default: a cheap/fast model for classification & guidance extraction; a stronger model only for guidance↔actual matching. Candidates: Claude Haiku 5.5 / Sonnet 5.5, or Gemini Flash free tier | Brief rewards routing and free tiers (M p.3) | Single model for everything | **No key present [F]**; quota exhaustion during demo → all LLM output is precomputed at ingest, never at page view | Pricing/limits: **verify on provider pages in Prompt 2, do not quote from memory** |
| Structured output | **Pydantic schemas + JSON mode / tool-use**, validate, 1 retry, else store `extraction_status=failed` | Required by evidence standard | Regex parsing | — | — |
| Retrieval | **Section/page chunking + BM25 (rank_bm25) or keyword filter**; no embeddings | Transcripts are small; guidance lives in predictable sections; explainable | Embeddings + vector store | Misses paraphrased guidance → mitigated by extracting per full transcript with a cheap model | Free |
| Front end | **Static mobile-first SPA: HTML + Alpine.js (or Preact via ESM CDN) + hand-written CSS**, no build step | Node is **not installed** [F]; zero-build ships fastest from the same FastAPI process | Jinja + htmx | Less component ergonomics than React; acceptable at 4–5 screens | CDN only |
| Deploy | **Render / Railway / Fly free tier (one container)** [Q: pick in Prompt 2 after testing outbound access to NSE] | One URL, one process | Hugging Face Spaces | Cold starts on free tiers (~30–60s) [A] → keep-warm ping or paid-tier day | Free tier |
| Scheduling | **GitHub Actions cron** running `finn ingest` and committing the snapshot, or run locally and push | No server-side scheduler needed | Manual run before demo | Actions IPs may also be blocked by NSE [A] → local run is the fallback | Free |

## 3. Module layout [P]

```
finn/
  config.py          # portfolio, thresholds defaults (only place tickers appear)
  adapters/
    prices.py        # yahoo → PriceBar
    nse_filings.py   # announcements → Filing
    nse_results.py   # integrated iXBRL + legacy XBRL → ResultFacts
    screener_docs.py # doc index → DocumentRef (transcripts, ARs, PPTs)
    http.py          # shared session: UA, retries, timeouts, raw-cache by URL+hash
  classify.py        # NSE 'desc' + text rules → category; LLM fallback for ambiguous
  metrics.py         # unit normalisation, EBITDA derivation, QoQ/YoY, period alignment
  signals.py         # ranking, thresholds, alerts, signal receipts, folding
  guidance.py        # transcript → GuidanceItem (LLM) ; match to actuals (deterministic + LLM judge)
  people.py          # mgmt-change filing → PersonProfile (LLM extract from filing text)
  llm.py             # provider wrapper, schema validation, content-hash cache, token log
  store.py           # SQLite schema + queries
  api.py             # FastAPI routes
  cli.py             # finn ingest [--symbols] | finn research SYMBOL
web/                 # index.html, app.js, styles.css
tests/               # pytest + recorded fixtures (real responses, labelled)
```

## 4. Key data flows

**Push (scheduled ingest → read):**
1. For each portfolio symbol: fetch announcements (window = max user window, 7d) → classify → store `Filing`.
2. For `results` filings: fetch the integrated iXBRL for that quarter. Prior quarter and year-ago quarter come from the store or the legacy XBRL endpoint. Compute metrics → `ResultCard`.
3. For `management_change`: fetch the PDF → extract person/role/effective date/profile → `PersonProfile`.
4. Fetch 60 trading days of prices → compute daily % move and volume ÷ N-day average.
5. `signals.py` scores everything **at request time** from stored facts plus the user's thresholds. It is a pure function, so threshold changes are instant and testable.

**Pull (on demand, cached):**
`GET /company/{symbol}` → if no ingest is in the store, run the research pipeline:
1. Screener doc index.
2. Last 4–5 transcripts plus the latest AR.
3. Extract text.
4. Extract guidance (cheap model).
5. Fetch actuals for the target periods (XBRL).
6. Match (deterministic where the metric and period are numeric; LLM judge only for qualitative items).
7. Store.

Progress streams to the UI (SSE or polling). A second visit costs zero LLM calls.

## 5. Ranking (deterministic, explainable)

`score = base_weight(category) × modifiers`. Example base weights [P, tunable in config, documented]:
- results 100, M&A 90, management_change (CEO/CFO/MD) 85, fund_raise 70, litigation 70, credit_rating 60, pledging 60, capex 55, insider_trading 50, dividend 30, press_release 25, earnings_call 20, investor_meetings 10, agm_egm/postal_ballot 5, unclassified 0.

Modifiers: the user's watched categories ×1.5; same-day price/volume breach on that ticker ×1.3; muted (ticker, category) → 0. Below a fold threshold, an item goes into the "routine" group. Every card stores its **receipt**: the base weight, the modifiers applied, the source timestamp and the data freshness.

## 6. Error handling & freshness

- Each adapter returns `Ok(data, fetched_at, source_url)` or `Unavailable(reason, last_good_at)`. The UI shows reasons literally ("NSE returned 403 at 14:05; showing data from 09:12").
- Raw responses are cached on disk by URL hash, which enables offline replay for tests and demos.
- Data provenance tags: `live` / `cached` / `fixture` / `unavailable`. Fixtures exist only in `tests/fixtures` and are never served by the app.

## 7. Open decisions for Prompt 2
1. Host choice: test outbound NSE access from the candidate host first.
2. LLM provider and key: need the user's key. Verify current pricing and free-tier limits.
3. Front-end library: Alpine vs Preact-ESM. Decide after the first screen.

## 8. ADR log (continued in architecture-decisions.md)
- ADR-001 (2026-10-27): Results metrics come from NSE iXBRL, not LLM PDF reading. Reason: verified machine-readable, primary and cheap.
- ADR-002 (2026-10-27): Management bio sourced from the Reg-30 filing text, not LinkedIn scraping. Reason: ToS and reliability; primary source. [A: profile usually present; verify]
- ADR-003 (2026-10-27): No vector DB / embeddings. Reason: small corpus; explainability.
- ADR-004 (2026-10-27): All LLM work happens at ingest, never at page view. Reason: demo reliability and cost.
