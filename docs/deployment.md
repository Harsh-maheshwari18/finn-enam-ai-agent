# FINN: Deployment (Render Free)

**Status as of 2026-10-27: not deployed.** Everything below has been run locally under gunicorn. Nothing has run on Render yet, so **connectivity from Render is untested**.

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
3. Wait for the build. The log should end with `OK recomputed 3c15b9d5437d9589 …` from the verify step.
4. Smoke test, replacing the host:
   ```
   curl -s https://<service>.onrender.com/health
   curl -s https://<service>.onrender.com/api/v1/companies/TCS/results
   curl -s https://<service>.onrender.com/api/v1/diagnostics/connectivity
   ```
   Expected: `/health` shows `"verified": true` and digest `3c15b9d5…`; TCS revenue is `73188.00` with QoQ `1.26`.
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
