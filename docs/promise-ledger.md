# Management Promise Ledger: method and audit

Updated 2026-10-27 (Prompt 5, after the final review). Built offline with no LLM. Snapshot `c4e9ab86…` is unchanged.

## What it answers
For each company: what did management commit to on an earnings call, what did they say about it on later calls, and can the outcome be checked against filed results?

**The ledger is a curated selection, not a complete list.** It holds 17 records chosen by the criteria below from 78 management sentences labelled as commitments or commentary (35 explicit numeric, 14 measurable qualitative, 29 commentary). Statements that were left out are listed in the appendix with a reason.

## Pipeline
| Step | Command | Output | Committed |
|---|---|---|---|
| 1. Candidates | `python -m finn.promises audit` | `data/derived/promise_candidates.json`, which contains transcript sentences | No (git-ignored) |
| 2. Labels | written by hand | `config/promise_audit.json`: hash, page, speaker and label for each candidate. No text. Also the relabel log and the known misses | Yes |
| 3. Records | written by hand | `config/promise_ledger.json`: 17 records with short quotes | Yes |
| 4. Build | `python -m finn.promises build` | `snapshot/promise_ledger.json` | Yes |
| 5. Review pack | `python scripts/promise_review_pack.py` (`--check` to verify) | `docs/promise-ledger-human-review.md`, generated from step 4 plus the hand-written prompts in `config/promise_review_questions.json` | Yes |

## Audit structure
| Layer | Count | What it is |
|---|---|---|
| Candidates | **164** | Sentences from the 12 transcripts that pair a forward-looking word with a financial topic. They are proposals only |
| Audit labels | **164** (one per candidate) | analyst 44 · explicit numeric 35 · measurable qualitative 14 · commentary 29 · actual report 12 · not guidance 30 |
| Known misses | **7** | Real commitments the filter did not propose, found by reading (listed in `promise_audit.json`). Two were found during review preparation on 2026-10-27 |
| Ledger records | **17** | Selected commitments (criteria below) |
| Quotes inside the records | **71** | 17 statements, 46 follow-ups and 8 analyst questions (69 distinct texts). Every one is re-validated by the build. Before the review corrections of 2026-10-27 there were 55 (16, 34 and 5) |

Correction: the final review first described the 15 original records as "50 quotes: 15 statements, 25 follow-ups and 10 analyst questions". The 50 was right, but the split was 15, 30 and 5.

What each category means:
- **Source-backed commitment (a record's statement):** management speech about this company's own future, quoted exactly, at a cited page.
- **Follow-up:** a later (or same-call) management statement on the same commitment. Each carries a stance:
  - **decisive:** `restated`, `tightened`, `softened`, `widened`, `delayed`;
  - **neutral:** `not_restated` (an answer that does not repeat the target), `reported` (management's own progress figure), `explained`.
- **Analyst claim:** an analyst's words. They are never guidance and appear only as the question that prompted a management answer. There are 44 analyst labels.
- **Commentary:** an aspiration or tone with no measurable target. It is recorded but never scored.
- **Excluded candidate:** labelled `actual_report` or `not_guidance`, or a commitment not selected (appendix).

## Selection criteria
A statement becomes a record only if **all** of these hold:
1. Management, not an analyst or the moderator, speaking about **this company's** future, not the industry or the economy.
2. It names a **measurable target**: a metric with a number or range, a dated milestone, or a direction against a named benchmark. Undated aspirations with a number (TCS 26–28%) are kept as commentary so their status is visible.
3. It is an **outcome an investor tracks**: margin, growth, capital spending, balance sheet, shareholder payout, revenue mix or a capacity milestone. How a budget is divided internally is not a separate record.
4. It is **not a restatement or component** of another record. Those become follow-ups.
5. The quote is not withdrawn or contradicted in the same answer.

## Validation (unchanged rules)
The build re-reads each PDF from the raw cache and admits a record only if all of these hold:
- every quote is found on the cited page, exact or after reversible normalisation (`transcripts.locate_quote`, **no fuzzy matching**);
- the quote sits inside a turn of the cited speaker;
- the speaker's role, derived from the same transcript, is management. A question shown alongside an answer must come from an analyst;
- the record's kind agrees with the audit label of its sentence;
- the record states a `scope`.

A record that fails any check is listed in `excluded` and the CLI exits 1. During Phase 5 this caught three wrong page citations in the hand-written records, and they were fixed.

**Speaker roles:**
- **Moderator:** the operator.
- **Analyst:** introduced by the moderator as a questioner.
- **Management:** one of the following:
  - under the `MANAGEMENT:` header;
  - spoke in the prepared remarks, after the moderator opens and before the first analyst;
  - listed under the header of another transcript from the same company.
- **Cover-letter fields:** anything before the first Moderator turn, plus all-caps names. These are never speakers.

The ledger's speaker pattern accepts single-letter initials (`K Krithivasan:`), so TCS turn counts rise from 60/65/66/91 to 74/87/84/104. The inventory counts are unchanged.

### Outcomes, scope and verdicts
- **Outcomes** are computed only for metrics the snapshot holds **with the same scope as the guidance**. Today that is TCS's operating margin = (EBITDA − D&A) / revenue, consolidated: 25.18%, 23.96% and 23.98% (quarters ended Sep-25, Jun-26, Sep-26). TCS states 25.2%, 24% and 24%. A record whose `scope` is not `consolidated` is never computed, even if the metric name matches.
- **Never computed or substituted:**
  - segment margins (the consolidated figure is never used, and a segment EBIT figure is never matched to an EBITDA target);
  - working-capital days (no balance-sheet ratio is substituted);
  - capex, export share, dividend payout, LDR, MSME growth, growth relative to the system, and peer NIM.
- **Verdict precedence:**
  1. A computed met or missed on a reported target period.
  2. **Not reaffirmed**, if management's last *decisive* statement softened, widened or delayed it.
  3. Commentary is always unverifiable.
  4. Pending while the stated horizon is open.
  5. Otherwise unverifiable.

  Neutral stances never establish or clear "not reaffirmed". Silence, and answers that do not repeat the target, are never treated as withdrawal. There are no confidence scores.

## Results
| Company | Records | Not reaffirmed | Awaiting outcome | Can't be checked |
|---|---|---|---|---|
| TCS | 2 | 0 | 1: 25% operating-margin exit by Q4 FY27 (inferred) | 1: 26–28% aspiration |
| POLYCAB | 9 | 1: EHV plant moved from end-CY2026 to FY28 | 6: W&C 11–13% FY30, FMEG 8–10% FY30, capex ₹12–16 bn a year, C&W 1.5× market through FY30, exports above 10% FY30, dividend payout above 30% FY2030 | 2: working-capital days, EPC margin |
| HDFCBANK | 6 | 0 | 2: LDR 85–90% FY27; FY27 "top line" growth faster than the system | 4: LDR 90–96% FY26, FY26 growth in line with the system, MSME about 18–20% (or 21%), margin "change" in two quarters |

No record is met or missed.

## Corrections made in the final review (2026-10-27)
| Item | Before | After | Why |
|---|---|---|---|
| HDFCBANK LDR 85–90% | not reaffirmed (Q4 FY26 "not a constraint" = softened) | **pending** (`not_restated`) | The call that set the range already said "we don't think that we shall be constrained by the CD ratio" (Q3 FY26 p.4, now a follow-up). Not repeating the range is not a withdrawal |
| HDFCBANK FY27 growth vs system | not reaffirmed (two answers = softened) | **pending** (`not_restated`) | Neither answer uses weakening language; they only do not repeat the claim |
| HDFCBANK growth titles | "loan growth" | "'top line' growth" | Management said "top line growth" and, on the same call (p.8), separated it from loan growth. The measure is undefined, so FINN does not choose one |
| HDFCBANK MSME title | 18% to 21% | about 18% to 20% (or 21%) | Shows management's exact words ("18% to 20%, 21%"). The target field keeps the widest reading |
| HDFCBANK margin record title | "to improve relative to peers" | "'You will see that change' in margins over the next two quarters" | Management did not state a direction |
| TCS 25% exit | follow-ups softened, softened | softened, `not_restated` | Only the "uphill task" answer is explicit. The verdict stayed **not reaffirmed** on that statement alone (revised again at review, below) |
| TCS titles | "EBIT margin" | "operating margin" | TCS's prepared remarks say "operating margin"; "EBIT" is the analyst's word |
| POLYCAB W&C 11–13% | — | scope and basis note | Management reports the segment at EBIT (13.3%, 14.2%) and guides on EBITDA. The two are not compared |
| POLYCAB C&W 1.5× | 2 follow-ups | 4 | Added Q4 FY26 p.15 (base is GDP growth, a different benchmark) and Q1 FY27 p.9 (hedged "maybe 2-3 next quarters" horizon) |
| POLYCAB capex | 1 follow-up | 2 | Added the ~90% Cables & Wires allocation (Q4 FY26 p.16) as part of this record |
| POLYCAB dividend payout | not in the ledger | **new record**, pending | Meets every criterion (appendix item 4) |
| POLYCAB working-capital days | target field 45–50 days | target **50–55 days**, as in the statement; 45–50 recorded as the Q4 FY26 tightening | The statement (Q3 FY26 p.5) says 50 to 55 days. Putting the later range in the target hid the original. Verdict unchanged (unverifiable) |
| POLYCAB exports audit note | "The p.5 sentence was missed" | "The p.8 sentence" | The sentence is on Q4 FY26 p.8, which the statement and `known_misses` both cite. No POLYCAB transcript has an export target on p.5 |

### Corrections made during review preparation (2026-10-27)
These were made on the reviewer's instruction while working through the review pack. They are **not** a person's sign-off: every record stayed marked as not yet reviewed by a person (see "Human review" below for R01).

| Item | Before | After | Why |
|---|---|---|---|
| TCS 25% exit | `softened`, `not_restated`; **not reaffirmed** | `not_restated`, `not_restated`; **pending** | "While it's an uphill task, we'll continue to endeavor to inch up on our margins" (Q2 FY27 p.16) is cautionary context: it neither repeats nor revises the 25% target. The risk note (MHP dilution, furlough seasonality, investment priorities, the latest 23.98%), the margin-formula caveat and the inferred Q4 FY27 horizon are kept |
| TCS 26–28% aspiration | statement Q2 FY27 p.15 | statement **Q3 FY26 p.23** (CFO); p.15 becomes a follow-up | The audit note called p.23 analyst-only, but the CFO's answer on that page also states the band. Logged as a known miss. Verdict unchanged (unverifiable) |
| POLYCAB C&W 1.5× | horizon "each full year, no end date"; unverifiable | "each year through FY30", stated; **pending** | Management says "we believe that will continue to happen until FY30" (Q1 FY27 p.18) |
| POLYCAB working-capital days | 3 follow-ups | 7 | Management's reported cycle (27, 25, 15, 11 days) added as `reported`, unchecked. Verdict unchanged (unverifiable) |
| POLYCAB W&C 11–13% | 4 follow-ups | 5 | Added the Q1 FY27 p.12 restatement |
| POLYCAB capex | 2 follow-ups | 3 | Added management's H1 FY27 figure (INR 6.1 bn), unchecked |
| HDFCBANK FY27 LDR 85–90% | 3 follow-ups | 5 | Added the CEO's Q3 FY26 p.8 answer to a direct question about the FY27 range, as two `explained` follow-ups: "a broad range", with "90%" meaning roughly 88% to 91%, and "somewhere around the 90%" being acceptable. Management's reading of its own range, not a revision: the 85–90% target and the pending verdict are unchanged. FY26-only sentences from the same answer stay with the FY26 record |
| HDFCBANK FY26 LDR 90–96% | not in the ledger | **new record**, unverifiable | "We said we will try and be in a range of somewhere between 90% to 96% in the year FY '26, which is what we will be is what we are very confident about" (Q3 FY26 p.6, CEO), repeated on p.8. It meets the same criteria as the dividend record: management speaker, the bank's own ratio, a numeric range with a stated year, an investor-tracked balance-sheet measure, a separate target from the FY27 record, not withdrawn in the same answer. FY26 has closed, FINN holds no loan or deposit figures and no FY26 ratio was found in the later calls, so it is neither met nor missed. Logged as a known miss |
| Every record | — | `scope` field | Scope is explicit and enforced by the build |

### Human review (2026-10-27)
**R01 (TCS 25% exit) was accepted by a person, with the verdict pending.** That decision is recorded in `config/promise_reviews.json` and shown in the review pack. The reviewer is Harsh Maheshwari. The other 16 records are still not reviewed by a person. Claude also made decisions on R02–R17 at the reviewer's request; those are not reviews and are not recorded as reviews. Two changes were applied with the reviewer's approval. Neither changes a verdict:

| Item | Before | After | Why |
|---|---|---|---|
| TCS 26–28% aspiration | horizon "inferred by FINN"; p.27 answer with no question | horizon basis quotes management's "long-term"; p.27 shows Kumar Rakesh's question | Only the absence of a date is FINN's reading. The p.27 answer replies to whether TCS would revise the band |
| POLYCAB exports | 3 follow-ups | 4 | Added management's Q2 FY27 p.16 figure, "still at 5%" (Aditya Nathany), as `reported`, unchecked. The 10% target is still not restated in Q2 FY27 |

The relabelling is logged in `promise_audit.json` (`relabels`, `record_kind_changes`):
- **HDFCBANK Q2 FY27 p.9**, `measurable_qualitative` → `commentary`. This was done while the ledger was being built and was disclosed in the final review. "You will see that change" names no measure, size or direction.
- **Five POLYCAB sentences**, `not_guidance` → `actual_report`, because each describes a reported result:
  - Q3 FY26 p.5 (two sentences): EBITDA margin excluding a one-off, and the quarter's inventory and working-capital position;
  - Q3 FY26 p.7: FMEG growth of 17% YoY;
  - Q3 FY26 p.20: the quarter's growth against industry growth;
  - Q4 FY26 p.7: ninth consecutive quarter of outperformance.

  None of these changes affects which statements became records.
- **Record POLYCAB-cw-growth-1.5x**, kind `measurable_qualitative` → `explicit_numeric`, to match its label when the build began enforcing that rule.
- **Kept after review:** POLYCAB Q1 FY27 p.14, the BharatNet "maybe INR 800 crores to INR 1,000 crores", stays `commentary`. It is hedged twice, and the figure does not follow from the arithmetic stated with it (one third of the INR 4,500 crore execution piece is about INR 1,500 crore).

## Appendix: commitments examined and not made into separate records
| # | Statement (source) | Label | Decision | Reason |
|---|---|---|---|---|
| 1 | POLYCAB "we've given a guidance that we want to spend around 3% to 5% of B2C top-line every year on A&P" (Q3 FY26 p.14, Chirayu Upadhyaya) | explicit numeric | **Omitted** | Criterion 5: the same answer adds "it will be difficult to say that this will be every year". Criterion 3: it allocates an operating cost, and its base ("B2C top-line") is not a reported figure FINN could ever check |
| 2 | POLYCAB "around 90% of that will go into Cable & Wire capacity expansion alone" (Q4 FY26 p.16, Shashank Yagnick) | explicit numeric | **Included as a follow-up** of POLYCAB-capex-12-16bn | Criterion 4: it describes how the Project Spring capex is divided, so it belongs with that record and not as a separate commitment |
| 3 | TCS "our aspiration would be make the right investments and to progressively inch up closer, at least to the FY26 levels" (Q1 FY27 p.23, Samir Seksaria) | commentary | **Omitted** | Criterion 2: an aspiration with no number or date. "FY26 levels" is not stated as a figure, and FINN's snapshot holds only one FY26 quarter. The measurable TCS margin target from the same call (25% exit) is already a record |
| 4 | POLYCAB "...towards our stated objective of exceeding 30% by FY 2030" (dividend payout; Q4 FY26 p.9, Shashank Yagnick) | not a candidate (known miss) | **Included** as POLYCAB-dividend-payout-30 | Meets every criterion. The payout base (which profit) is not stated, and no later mention was found in Q1 or Q2 FY27 |

Other commitment-labelled candidates are restatements already attached to a record as follow-ups. The exceptions are a few minor items not made into records: POLYCAB's ₹60–80 bn five-year capex programme and its "₹6,000 to ₹8,000 crores by FY2030" form (both restate the capex record), the FMEG "1.5x to 2x of industry growth" target, and the W&C "12% to 14%" near-to-mid-term range (noted on the W&C record). They are labelled in `promise_audit.json` and can be promoted later by the same criteria.

## Who audited it
The labels, records, relabels and this selection were written by **Claude (AI assistant)** from the extracted PDF text on 2026-10-27. The build checks quotes, pages, speakers and roles, but **no person has reviewed the judgements** (labels, stances, scopes, selection). The UI and the data both say so. `docs/promise-ledger-human-review.md` sets out every record, with a checklist and a question for the reviewer. It is generated from the ledger. R01 is marked as accepted by a person (`config/promise_reviews.json`); every other record is marked pending.

## Tests
- `tests/test_promises.py`: 35 tests.
  - Committed artefacts: digest and input hashes match, no exclusions, every quote is management speech with a page and an NSE URL, no confidence fields, the TCS series is right, segment and days guidance is never computed, the verdict table holds, the relabel log matches the labels, the HDFCBANK verdicts do not rest on omission, every record has a scope and only consolidated scope is computed.
  - Verdict rules on SYNTHETIC records: neutral stances never withdraw or clear; a segment-scope record with a computable metric name is not computed.
  - API: ok, not_audited, 404, stale, missing.
  - Five tests use the real PDFs and skip without `data/raw`: the build reproduces the committed ledger exactly; the quote check rejects a paraphrase, a wrong page, a wrong speaker and an analyst cited as management; roles; analyst labels against roles; a tampered record is excluded.
  - Review pack: the committed pack equals a fresh generation and contains every quote and page link; only the records in `config/promise_reviews.json` (R01) are marked reviewed, with exactly one overall box ticked each, and a review whose verdict no longer matches the ledger is refused. The working-capital record keeps its original range and shows the reported cycle, the exports note cites p.8, the FY26 LDR record is unverifiable (not missed), the C&W horizon is quoted, and the TCS aspiration starts at Q3 FY26 p.23.
- `tests/test_guidance_llm.py`: a new test pins the Prompt 2 fixture's corrected segment label for the POLYCAB 11–13% band. The 14.37% cases in the band-logic test are kept and marked as synthetic inputs, not POLYCAB outcomes.
- `tests/test_ui.py`: 3 new browser tests:
  - the TCS evidence chain;
  - the POLYCAB segment state (not computed, and 14.37% never shown);
  - the HDFCBANK LDR shown as "Awaiting outcome", with "Not restated" and the original call's CD-ratio remark.

  One existing assertion changed: POLYCAB now expects the ledger instead of "Guidance analysis not yet available". The ITC assertion is unchanged.

## Limits
- Covers 3 companies × 4 quarters. The other 19 companies show "Guidance analysis not yet available".
- A commitment made before Q3 FY26 is seen only if it is restated in these calls.
- "Exit FY27" is read as Q4 FY27, and the UI marks that date as inferred. TCS's own margin definition is not in the snapshot; the formula is justified only by reproducing TCS's stated figures.
- Management's own figures are shown as reported, not checked against filed statements: POLYCAB FY26 capex ₹14.8 bn, exports 5.4% and payout about 27.2%; HDFCBANK MSME 22.3%.
- The candidate filter missed 7 commitments that were found by reading. Recall is below 100%, and the 10/10 figure from Prompt 2 was measured on the set the filter was tuned on.
- The Prompt 2 fixture (`tests/fixtures/real/guidance_experiment.json`) still holds partial page text from 14 transcript pages (TCS 5, POLYCAB 7, HDFCBANK 2), committed in Prompt 2. That predates this phase and is unchanged.
