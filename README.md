# FINN — Financial Investment Agent (ENAM AI Engineer Build Challenge)

A mobile-first investor workflow over NSE primary sources: a **Signal Inbox** (push) and a **Research** view with a
**Management Promise Ledger** (pull). Every number and quote links back to the NSE filing or transcript page it came from.

| | |
|---|---|
| **Live app (open on a phone)** | https://finn-web-q1bw.onrender.com/ |
| API health | https://finn-api-9z4q.onrender.com/health (shows the deployed commit and snapshot digest) |
| Repository | https://github.com/Harsh-maheshwari18/finn-enam-ai-agent |

The API runs on Render's free tier: the first request after about 15 minutes idle can take ~30 s while it wakes
(the app shows a "waking the server" state). Open the link once before a demo.

## Push: the Signal Inbox
- **Windowed digest** of NSE announcements across an 18-company portfolio: last 24 h by default, or 3 d, 7 d, 30 d.
  Items are ranked (score = category base + novelty + your watch list, + magnitude for price/volume moves);
  routine categories are folded with a count, not shown in full. Rules: `docs/signal-rules.md`.
- **Triggered alerts** on end-of-day data: price move beyond ±X%, volume above N× its recent average, with the
  threshold, lookback, watch list and muted companies set by you (kept in the browser).
- **Signal Receipt** on every item: why it was surfaced, the evidence, the NSE link, raw IST/UTC times and what is unknown.
- **Results first cut:** Revenue, EBITDA, PBT and PAT, QoQ and YoY, computed from the filed XBRL, with the basis
  (consolidated/standalone) and EBITDA formula stated.

## Pull: Research and the Management Promise Ledger
- **Research:** search the 22 companies in the snapshot; a company page shows the results card, transcript
  inventory, last 30 days of filings and the latest session. An unknown ticker gets an honest "not in this snapshot".
- **Management Promise Ledger** (TCS, POLYCAB, HDFCBANK; 4 earnings calls each): what management committed to,
  what it said later (restated, tightened, softened, delayed, or simply not repeated), and the outcome where the
  filed numbers allow it. 17 records, 71 quotes; every quote is re-checked by the build at its PDF page and speaker,
  with tap-to-source links. Verdicts: 1 not reaffirmed, 9 pending, 7 unverifiable, 0 met or missed. Silence is never
  read as a broken promise, and segment or days targets are never compared with a substitute figure.
  Example: `GET https://finn-api-9z4q.onrender.com/api/v1/companies/TCS/promises`.
- **Review status:** records were selected and labelled by Claude (AI assistant). **Only R01 (TCS 25% exit) has been
  reviewed and accepted by a person** (Harsh Maheshwari, 2026-10-27); R02–R17 have not been reviewed by a person.
  See `docs/promise-ledger.md` and `docs/promise-ledger-human-review.md`.

## How it works
A deterministic build ingests NSE filings, XBRL results, end-of-day prices and transcripts into a committed,
digest-verified snapshot (`snapshot/`). The API (`finn/api.py`, plain WSGI) serves only that snapshot; the frontend
(`web/`) is static HTML/JS. **No LLM is called in the deployed phase** (`FINN_LLM_DISABLED=1`).

API: `/health`, `/api/v1/companies`, `/api/v1/companies/{SYMBOL}/results`, `/transcripts`, `/filings`, `/promises`,
`/api/v1/signals`, and `/api/v1/diagnostics/connectivity` (token-protected live probe).

## Setup
```bash
python3 -m venv --without-pip .venv && python3 -m pip --python .venv/bin/python install -r requirements.txt pytest
.venv/bin/python -m pytest -q                          # offline, real fixtures + committed snapshot
.venv/bin/python -m finn.api 8000                      # app + API on http://127.0.0.1:8000 (or: gunicorn finn.api:app)
.venv/bin/python -m finn.snapshot verify               # recompute the snapshot digest against snapshot/manifest.json
.venv/bin/python -m finn.snapshot build                # live NSE ingest for config/universe.json -> validated snapshot
.venv/bin/python -m finn.promises build                # re-validate the Promise Ledger (needs the cached transcripts)
```
Browser tests (`tests/test_ui.py`) need Playwright and skip without it. Deployment: `render.yaml`, `docs/deployment.md`.

## Known limitations
- **No management-change bio** for incoming executives.
- **No push notifications:** alerts are evaluated in the app, not sent to the phone.
- **No on-demand research for unseen tickers:** the engine is ticker-agnostic, but the deployed app serves only the
  22 companies in the committed snapshot.
- **Promise Ledger covers 3 companies**, and only R01 is human-reviewed.
- **Committed snapshot data** (as of 2026-10-27): the inbox and results do not update until the snapshot is rebuilt and pushed.
- **Free-tier cold start** of about 30 s after idle (one measurement: 32.8 s).
- **LLM disabled** in the deployed phase; all outputs are deterministic.
- Tested in headless Chromium at 360×780; not yet on a real phone.

More: `docs/api-verification-report.md` (financial checks and gaps), `docs/deployment.md` (deploy and cold start).

## Docs
- Architecture: `docs/architecture.md`, decisions `docs/architecture-decisions.md`
- Evidence standard: `docs/data-and-evidence-standard.md`; sources `docs/data-source-matrix.md`; failure behaviour `docs/data-failure-behaviour.md`
- Risk register: `docs/risk-register.md`
- Product and status: `docs/product-spec.md`, `docs/evaluator-scorecard.md`, `docs/frontend.md`, `docs/signal-rules.md`
