# FINN — Product Specification

Status: v0.1 (Prompt 1 blueprint, 2026-10-27). Source of truth for requirements: `1. ENAM_AI_Engineer_Build_Challenge_Main.pdf` (cited as **M p.N**) and `2. ENAM_AI_Engineer_Build_Challenge_Reference.pdf` (cited as **R §N**).

Legend: **[F]** verified fact · **[A]** assumption · **[P]** proposal · **[Q]** open question

---

## 0. The constraint that dominates everything

- **[F]** Brief released Tue 27 Oct 2026, deadline Sun 1 Nov 2026 (M p.1). Today is 27 Oct. **That gives about 4.5 working days.**
- **[F]** "Thin-but-working beats broad-but-broken… A demo that doesn't run is the worst outcome." (M p.4)
- **[F]** "We grade creativity, product sense, judgment, and architecture — not completeness." (M p.3)
- **[Q]** The time of day for the deadline and its timezone are not stated. Plan to submit by **Sun 1 Nov, 12:00 IST**.

Every scope decision below follows from this.

---

## A. Brief decomposition

### A1. Mandatory (explicitly required)

| # | Requirement | Source |
|---|---|---|
| M1 | Mobile-first working prototype, easy to try on a phone (deployed link / Expo / responsive web) | M p.1, p.4 |
| M2 | Two interaction modes: **Push** (proactive: what changed, why care) and **Pull** (on-demand research) | M p.1 |
| M3 | Mock portfolio of **15–20** NSE/BSE-listed companies | M p.1 |
| M4 | Ad-hoc research demo set of "say 3–5" companies, which may be outside the portfolio | M p.1 |
| M5 | Research engine must **generalise to any NSE ticker where data is available**; "we may point it at a company you didn't pick" | M p.2 |
| M6 | Pull side grounded in **primary sources only** (annual reports + transcripts); no news, broker notes, or model outside knowledge | M p.3, R §2 |
| M7 | Submit: prototype link, GitHub repo, **AI build history**, short write-up in covering email (what was built, decisions/trade-offs, what was left out, next steps) | M p.4 |
| M8 | Email to assessment@enam.com, subject **"ENAM - IIT screening - 2027"** | M p.4 |

### A2. Strongly signalled (not a checklist, but explicitly valued)

| # | Signal | Source |
|---|---|---|
| S1 | Push "windowed digest": user-chosen window (default 24h), every filing across the portfolio, prioritised, routine items collapsed/hidden | M p.2 |
| S2 | Push "triggered alerts": material announcement types the user cares about; EOD volume > ~2× recent average; price move beyond ±X%; **thresholds configurable** | M p.2 |
| S3 | Management change → background/bio of the incoming person ("two examples we love") | M p.2 |
| S4 | Quarterly results → Revenue, EBITDA, PBT, PAT, QoQ and YoY, from the **actual results filing** ("two examples we love") | M p.2, R §3 |
| S5 | Per-type judgment on what earns attention (one-liner vs. just surfaced at the right priority) — "That judgment is the point" | M p.2 |
| S6 | **Numbers vs. narrative / promised vs. delivered over the last four quarters**, which the brief calls "the kind of thing we value most" | M p.3 |
| S7 | Interaction model with a point of view; "try more than the obvious" | M p.3 |
| S8 | "No AI slop": concise, dense, beautiful, interactive | M p.3 |
| S9 | **Cost efficiency earns bonus points**: model routing, caching, chunking | M p.3 |

### A3. Optional menu (pick, don't do all)
Pull outputs (M p.3): Business snapshot, Financial snapshot, Trajectory, Balance sheet, Cash quality, Narrative vs numbers, Guidance, Bull vs bear. Announcement taxonomy (R §1) is "use, adapt or ignore".

### A4. Explicit non-requirements
- Data plumbing is "plumbing, not the point — don't over-engineer" (M p.2).
- No finance expertise is assumed. Completeness and polish are not graded.
- No official numeric rubric exists. Any weights we use are **our own**.

---

## C. Three competing product concepts

### Concept 1 — "Triage Desk" (inbox-zero for an investor's day)
Push is a **ranked triage queue** rather than a feed. Each item is a compact card with a materiality score and a one-line "why it matters". Routine items fold into a single "14 routine filings" row. Actions are *Dig in* (go to company), *Mute type for this company*, and *Done*. Tapping a card opens an **evidence sheet** (filing link, extracted numbers, calculation). A company page holds the Pull research, whose centrepiece is the guidance ledger.
- Problem solved: filtering. This is the brief's literal thesis (M p.1, "the scarce skill is… filtering").
- Feasibility: high. It is mostly deterministic ranking plus a few LLM calls.
- Risk: it could look like "just a feed" unless ranking and receipts are visibly smart.

### Concept 2 — "Ask FINN" (chat-first copilot)
A single chat surface. "What happened in my portfolio today?" and "Research Polycab" both go through an agent with tools.
- Feasibility: medium. Agent loops are easy to demo and hard to make reliable.
- Risk: **this is the generic AI-finance-chatbot the brief warns against** ("try more than the obvious", "not a model filling a template"). Latency, hallucination, and output that is hard to make dense.

### Concept 3 — "Thesis Tracker"
The investor writes a 3-bullet thesis per holding. Every event and quarterly result is mapped to the thesis pillars it supports or threatens.
- Strongly differentiated, and close to how high-conviction funds actually think.
- Feasibility: low in 4.5 days. It needs thesis authoring UX and event-to-pillar mapping, and a good demo needs seeded theses for 18 companies. Mapping quality is hard to verify.

### Decision matrix (our own 1–5 ratings; no official weights)

| Criterion | Triage Desk | Ask FINN | Thesis Tracker |
|---|---|---|---|
| Fits the brief's core thesis (filtering) | 5: the product *is* filtering | 3: filtering is implicit | 4 |
| Distinctive UX / point of view | 4: inbox-zero triage is opinionated | 2: chat is the obvious default | 5 |
| Feasible by 1 Nov | 5 | 3 | 2 |
| Evidence quality / traceability | 5: deterministic + receipts | 2: provenance gets lost in prose | 3 |
| Demonstrability in 2 minutes | 5 | 3: needs typing and waiting | 3: needs setup explanation |
| Engineering complexity (5 = low) | 4 | 3 | 2 |
| Failure risk (5 = low) | 4 | 2 | 2 |
| Differentiation from generic chatbot | 4 | 1 | 5 |
| **Total (unweighted)** | **36** | **19** | **26** |

**Selected: Concept 1, Triage Desk.** Borrowed elements:
- From Concept 3: the **Promise Ledger** (guidance → outcome), which is a "thesis tracker" built from management's own words. It needs no user authoring.
- From Concept 2: one **scoped question box** on the company page ("Ask the transcripts"), answered only from retrieved chunks with citations. It is Tier 2 and not the primary interface.

**Why not chat-first:** the brief says the best submissions "show a point of view about how an investor should interact". Our point of view is that **an investor's day is a queue to clear, not a conversation to have.** Chat stays as a narrow secondary tool for questions the UI doesn't anticipate.

---

## D. Innovation shortlist

| Idea | User value | Originality | Feasibility (4.5d) | Evidence quality | Demo impact | Verdict |
|---|---|---|---|---|---|---|
| **Promise Ledger**: explicit guidance from the last 4–5 concalls, each matched to the reported outcome (Met / Missed / Pending / Unverifiable) | Very high. The brief calls this the thing it values most | Medium. The concept exists in analyst practice, but auto-built and source-linked is uncommon | Medium. Needs transcript extraction + XBRL actuals | High if quotes are verbatim and actuals deterministic | Very high | **SELECTED (signature)** |
| **Signal Receipt**: every ranked card shows *why* it ranked (rule fired, threshold, data freshness, source, what's uncertain) | High: trust and auditability | Medium | High: falls out of a deterministic ranker | Very high | High | **Adopted as a cross-cutting pattern** (cheap) |
| **Attention Budget**: user sets "max N items/day", ranker fills the budget, the rest is folded | Medium-high: directly operationalises "filtering" | Medium | High | n/a | Medium | Tier 2: a slider on the settings sheet |
| **Primary-source bio**: management-change bio extracted from the Reg-30 filing itself (which normally includes a brief profile) rather than LinkedIn | High: answers "who is this?" with zero ToS risk | Medium. A nice judgement call to explain in the write-up | High **[A: profile is present in most appointment filings; verify on 5 samples]** | High | Medium | **Tier 1** (it's how we satisfy S3) |
| **Contradiction Detector**: narrative tone vs. numbers divergence | High | Medium | Low-medium. Hard to validate and prone to false positives | Low-medium | High *if* correct, embarrassing if wrong | Deferred. The Ledger's "Missed" rows already deliver the honest version |
| **Evidence Graph**: visual graph event → filing → metric → promise | Medium | Medium | Low | High | Medium (graphs are hard to read on mobile) | Deferred. The receipt plus deep links give the same traceability linearly |

**Why the Promise Ledger:** it is the only idea the brief explicitly calls out as the most valued output (M p.3). It cleanly separates evidence (verbatim quote + page), deterministic calculation (actuals from XBRL) and model judgment (the classification). And an evaluator can falsify it in 30 seconds by tapping the quote and opening the PDF page. We claim no novelty beyond "automated, source-linked, honest about unverifiable guidance".

---

## E. Product specification

### E1. Target user
A portfolio manager or analyst at a lean, high-conviction fund. They hold ~18 names, check their phone between meetings, and need to know in under 60 seconds whether anything today needs action. Then, occasionally, they need to go deep on one company before a decision.

### E2. Core screens (each has one job)

1. **Today (Push / Triage)**. Job: "what needs my attention?"
   - Header: window chip (24h ▾ / 3d / 7d / custom), portfolio name, data-freshness dot ("Filings 14:05 IST · Prices EOD 24 Oct").
   - **Alerts strip**: threshold breaches (price ±X%, volume ≥ k× 20-day average, watched announcement types).
   - **Ranked cards**: ticker, category chip, one-line "why it matters", key number. Results cards show the four-metric mini-table inline.
   - **Folded routine row**: "11 routine filings (newspaper ads, compliance certificates…)", which expands.
   - Card actions: open receipt · go to company · mute this type for this company.
2. **Signal sheet** (bottom sheet). Job: "should I believe this?" It has three sections:
   - **Evidence**: filing link, timestamp, extracted fields.
   - **Calculation**: e.g. QoQ = (73,188 − 72,275) / 72,275.
   - **Interpretation & uncertainty**: the model's one-liner, marked as model output, plus what's missing.
   - Results: Revenue / EBITDA* / PBT / PAT × (this Q, last Q, QoQ %, same Q last year, YoY %), with consolidated/standalone labelled. *EBITDA is labelled "derived" with its formula.
   - Management change: person, role, appointed/resigned, effective date, profile extracted from the filing, and a link out to search for them.
3. **Company (Pull / Research)**. Job: "do I still believe in this company?"
   - Tab 1 **Promises** (signature): ledger rows as `[metric] [promised: "…" Q2 FY26 call, p.7] → [actual] [Met / Missed / Pending / Unverifiable]`, plus a summary of how many guidance points were met.
   - Tab 2 **Numbers**: 8-quarter trajectory for Revenue, EBITDA margin and PAT, plus a 5-year annual view (balance sheet / cash conversion from AR-derived tables) — Tier 2.
   - Tab 3 **Sources**: every document used, with retrieval time and parse status.
4. **Settings sheet**: thresholds (price %, volume ×, lookback days), watched categories, attention budget, portfolio editor.
5. **Search**: any NSE symbol → company page (triggers on-demand ingest with a visible progress state).

### E3. End-to-end journey (first-time evaluator on a phone)

1. Opens the link. It lands on **Today**, with a default portfolio preloaded, no login and no setup. A one-line banner explains it: "Your 18-stock portfolio. 4 things need attention in the last 24h."
2. Sees the top card, e.g. a results card with the four headline metrics and the deltas coloured.
3. Taps it to open the **Signal sheet**: evidence, calculation and uncertainty, plus a link to the actual NSE filing.
4. Taps "Open TCS" to go to the **Company → Promises** tab and see what management guided over 4 quarters vs. what happened.
5. Taps a quote to open the source transcript PDF at that page.
6. Goes back to Today, opens **Settings**, changes the volume threshold from 2.0× to 1.5×, and the alert strip updates immediately (deterministic, local).
7. Opens **Search**, types an unseen ticker, and the company page builds live (progress: prices ✓ results ✓ transcripts 3/4 ✓ ledger…), or shows an honest partial state.
8. Failure states are visible and honest: "No concall transcripts found on screener for this company. Promise Ledger unavailable", never an empty or fabricated ledger.

### E4. The two-minute demo (what must work perfectly)
`0:00` Today loads in under 2s from cache → `0:15` results card with real QoQ/YoY → `0:30` receipt + source PDF → `0:50` company Promise Ledger with 4 quarters → `1:20` threshold change re-ranks alerts → `1:40` unseen ticker lands on a company page (pre-warmed **and** one live).

---

## Final quality gate (self-critique as a sceptical ENAM evaluator)

- **What would make it look generic?** A chat box as the home screen; LLM paragraphs summarising every filing; "Bull vs Bear" prose without citations; a dark-mode dashboard with sparklines and no ranking logic. We avoid all four by design, but the risk of the Ledger turning into "LLM wrote some bullets" is real. Mitigation: verbatim quotes, page numbers, deterministic actuals, and an explicit Unverifiable bucket.
- **Strongest evidence of engineering ability:** primary-source XBRL ingestion with deterministic, unit-tested QoQ/YoY and a reconciled EBITDA definition. Also a cached ingest pipeline that degrades honestly when NSE blocks.
- **Strongest evidence of analytical judgment:**
  - Per-category attention rules: what gets a one-liner, what gets folded.
  - Refusing to compute EBITDA for banks.
  - Classifying vague guidance as "Unverifiable" instead of forcing a verdict.
- **Most distinctive, demonstrable innovation:** the Promise Ledger, with tap-to-source quotes.
- **Most dangerous technical assumption:** that NSE endpoints are reachable from the deployment host. They are reachable from this machine **[F]**, but NSE often blocks datacentre IPs **[A]**. Without a pre-ingested snapshot, the deployed app could show nothing.
- **Cut first if behind:** live on-demand ingest for unseen tickers (fall back to "pre-warmed unseen ticker + documented CLI run"). Then the Numbers tab. Never cut the Ledger or the results card.
- **Must work perfectly in the first two minutes:** Today loads with real data; the results card numbers are correct; tap-through to the source works.
- **Could fail even with a beautiful UI:**
  - Stale or empty data because of IP blocking.
  - LLM key missing or quota exhausted on the deployed host.
  - Cold start on a free host (>30s).
  - A wrong number that the evaluator spots against screener.
- **Proof of generalisation:** the code has no ticker-specific branches (grep-able). We also provide a recorded and reproducible run on a ticker outside the demo set, and the live search box.
- **Why this scope:** it covers every "example we love" (S3, S4) and the explicitly most-valued output (S6) with one coherent flow. Everything else is folded into Tier 2/3.

---

## I. Portfolio and source plan

### Availability check (2026-10-27, local machine, `screener` = HTTP status, transcripts = count of transcript links on the screener page)
- **[F]** All 27 candidates have NSE integrated-filing iXBRL results (7–16 quarters each). Latest quarter ended is 30-Sep-2026 for TCS, HDFCBANK, BAJFINANCE, DMART, POLYCAB, PERSISTENT, and 30-Jun-2026 for the rest. **Q2 FY27 results season is in progress**, so new results filings will land during evaluation week. That's good for Push.
- **[F]** Verified transcript counts: TCS 44, HDFCBANK 28, RELIANCE 47, BHARTIARTL 42, ITC 37, LT 66, SUNPHARMA 38, ASIANPAINT 42, POLYCAB 47, DEEPAKNTR 40, PAGEIND 27.
- **[F]** screener returned **HTTP 429** after ~7 requests at 1.2s spacing. Remaining tickers are *unchecked*, not unavailable. Re-check with ≥5s spacing in Prompt 2.
- **[Q]** Annual-report link parsing returned 0 with the current regex. Fix in Prompt 2.

### Proposed portfolio (18) — sector/size mix [P, finalise after re-check]
| Sector | Large cap | Mid/small cap |
|---|---|---|
| IT services | TCS | PERSISTENT, KPITTECH |
| Banks / financials (tests "EBITDA n/m") | HDFCBANK, BAJFINANCE | CDSL |
| Energy / conglomerate | RELIANCE | — |
| Telecom | BHARTIARTL | — |
| FMCG / consumer | ITC, ASIANPAINT, TITAN | PAGEIND |
| Capital goods / infra | LT | POLYCAB |
| Pharma | SUNPHARMA | — |
| Auto | MARUTI | — |
| Chemicals | — | DEEPAKNTR |
| Electronics manufacturing | — | DIXON |

### Ad-hoc research set (4, outside the portfolio) [P]
KAYNES (EMS small-cap), ASTRAL (building materials), LALPATHLAB (diagnostics), HAL (defence PSU). These were chosen for sector diversity and a different disclosure style (a PSU). Transcript availability **is to be verified**. The Promise Ledger demo companies (≥3) will be picked from the verified-rich set: **TCS, POLYCAB, ASIANPAINT** (+ DEEPAKNTR backup).

### Generalisation test
1. **Pre-registered unseen ticker:** an NSE symbol in neither list (e.g. `CAMS` or `BEL`), chosen *after* the engine is frozen. The run is logged to `docs/test-logs/unseen-ticker.md` with timings, sources found, ledger rows and failures.
2. **Live:** the evaluator types any symbol in Search.
3. **Static proof:** a CI check that no ticker string appears outside `finn/config.py` and `tests/`.
4. **Negative case:** a symbol with no transcripts on screener shows an honest partial page (prices + results, ledger "unavailable: no transcripts found").

---

## M. Next step: Prompt 2 objective (not executed)

**Objective:** a working, tested data spine. `finn ingest` pulls announcements, EOD prices and iXBRL results for 3 tickers (TCS, POLYCAB, HDFCBANK) into SQLite. It produces correct Revenue/EBITDA/PBT/PAT with QoQ/YoY, every value carries a `SourceRef`, and the suite runs offline from recorded fixtures.

**Acceptance criteria**
1. `git init`, Python venv, `pyproject.toml`, `.env.example`, `.gitignore` (DB, raw cache, `.env`).
2. Adapters return `Ok`/`Unavailable` with reasons. 403, 429 and timeout are handled and tested with mocks.
3. Quarterly metrics for TCS Q2 FY27 equal ₹73,188 / 18,815 (EBITDA, derived) / 18,638 / 13,934 cr. QoQ and YoY are computed from prior-quarter filings on the same basis.
4. HDFCBANK shows EBITDA `not_applicable` with a reason. There is no crash.
5. Classifier maps NSE `desc` values for a real 7-day sample, and unmapped values are logged.
6. screener doc index fetched with ≥5s throttling and disk cache. The transcript list for TCS and POLYCAB is stored.
7. Availability re-check for all 22 tickers is recorded in this doc.
8. Outbound NSE/Yahoo access tested from the intended host (a deploy smoke test), or the result is reported as Blocked.
9. Scorecard rows E, G, I and K updated with evidence.

**Inputs needed from you:** an LLM provider + API key (not needed until M4, but needed to verify cost and limits), and your preferred hosting account (Render/Railway/Fly/HF Spaces).
