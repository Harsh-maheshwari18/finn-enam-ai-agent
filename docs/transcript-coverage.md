# FINN: Transcript Coverage Audit

Run 2026-10-27 from the local development machine; announcement search re-run live with `--refresh` at 08:39 UTC (same 13 filings). Source: NSE `api/corporate-announcements`, label "Analysts/Institutional Investor Meet/Con. Call Updates", headline containing "Transcript". Searched in 90-day windows from 2025-12-31 (the end of the oldest target quarter) to 2026-10-27. Reproduce with `python -m finn.snapshot build` (the `transcript_audit` list in `config/universe.json`).

**Result: 12 of 12 target quarters available** (4 quarters × TCS, POLYCAB, HDFCBANK). No quarter is missing, and none is scanned or unreadable.

## How each transcript was audited
1. Downloaded the PDF from `nsearchives.nseindia.com` into the git-ignored raw cache. The PDF and its text are **not** committed. The snapshot keeps URL, sha256, size and the metadata below.
2. Extracted text with pypdf, then checked the text layer: a PDF counts as scanned if more than half its pages have fewer than 200 characters.
3. **Quarter from the document's own text**, not from the filing date. Quarter references on the first 5 pages vote; pages 1–2 (the covering letter and the IR opening) count 3×. A close runner-up marks the result ambiguous instead of guessing.
4. Checked that the document is an earnings or results call, not another investor call.
5. Cross-checked against the filing date: the latest quarter that ended at least 7 days before the filing.

## Coverage

Filed times are NSE broadcast times (IST, `+05:30`); retrieval times are UTC. **No missing quarters and no duplicates.**

| # | Company | Quarter | Status | Filed (IST) | Pages | Text extraction | Earnings call | Quarter from text (page) | Date check | Speaker turns | Duplicates | sha256 | Retrieved (UTC) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | TCS | Q2 FY27 | available | 2026-10-14T16:00:08+05:30 | 29 | 52,217 chars; text layer | yes | "quarter and six-month period ended September 30, 2026" (p.1) | agrees | 91 | none | `13033ccd2b71…` | 2026-10-27T07:20:59 |
| 2 | TCS | Q1 FY27 | available | 2026-07-15T19:37:13+05:30 | 25 | 46,388 chars; text layer | yes | "quarter ended June 30, 2026" (p.1) | agrees | 66 | none | `c47e71290e80…` | 2026-10-27T07:20:58 |
| 3 | TCS | Q4 FY26 | available | 2026-04-14T20:02:19+05:30 | 35 | 57,548 chars; text layer | yes | "quarter and year ended March 31, 2026" (p.1) | agrees | 65 | none | `5298f07b0181…` | 2026-10-27T07:20:57 |
| 4 | TCS | Q3 FY26 | available | 2026-01-16T16:38:43+05:30 | 33 | 48,112 chars; text layer | yes | "quarter and nine -month period ended December 31, 2025" (p.1) | agrees | 60 | none | `699bbfb4697e…` | 2026-10-27T07:20:55 |
| 5 | POLYCAB | Q2 FY27 | available | 2026-10-19T16:39:28+05:30 | 20 | 54,238 chars; text layer | yes | "Q2 FY27" (p.2) | agrees | 97 | none | `2119d33fa2af…` | 2026-10-27T07:21:08 |
| 6 | POLYCAB | Q1 FY27 | available | 2026-07-20T12:11:37+05:30 | 19 | 53,960 chars; text layer | yes | "Q1 FY27" (p.2) | agrees | 82 | none | `59ed4c668970…` | 2026-10-27T07:21:07 |
| 7 | POLYCAB | Q4 FY26 | available | 2026-05-08T18:59:43+05:30 | 19 | 53,689 chars; text layer | yes | "Q4 FY26" (p.2) | agrees | 85 | none | `ffed5ff85c25…` | 2026-10-27T07:21:06 |
| 8 | POLYCAB | Q3 FY26 | available | 2026-01-22T19:37:01+05:30 | 20 | 52,503 chars; text layer | yes | "Q3 FY26" (p.2) | agrees | 111 | none | `a329cd206e93…` | 2026-10-27T07:21:05 |
| 9 | HDFCBANK | Q2 FY27 | available | 2026-10-23T22:50:22+05:30 | 17 | 54,471 chars; text layer | yes | "quarter and half-year ended September 30, 2026" (p.1) | agrees | 82 | none | `07c34082f55e…` | 2026-10-27T07:21:18 |
| 10 | HDFCBANK | Q1 FY27 | available | 2026-07-24T15:52:03+05:30 | 17 | 54,121 chars; text layer | yes | "quarter ended June 30, 2026" (p.1) | agrees | 76 | none | `d6c19e7d4f74…` | 2026-10-27T07:21:17 |
| 11 | HDFCBANK | Q4 FY26 | available | 2026-04-24T15:44:52+05:30 | 16 | 50,877 chars; text layer | yes | "quarter and year ended March 31, 2026" (p.1) | agrees | 78 | none | `461640336351…` | 2026-10-27T07:21:16 |
| 12 | HDFCBANK | Q3 FY26 | available | 2026-01-23T16:00:19+05:30 | 18 | 57,171 chars; text layer | yes | "quarter and nine-months ended December 31, 2025" (p.1) | agrees | 99 | none | `3013668b1592…` | 2026-10-27T07:21:14 |

Excluded: HDFCBANK 2026-03-19T22:16:04+05:30 14 pp, earnings call=False, quarter named=None, https://nsearchives.nseindia.com/corporate/HDFCBANK_19032026221513_SEintimationTranscriptofearningscall19Mar2026.pdf

URLs and sha256 for every file: `GET /api/v1/companies/{SYMBOL}/transcripts`, or the `transcript_filings` table in `snapshot/finn_snapshot.db`.

## Findings
- **The same NSE label covers more than earnings calls.** HDFCBANK filed a 14-page transcript on 2026-03-19 of an "Investor Conference Call" about a disclosure the bank made on 2026-03-18. It names no quarter and is kept separately under `other_transcripts`, not counted as a quarter. A date-only rule would have filed it under Q3 FY26.
- **The first detector got TCS Q3 FY26 wrong.** It read "Q2FY26" (a comparison on p.3) as the call's quarter. Three real phrasings defeated its patterns: "nine -month" with a stray hyphen space, "fiscal year FY2026", and "December 31st". These phrases are now regression tests (`tests/test_transcript_inventory.py`).
- **Management-name extraction is weak.** The `MANAGEMENT:` header block is parsed for HDFCBANK and POLYCAB in some quarters (1–5 names) and never for TCS, whose transcripts have no such block. Speaker turns (60–111 per call) are always found. Attributing a statement to a speaker therefore still relies on turns plus the IR introduction, as in the Prompt 2 guidance experiment.
- **Out of scope:** TCS also filed a transcript on 2025-12-23. That is before the oldest target quarter ended, so it cannot be one of these four calls, and it was not audited.

## Availability is not guidance quality
These 12 transcripts are **available and readable**. That says nothing about how many measurable, checkable commitments they contain.
- **Prompt 5 (2026-10-27):** all 12 transcripts went through the deterministic candidate filter. That produced 164 candidates, all labelled by hand, and **17 validated ledger records**, a curated selection (`promise-ledger.md`). Only **1** record (TCS EBIT margin) can be computed from filed numbers. The rest need segment, capex, working-capital or banking data that the snapshot does not hold.
- The labels and records were written by Claude from the extracted text and have **not been reviewed by a person**.
- **No LLM is used.** The quote gate (exact or reversible normalisation only) is unchanged.
- The ledger's speaker pattern accepts initials, so `K Krithivasan:` is a turn and TCS turn counts rise to 74/87/84/104. The inventory counts above use the original pattern.

## Limits
- Covers the 3 companies × 4 quarters requested. The other 19 companies in the snapshot have `status: not_audited` in the API.
- Quarter detection has been tested on these 13 real documents only.
- This audit checks availability and readability. It does not check whether the guidance statements inside these transcripts are extracted correctly; that needs the LLM, which this phase does not use.
