# FINN: Transcript Coverage Audit

Run 2026-10-27 from the local development machine. Source: NSE `api/corporate-announcements`, label "Analysts/Institutional Investor Meet/Con. Call Updates", headline containing "Transcript". Searched in 90-day windows from 2025-12-31 (the end of the oldest target quarter) to 2026-10-27. Reproduce with `python -m finn.snapshot build` (the `transcript_audit` list in `config/universe.json`).

**Result: 12 of 12 target quarters available** (4 quarters × TCS, POLYCAB, HDFCBANK). No quarter is missing, and none is scanned or unreadable.

## How each transcript was audited
1. Downloaded the PDF from `nsearchives.nseindia.com` into the git-ignored raw cache. The PDF and its text are **not** committed. The snapshot keeps URL, sha256, size and the metadata below.
2. Extracted text with pypdf, then checked the text layer: a PDF counts as scanned if more than half its pages have fewer than 200 characters.
3. **Quarter from the document's own text**, not from the filing date. Quarter references on the first 5 pages vote; pages 1–2 (the covering letter and the IR opening) count 3×. A close runner-up marks the result ambiguous instead of guessing.
4. Checked that the document is an earnings or results call, not another investor call.
5. Cross-checked against the filing date: the latest quarter that ended at least 7 days before the filing.

## Coverage

| Company | Quarter | Status | Filed on NSE | Pages | Text chars | Speaker turns | Quarter evidence (verbatim, page) | Date cross-check |
|---|---|---|---|---|---|---|---|---|
| HDFCBANK | Q2 FY27 | available | 2026-10-23 | 17 | 54,471 | 82 | "quarter and half-year ended September 30, 2026" (p.1) | agrees |
| HDFCBANK | Q1 FY27 | available | 2026-07-24 | 17 | 54,121 | 76 | "quarter ended June 30, 2026" (p.1) | agrees |
| HDFCBANK | Q4 FY26 | available | 2026-04-24 | 16 | 50,877 | 78 | "quarter and year ended March 31, 2026" (p.1) | agrees |
| HDFCBANK | Q3 FY26 | available | 2026-01-23 | 18 | 57,171 | 99 | "quarter and nine-months ended December 31, 2025" (p.1) | agrees |
| POLYCAB | Q2 FY27 | available | 2026-10-19 | 20 | 54,238 | 97 | "Q2 FY27" (p.2) | agrees |
| POLYCAB | Q1 FY27 | available | 2026-07-20 | 19 | 53,960 | 82 | "Q1 FY27" (p.2) | agrees |
| POLYCAB | Q4 FY26 | available | 2026-05-08 | 19 | 53,689 | 85 | "Q4 FY26" (p.2) | agrees |
| POLYCAB | Q3 FY26 | available | 2026-01-22 | 20 | 52,503 | 111 | "Q3 FY26" (p.2) | agrees |
| TCS | Q2 FY27 | available | 2026-10-14 | 29 | 52,217 | 91 | "quarter and six-month period ended September 30, 2026" (p.1) | agrees |
| TCS | Q1 FY27 | available | 2026-07-15 | 25 | 46,388 | 66 | "quarter ended June 30, 2026" (p.1) | agrees |
| TCS | Q4 FY26 | available | 2026-04-14 | 35 | 57,548 | 65 | "quarter and year ended March 31, 2026" (p.1) | agrees |
| TCS | Q3 FY26 | available | 2026-01-16 | 33 | 48,112 | 60 | "quarter and nine -month period ended December 31, 2025" (p.1) | agrees |

URLs and sha256 for every file: `GET /api/v1/companies/{SYMBOL}/transcripts`, or the `transcript_filings` table in `snapshot/finn_snapshot.db`.

## Findings
- **The same NSE label covers more than earnings calls.** HDFCBANK filed a 14-page transcript on 2026-03-19 of an "Investor Conference Call" about a disclosure the bank made on 2026-03-18. It names no quarter and is kept separately under `other_transcripts`, not counted as a quarter. A date-only rule would have filed it under Q3 FY26.
- **The first detector got TCS Q3 FY26 wrong.** It read "Q2FY26" (a comparison on p.3) as the call's quarter. Three real phrasings defeated its patterns: "nine -month" with a stray hyphen space, "fiscal year FY2026", and "December 31st". These phrases are now regression tests (`tests/test_transcript_inventory.py`).
- **Management-name extraction is weak.** The `MANAGEMENT:` header block is parsed for HDFCBANK and POLYCAB in some quarters (1–5 names) and never for TCS, whose transcripts have no such block. Speaker turns (60–111 per call) are always found. Attributing a statement to a speaker therefore still relies on turns plus the IR introduction, as in the Prompt 2 guidance experiment.
- **Out of scope:** TCS also filed a transcript on 2025-12-23. That is before the oldest target quarter ended, so it cannot be one of these four calls, and it was not audited.

## Limits
- Covers the 3 companies × 4 quarters requested. The other 19 companies in the snapshot have `status: not_audited` in the API.
- Quarter detection has been tested on these 13 real documents only.
- This audit checks availability and readability. It does not check whether the guidance statements inside these transcripts are extracted correctly; that needs the LLM, which this phase does not use.
