# FINN: Deployment (Render Free)

**Status 2026-10-27: deployed** at https://finn-api-9z4q.onrender.com. First deploy: commit `c9ccac0`, snapshot `3c15b9d5…`. Smoke test from outside: every endpoint gave the expected status; POST 405; first request after idle took 23.6 s (cold start), later ones 0.34–0.45 s.

**Redeployed 09:16 UTC:** commit `ec315b3` (timestamp fix), snapshot `ff4868ac…`. Live at about 20 s after the push. `/health`: `verified: true`, 22 companies. Checked live: TCS revenue `73188.00`, all 4 TCS `published_at` values end in `+05:30`, and POLYCAB transcript `broadcast_at` values end in `+05:30` (Q2 FY27 `2026-10-19T16:39:28+05:30`). The 404/405 responses were not re-checked after the redeploy; that code did not change.

**Connectivity from Render, measured:** two probes from Render (`finn-api-9z4q`, Singapore), both all four checks 200 and parsed:

| Probe (UTC) | Commit | NSE announcements | NSE results listing | NSE archives XBRL | Yahoo chart |
|---|---|---|---|---|---|
| 08:29:57 | `c9ccac0` | 1,232 ms, 19 filings / 30 days | 188 ms, 14 filings | 124 ms, 280 facts | 45 ms, 5 bars |
| 09:17:49 | `ec315b3` | 827 ms, 19 filings / 30 days | 197 ms, 14 filings | 200 ms, 280 facts | 53 ms, 5 bars |

Two samples, 48 minutes apart, on one day: they show the Render IP was not blocked at those moments, not that it never will be.

**Tests at the deployed commit:** 254 passed offline; `python -m finn.snapshot verify` OK (`ff4868acfaa6c15c` recomputed, stored and in the manifest).

**Cold start:** 23.6 s for the first request after idle, measured once on the first deploy. Not re-measured after the redeploy (the service was already warm). Any frontend must show a loading state for this, and the URL should be opened once before a demo.

## Remaining limitations (2026-10-27)
- **NSE access from Render:** two passing samples on one day. Long-run, rate- or time-dependent blocking is unmeasured.
- **Manual PDF verification:** 3 of 22 companies (TCS, HDFCBANK, POLYCAB; 44/44 values) are checked against signed results PDFs. The other 19 are checked by arithmetic identities and the screener cross-check only.
- **Regrouped comparatives** are disclosed, not corrected (BAJFINANCE YoY 21.64% as filed vs 22.79% like-for-like).
- **Promise Ledger:** not validated. 12/12 transcripts are available and readable, but guidance has been labelled for the latest quarter only (10 statements, 1 numerically checkable); the other 9 transcripts have no extraction, and no LLM is called.
- **Snapshot freshness:** as of 2026-10-27; 17 of 22 companies' latest filed quarter is Jun-26.
- **No frontend** is deployed; only the JSON API.

## What gets deployed
A read-only JSON API (`finn/api.py`, plain WSGI, served by gunicorn) that serves the committed snapshot `snapshot/finn_snapshot.db`. Requests never fetch live data and never call an LLM, with one exception: `/api/v1/diagnostics/connectivity` is a deliberate live probe, rate limited to one run per 10 minutes per worker.

| Endpoint | Purpose |
|---|---|
| `GET /health` | Recomputes the snapshot's content digest and compares it with the stored one. 503 if they differ. Render's health check |
| `GET /api/v1/companies` | 22 companies with validation level (`golden_verified` / `integrity_checked`) |
| `GET /api/v1/companies/{SYMBOL}/results` | Results card. Every number carries URL, XBRL context, retrieval time |
| `GET /api/v1/companies/{SYMBOL}/transcripts` | Transcript inventory (metadata only) |
| `GET /api/v1/diagnostics/connectivity` | Live NSE announcements, NSE results listing, NSE archives XBRL and Yahoo chart, from the serving host |

## Configuration (already in the repo)
- `render.yaml`: Blueprint. Free plan, Singapore region, Python 3.12.3, health check `/health`, `FINN_LLM_DISABLED=1`. The build runs `python -m finn.snapshot verify`, so a corrupted snapshot fails the deploy.
- `requirements.txt`: `pypdf==6.21.2`, `gunicorn==23.0.0` (the versions tested locally).
- No secrets are needed. The service has no API keys and none should be added in this phase.

## Manual steps (need your Render account)
1. **Review and push** the Phase 3 changes. Render deploys from GitHub, so the snapshot, `render.yaml` and `requirements.txt` must be on `main`. You asked to review before any push.
2. Render dashboard → **New → Blueprint** → connect GitHub → pick `Harsh-maheshwari18/finn-enam-ai-agent` → Render reads `render.yaml` → **Apply**. If the repo is private, grant Render's GitHub app access to it.
3. Wait for the build. The log should end with `OK recomputed <digest> …` from the verify step, where `<digest>` is `content_digest` in `snapshot/manifest.json` (currently `ff4868acfaa6c15c…`).
4. Smoke test, replacing the host:
   ```
   curl -s https://<service>.onrender.com/health
   curl -s https://<service>.onrender.com/api/v1/companies/TCS/results
   curl -s https://<service>.onrender.com/api/v1/diagnostics/connectivity
   ```
   Expected: `/health` shows `"verified": true` and the manifest's digest; TCS revenue is `73188.00` with QoQ `1.26`; every `published_at` ends in `+05:30`.
5. Send me the connectivity JSON, or the service URL so I can call it. That JSON is the first real evidence of whether NSE and Yahoo work from a cloud host. Each check reports HTTP status, latency, bytes and whether the body parsed. An empty NSE list counts as a failure, because a silently blocked host may get one.

## Free-plan behaviour to expect
- The service sleeps after about 15 minutes idle. The first request after that takes tens of seconds (cold start). Open the URL once before a demo.
- The filesystem is ephemeral. Nothing is written except `/tmp` (the raw-cache path, unused by the snapshot endpoints).

## If NSE blocks the Render host
The snapshot endpoints are unaffected: they never touch NSE. Refresh then stays local: run `python -m finn.snapshot build` on a machine that can reach NSE, commit the new snapshot and manifest, and push. Render redeploys automatically.

## Local run
```
.venv/bin/gunicorn finn.api:app --bind 127.0.0.1:8000     # same start command as Render
.venv/bin/python -m finn.api 8000                         # stdlib dev server, no gunicorn needed
```
Tested 2026-10-27 locally: every endpoint 200 in about 10 ms, POST 405, unknown symbol 404. Connectivity from the dev machine: all four checks reachable and parsed. NSE announcements: 19 filings in 30 days, 873 ms. Results listing: 14 filings. XBRL: 280 facts. Yahoo: 5 bars.
