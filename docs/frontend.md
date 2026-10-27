# FINN: Mobile web app

`web/`: `index.html`, `styles.css`, `app.js` (ES module), `config.js`, `icon.svg`, `app.webmanifest`.
No framework, no build step, no runtime dependencies. About 700 lines of JavaScript.

## Architecture decision (ADR-025)

| Option | Verdict |
|---|---|
| React/Vite or similar | Rejected: needs Node (absent on the dev machine), a build, and dependencies to pin; nothing here needs a virtual DOM |
| **Plain ES module + hash routes** | **Chosen**: one file to read, works from any static host, testable in a real browser |

Two ways to serve the same files, both live:

1. **Same origin as the API.** `finn/api.py` serves `web/` at `/` (fixed allowlist of file names, no directory
   traversal, strict Content-Security-Policy). No CORS is involved. Drawback: on Render Free the HTML itself waits
   for the API to wake (measured 23.6 s), so the browser shows its own blank loading screen first.
2. **Static site `finn-web`** (Render static, CDN). The page loads at once and the app shows its own "waking the
   FINN server" state while the API cold-starts. Needs CORS: the API allows exactly the origins in
   `FINN_CORS_ORIGINS`.

## Configuration

| Setting | Where | Default |
|---|---|---|
| API base URL | `web/config.js` → `window.FINN_CONFIG.apiBase` | `""` = same origin. The static site's build writes it from `FINN_API_BASE` |
| Request timeout | `window.FINN_CONFIG.timeoutMs` | 45 000 ms |
| Allowed origins | API env `FINN_CORS_ORIGINS` (comma-separated, exact match) | none, so no CORS headers. **Never `*`** |
| Local dev origins | API env `FINN_CORS_DEV=1` | off. When on, also allows `http://localhost:<port>` and `http://127.0.0.1:<port>` |
| Diagnostics token | API env `FINN_DIAG_TOKEN`, header `X-Finn-Diagnostics-Token` | unset = the live probe is disabled (403). The diagnostics route never sends CORS headers |

## Screens

- **Signals** (home): window 24 h / 3 d / 7 d / 30 d; filters for priority, category and company; ranked cards with
  "why surfaced" points; routine filings folded; empty state; freshness line ("Snapshot … · filings to … ·
  prices EOD … · not live").
- **Signal Receipt** (`#/signal/{id}`): what happened (verbatim headline and NSE subject), why FINN surfaced it
  (score parts), company and period, supporting numbers or the price calculation, evidence (filing link, listing
  URL, publication time IST with the raw `+05:30` value, retrieval time UTC with the raw `+00:00` value,
  provenance, sha256), and what FINN doesn't know.
- **Research** (`#/research`, `#/company/{SYM}`): search by ticker or name; company identity (NSE name, sector =
  FINN grouping); latest results card from the API (values, QoQ/YoY with the base values, derived badges and
  formulas, notes, integrity checks, comparison basis, filed vs retrieved time); transcript inventory; a
  **"Guidance analysis not yet available"** panel; NSE filings for the last 30 days; last completed session.
- **Alert rules** (`#/settings`): price %, volume ×, lookback, watch and mute categories, which companies are
  in the inbox. Stored in `localStorage` (`finn.settings.v1`), wrapped in try/catch, so a browser that blocks
  storage still works for the session.

## Loading and failure states

| Situation | What the user sees |
|---|---|
| Request in flight | Spinner and elapsed seconds; after 4 s, "Waking the FINN server… about 24 s when measured" |
| No answer in 45 s | "The server is taking too long", plus Retry |
| Network failure | "Can't reach the FINN server… a connection problem, not an empty result", plus Retry |
| 429 | "Too many requests", plus Retry |
| 5xx | "The server had a problem (HTTP n)", plus Retry |
| 404 ticker | The API's reason, plus how to add the company to a snapshot |
| A refresh fails after earlier data loaded | Earlier data stays on screen, with a "Refresh failed… showing data loaded at …" banner |
| No events | "No material events in this window… a checked result, not a loading failure" |

Changes are shown with a direction glyph (▲ ▼) and no green/red: a large change is not labelled good or bad
without context.

## Tests

`tests/test_ui.py` runs the real app in headless Chromium at **360 × 780 CSS px** against the real WSGI app and
the committed snapshot. Failures are injected by intercepting requests in the browser. Covers: inbox loads real
cards; window and filters change the records; empty state; network failure then retry; 429/500/503; slow-server
wake-up; receipt timestamps and source link; Ind-AS and bank labels not relabelled; transcripts and guidance
states; unsupported ticker; settings persist and drive the request; no horizontal scroll on every screen; touch
targets ≥ 44 px.

Playwright is a dev-only tool, not in `requirements.txt`. The tests skip, with the reason, when it is missing.

```
pip install playwright==1.48.0 && python -m playwright install chromium
python -m pytest tests/test_ui.py
```

On WSL without root, Chromium's missing libraries (`libnss3`, `libnspr4`, `libasound2t64`) can be unpacked with
`apt-get download` + `dpkg-deb -x` and passed via `LD_LIBRARY_PATH`. That is how these tests were run.
