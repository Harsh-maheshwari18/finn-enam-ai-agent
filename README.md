# FINN — Financial Investment Agent (ENAM AI Engineer Build Challenge)

Status: data spine + read-only API over a committed, validated snapshot (Prompt 3). No UI yet. No LLM is called.

```bash
python3 -m venv --without-pip .venv && python3 -m pip --python .venv/bin/python install -r requirements.txt pytest
.venv/bin/python -m pytest -q                          # offline, real fixtures + committed snapshot
.venv/bin/python -m finn.api 8000                      # API on http://127.0.0.1:8000 (or: gunicorn finn.api:app)
.venv/bin/python -m finn.snapshot verify               # recompute the snapshot digest against snapshot/manifest.json
.venv/bin/python -m finn.snapshot build                # live NSE ingest for config/universe.json -> validated snapshot
.venv/bin/python -m finn.cli card TCS --db data/finn.db   # Prompt 2 CLI (local working DB)
```

API: `/health`, `/api/v1/companies`, `/api/v1/companies/{SYMBOL}/results`, `/api/v1/companies/{SYMBOL}/transcripts`,
`/api/v1/diagnostics/connectivity`. Deployment (Render): `render.yaml`, `docs/deployment.md`.

Docs: `docs/` (scorecard, spec, architecture + ADRs, evidence standard, golden set, source matrix, failure behaviour,
transcript coverage, deployment, roadmap, risks).
