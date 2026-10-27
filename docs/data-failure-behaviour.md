# FINN — Data Failure Behaviour

Principle: **a failure is data.** Every adapter returns either a value with a `SourceRef`, or an `Unavailable(source, reason, url, http_status)` that is stored and shown. Nothing is zero-filled or guessed.

| Situation | Behaviour | Implemented in | Tested |
|---|---|---|---|
| HTTP 401/403/404/429 | No retry in the same run. Serve the last cached copy if any, with reason "live fetch failed (HTTP 429); serving cached copy from <time>". Otherwise `Unavailable` | `finn/http.py` | `test_403_not_retried_and_reported`, `test_stale_cache_served_when_live_fails` |
| Timeout / 5xx / DNS | One retry, then as above | `finn/http.py` | Not executed (logic shared with the path above) |
| Offline mode (`--offline`), cache miss | `Unavailable("offline mode and no cached copy")` | `finn/http.py` | `test_offline_cache_miss_is_reported`; CLI run on an empty cache |
| Symbol not listed / no XBRL | `Unavailable("no XBRL results listed for this symbol")`; card `status: unavailable` | `finn/service.py` | `test_source_unavailable_does_not_crash`; live `NOTAREALCO` |
| Corrupt XBRL | That quarter is reported unparseable; other quarters still render; the affected QoQ/YoY show `missing` | `finn/service.py` | `test_corrupt_xbrl_is_reported_not_raised` |
| Missing XBRL tag | Metric `status: missing` with the tags it looked for; derived metrics (EBITDA) become `missing`, never partial | `finn/metrics.py` | `test_missing_input_makes_ebitda_missing_not_zero` |
| Arithmetic identity fails inside a filing | `integrity: fail` with the difference in crore, shown on the card | `finn/metrics.py::integrity_checks` | 9/9 real filings pass; HDFCBANK mis-tag → `warn` |
| Comparator period missing or misaligned | `qoq/yoy.status = missing / misaligned` with the reason; no % shown | `finn/metrics.py::compare` | `TestPeriods` |
| % change not meaningful (zero base, sign flip) | `zero_base` / `sign_change`; both absolutes shown | `pct_change` | `TestPctChange` |
| Intraday price bar | `provisional=True`; excluded from EOD signals | `finn/adapters/prices.py` | `test_intraday_bar_marked_provisional_and_excluded` |
| Zero volume on a priced bar | `volume_suspect`; excluded from the average; no volume ratio for that day | `prices.py` | `test_zero_volume_excluded_from_average` |
| Fewer than 10 usable sessions | `volume_ratio = None` (no alert), not a guess | `prices.py` | `test_insufficient_history_gives_no_volume_ratio` |
| Announcement with vague label and no rule hit | `category = None, method = unresolved`. It goes to the LLM step if available, otherwise "needs review" at neutral priority | `finn/classify.py` | `test_unresolved_is_not_guessed` |
| Duplicate re-broadcast (new `seq_id`, same PDF) | Earliest kept | `nse_filings.py` | `test_duplicate_attachment_collapsed` |
| LLM: no credentials / SDK missing / rate limit / 5xx / refusal | `LLMResult(status="unavailable")`; ingest continues; guidance shows "not extracted" | `finn/llm.py` | `test_missing_credentials_degrades`, `test_rate_limit_degrades` |
| LLM: malformed JSON or schema violation | One retry, then `invalid`; nothing stored | `finn/llm.py` | `test_malformed_then_valid_retries_once`, `test_schema_violation_twice_is_invalid` |
| LLM: same document again | Cache hit by sha256(prompt version, model, schema, text); zero calls | `finn/llm.py` | `test_unchanged_document_not_resent_changed_document_is` |
| Extracted quote not in source | Rejected (`quote not found in source text`). No fuzzy matching | `finn/guidance.py::admit` | `test_paraphrase_is_rejected`, `test_admit_gate` |
| Scanned PDF | `looks_scanned()` → mark unparseable; no OCR | `finn/transcripts.py` | Not exercised (0 scanned pages in 7 real PDFs) |

## Freshness rules for the UI (to implement in Prompt 3)
- Show `retrieved_at` and `provenance` (`live` / `cached` / `fixture`) per source on every card.
- A cached copy is never labelled live. `published_at` (the filing time) and `retrieved_at` (our fetch time) are shown separately.
- Results filings are immutable, so any cached copy is valid. Listings refresh every 6h, announcements every 15 min, prices every hour (best effort).
