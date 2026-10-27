# FINN — Financial Investment Agent (ENAM AI Engineer Build Challenge)

Status: data spine only (Prompt 2). No UI yet. See `docs/source-feasibility-report.md`.

```bash
python3 -m venv --without-pip .venv && python3 -m pip --python .venv/bin/python install pypdf pytest
.venv/bin/python -m pytest -q                      # offline, real fixtures
.venv/bin/python -m finn.cli ingest TCS POLYCAB    # live NSE fetch -> data/finn.db (raw cache in data/raw)
.venv/bin/python -m finn.cli card TCS              # results card JSON with sources
.venv/bin/python -m finn.cli prices TCS            # EOD move / volume-ratio alerts
.venv/bin/python -m finn.cli ingest TCS --offline  # cache only; reports what is unavailable
```

Docs: `docs/` (scorecard, spec, architecture + ADRs, evidence standard, golden set, source matrix, failure behaviour, roadmap, risks).
