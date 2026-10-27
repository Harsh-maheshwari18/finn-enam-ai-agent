# FINN: Deployment (Render Free)

**Status 2026-10-27: deployed** at https://finn-api-9z4q.onrender.com (commit `c9ccac0`, snapshot `3c15b9d5…` verified). Smoke test from outside: every endpoint gave the expected status; POST 405; first request after idle took 23.6 s (cold start), later ones 0.34–0.45 s.

**Connectivity from Render, measured:** 2026-10-27 08:29 UTC, one probe from Render (`finn-api-9z4q`, Singapore, commit `c9ccac0`): NSE announcements 200 (19 filings / 30 days, 1,232 ms), NSE results listing 200 (14 filings, 188 ms), NSE archives XBRL 200 (280 facts, 124 ms), Yahoo chart 200 (5 bars, 45 ms). All parsed. This is a single sample: it shows the Render IP was not blocked at that moment, not that it never will be.

**Pending redeploy:** the timestamp fix and snapshot `ff4868ac…` exist locally only. The live service still serves `3c15b9d5…`, whose `published_at` / `broadcast_at` values have no offset. Push to redeploy (autoDeploy is on).

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
