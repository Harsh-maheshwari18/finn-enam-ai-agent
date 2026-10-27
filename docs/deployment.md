# FINN: Deployment (Render Free)

**Status 2026-10-27: deployed** at https://finn-api-9z4q.onrender.com. First deploy: commit `c9ccac0`, snapshot `3c15b9d5…`. Smoke test from outside: every endpoint gave the expected status; POST 405; first request after idle took 23.6 s (an observation; Render's suspension was not checked in its logs), later ones 0.34–0.45 s.

**Redeployed 09:16 UTC:** commit `ec315b3` (timestamp fix), snapshot `ff4868ac…`. Live at about 20 s after the push. `/health`: `verified: true`, 22 companies. Checked live: TCS revenue `73188.00`, all 4 TCS `published_at` values end in `+05:30`, and POLYCAB transcript `broadcast_at` values end in `+05:30` (Q2 FY27 `2026-10-19T16:39:28+05:30`). The 404/405 responses were not re-checked after the redeploy; that code did not change.

**Connectivity from Render, measured:** two probes from Render (`finn-api-9z4q`, Singapore), both all four checks 200 and parsed:

| Probe (UTC) | Commit | NSE announcements | NSE results listing | NSE archives XBRL | Yahoo chart |
|---|---|---|---|---|---|
| 08:29:57 | `c9ccac0` | 1,232 ms, 19 filings / 30 days | 188 ms, 14 filings | 124 ms, 280 facts | 45 ms, 5 bars |
| 09:17:49 | `ec315b3` | 827 ms, 19 filings / 30 days | 197 ms, 14 filings | 200 ms, 280 facts | 53 ms, 5 bars |

Two samples, 48 minutes apart, on one day: they show the Render IP was not blocked at those moments, not that it never will be.

**Tests at the deployed commit:** 254 passed offline; `python -m finn.snapshot verify` OK (`ff4868acfaa6c15c` recomputed, stored and in the manifest).

**Cold start:** one earlier observation and one controlled measurement, on different deploys; neither was repeated.
- First deploy (`c9ccac0`), **observation**: 23.6 s for the first request after idle. Render's logs were not checked,
  so a suspension before that request is not confirmed.
- `6ccb298` deploy, **measurement**: **32.81 s, HTTP 200**, `verified: true`. Render's logs confirm the instance was
  stopped while idle and a new one started for the request. See "Cold start (measured …)" below.

Any frontend must show a loading state for this, and the URL should be opened once before a demo.

## Remaining limitations (2026-10-27)
- **NSE access from Render:** two passing samples on one day. Long-run, rate- or time-dependent blocking is unmeasured.
- **Manual PDF verification:** 3 of 22 companies (TCS, HDFCBANK, POLYCAB; 44/44 values) are checked against signed results PDFs. The other 19 are checked by arithmetic identities and the screener cross-check only.
- **Regrouped comparatives** are disclosed, not corrected (BAJFINANCE YoY 21.64% as filed vs 22.79% like-for-like).
- **Promise Ledger:** not validated. 12/12 transcripts are available and readable, but guidance has been labelled for the latest quarter only (10 statements, 1 numerically checkable); the other 9 transcripts have no extraction, and no LLM is called.
- **Snapshot freshness:** as of 2026-10-27; 17 of 22 companies' latest filed quarter is Jun-26.
- **Frontend:** deployed (see Phase 4 below). Tested in headless Chromium at 360×780 only; no real phone, no Lighthouse.
- **Inbox freshness:** the inbox ends at the snapshot build (filings to 27 Oct 15:22 IST, prices EOD 26 Oct); it is
  not live until the snapshot is rebuilt and pushed.
- **`FINN_CORS_ORIGINS` is outside the Blueprint:** it is set by hand; if `finn-web` is ever recreated with a new
  URL, it must be updated by hand.

## Phase 4: web app (**deployed and verified 2026-10-27**)

| Service | URL | Deploy (all commit `75689df`) |
|---|---|---|
| `finn-web` (Render static site, CDN) | **https://finn-web-q1bw.onrender.com/** | `dep-dbg7r3mc6qcc73ek91s0`, live 10:32:11 UTC (Blueprint sync) |
| `finn-api` (Render Free web service) | https://finn-api-9z4q.onrender.com/ (also serves the same app at `/`) | `dep-dbg7vg142hec73ds744g`, live 10:41:49 UTC (env change) |

What happened, in order:
1. `e63fea8` (Phase 4) deployed to `finn-api` by the push; `finn-web` was **not** created and `FINN_DIAG_TOKEN`
   stayed unset, and a manual Blueprint sync failed. **Cause: unconfirmed.** Render's own sync error message was
   not retrieved (the Render integration has no Blueprint tool). The likely cause is a defect that was confirmed
   locally: `render.yaml` was not valid YAML. The static `buildCommand` was a plain YAML scalar containing `apiBase: "%s"`,
   and `: ` inside a plain scalar is a mapping indicator (PyYAML: `mapping values are not allowed here`, line 38
   col 57). Supporting evidence: the next push changed only that line, and its Blueprint sync succeeded.
2. `75689df` turned it into a `>-` block scalar. The fixed file parses and passes Render's published schema
   (`render.com/schema/render.yaml.json`) with 0 errors. The push triggered a Blueprint sync that created
   `finn-web` (assigned `finn-web-q1bw`) and generated `FINN_DIAG_TOKEN` on `finn-api`; `finn-api`'s plan,
   region and commands were unchanged.
3. `FINN_CORS_ORIGINS` was set to exactly `https://finn-web-q1bw.onrender.com` through the Render integration
   (merge, not replace). A Blueprint sync does not set it: `sync: false` values are prompted only when a Blueprint
   is first created. `finn-web.onrender.com` belongs to an unrelated site, so the origin was read from Render,
   not guessed.

| Env var (`finn-api`) | Value | Purpose |
|---|---|---|
| `FINN_CORS_ORIGINS` | `https://finn-web-q1bw.onrender.com` (set by hand, not by the Blueprint) | Exact-match CORS allowlist; never `*`, never guessed |
| `FINN_DIAG_TOKEN` | generated by Render (dashboard only; never printed) | Required header for the live probe; unset = probe disabled |
| `FINN_CORS_DEV` | unset | Development only: allows localhost origins |

### Live checks (2026-10-27, 10:31–10:45 UTC)
- `finn-api /health`: 200, `ok`, version 0.3.0, commit `75689df`, digest `c4e9ab86424773ec…`, `verified: true`,
  schema 2.
- `finn-web`: `/` 200 with the four headers from `render.yaml` (CSP with `connect-src
  https://finn-api-9z4q.onrender.com`, `nosniff`, `no-referrer`, `no-cache`); all six files 200 at their repo
  sizes; the built `config.js` is `window.FINN_CONFIG = { apiBase: "https://finn-api-9z4q.onrender.com" };`.
- CORS (curl): `/api/v1/signals`, `/api/v1/companies` and `/api/v1/companies/TCS/results` return
  `Access-Control-Allow-Origin: https://finn-web-q1bw.onrender.com` for that origin, and **no** CORS header for
  an unrelated origin or for the near misses `…q1bw.onrender.com/`, `http://…q1bw…`, `finn-web.onrender.com`,
  `…q1bw.onrender.com.evil.invalid` and `null`. Preflight `OPTIONS` from the real origin: 204, `GET, HEAD`,
  `Accept`, max-age 600; from an unrelated origin: 403. The app sends only `Accept`, so browsers do not preflight.
- Diagnostics: no token 401, wrong token 401, no CORS header even for the real origin. The authenticated probe
  was **not run** (the token is only in the dashboard).
- Live browser walkthrough of `finn-web` (a separate script, not `tests/test_ui.py`; Playwright Chromium, 360×780,
  mobile, touch): **18/18 checks passed**. Signals (7 cards: 3 high, 4 other ranked, 3 routine folded; top card
  MARUTI M&A), 30-day window (169 cards, 6 results filings), Signal Receipt (BAJFINANCE, published
  `2026-10-19T17:20:38+05:30`, NSE PDF link), results cards (BAJFINANCE labels match the API; TCS revenue
  ₹73,188.00 cr; HDFCBANK keeps bank labels), Research (POLYCAB search, transcripts, honest guidance state,
  unseen ticker), Settings (save sends `move_pct=2.5&volume_x=1.5&lookback=10` cross-origin and persists after
  reload), touch targets ≥ 44 px, no horizontal scroll on any screen. 21 API responses, all 200 with the exact
  allow-origin header. Console errors 0, page errors 0, failed requests 0, HTTP ≥ 400 responses 0. A page on an
  unrelated origin (served by Playwright's router) was blocked by Chromium's CORS policy.
- Not tested: a real phone, Lighthouse, the authenticated connectivity probe.

### Cold start (measured 2026-10-27 on the `6ccb298` deploy)
This measures the deploy of `6ccb298` (`dep-dbg87o29lscs7392nctg`, live 10:59:24 UTC). Any later push, including
a documentation-only one, redeploys `finn-api`; those later deploys were **not** measured.

| Step | Time (UTC) | Source |
|---|---|---|
| `6ccb298` instance live | 10:59:24 | Render deploy record |
| Last request from us before the measurement | ≈ 10:43:51 (live walkthrough) | our script log |
| Render stops the idle instance (`Handling signal: term`) | 11:14:24, 15 min after going live | Render app log |
| The one timed request sent (`GET /health`, curl) | 11:18:03.5 | our clock |
| New instance starts gunicorn | 11:18:25.7 | Render app log |
| Request served on the new instance | 11:18:38.4 | Render access log |

Result: **HTTP 200 after 32.81 s** (time to first byte; connect 0.16 s). Body: `ok`, commit `6ccb298`,
digest `c4e9ab86424773ec…`, `verified: true`, schema 2. The service had been idle for 18 min 39 s since going
live, and was asleep for 3 min 39 s before the request. Only Render's own internal health checks reached it
between 10:59 and 11:14; they did not keep it awake. Our clock and Render's differ by about 2 s, so use the
curl durations, not differences between the two clocks.

One sample, from one network. It is slower than the 23.6 s first-deploy observation, which makes the 45 s app
timeout about 1.4× the slowest observed wake. Only the API was timed, not the browser; the static site's own
files come from Render's CDN and do not sleep.

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
