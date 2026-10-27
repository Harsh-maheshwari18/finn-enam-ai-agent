# FINN: Signal Inbox rules

Code: `finn/signals.py` (ranking), `finn/classify.py` (category), `finn/adapters/prices.py::session_stats` (price/volume).
Tests: `tests/test_signals.py` (rules, on labelled synthetic fixtures) and `tests/test_api.py` (real snapshot).

The inbox answers one question: **what changed, why does it matter, and what evidence supports it?** It is
deterministic. No model reads or summarises anything; every card shows the rule points that produced its score.

## Inputs (all from the committed snapshot; nothing is fetched when the app opens)

| Input | Source | Bound |
|---|---|---|
| Announcements | NSE `api/corporate-announcements`, subject (`desc`) and headline kept verbatim, attachment link | Last 30 days before the snapshot date, all 22 companies |
| EOD prices | Yahoo chart API, daily bars | Last 90 **completed** sessions per company; a bar still open when fetched is never stored |
| Results numbers | The verified results card (`/api/v1/companies/{SYM}/results`) | Attached to a results filing only when its XBRL was published the same IST day |

## Window

24 h (default), 3 days, 7 days or 30 days, **ending at the snapshot's announcement retrieval time**, not at the
viewer's clock. A committed snapshot cannot know about filings made after it was built, so "last 24 h" means the 24
hours it can see. The window start and end are printed under the summary.

## Score

`score = category base + novelty + watch list (+ magnitude for price/volume)`

| Category (from NSE label, then headline rules) | Tier | Base |
|---|---|---|
| Results, M&A | material | 80 |
| Management change | material | 75 |
| Litigation / regulatory action, fund raise | material | 70 |
| Pledge / encumbrance | material | 65 |
| Credit rating, bonus / split | notable | 55 |
| Capex | notable | 50 |
| Dividend | notable | 45 |
| Earnings-call transcript or recording, press release / order | notable | 40 |
| Unresolved ("General Updates" and similar, no rule matched) | needs review | 35 |
| Insider / SAST | routine (folded) | 20 |
| Investor-meeting schedules, AGM/EGM, postal ballot | routine (folded) | 15 |
| Compliance (newspaper ads, ESOP allotments, trading window, certificates) | routine (folded) | 10 |
| Price move: \|close-to-close\| ≥ threshold | material | 65 + 2 per % beyond the threshold (cap 20) |
| Unusual volume: volume ≥ threshold × average | material | 60 + 5 per × beyond the threshold (cap 15) |

- **Novelty +10:** first filing of that category for the company in the stored announcements, when at least 7 days
  of history precede it. Repeats (a second credit-rating letter) don't get it.
- **Watch list +15:** categories the user watches.
- **Mute:** removes a category from the inbox. The count of muted items is shown.
- **Priority:** high ≥ 70, medium 40–69, low < 40. Routine tiers are folded into one expandable row, never deleted.
- **Ties:** newest first.

**Priority ranks attention, not the probability of a price move.** The receipt says so.

## Price and volume rules (defaults from the brief; all configurable in the app)

| Setting | Default | Range |
|---|---|---|
| Daily price move | 5 % | 0.5–50 |
| Unusual volume | 2.0 × average | 1.1–20 |
| Average over | 20 completed sessions | 5–60 |

- Only completed EOD sessions. A session counts inside the window when it closed (15:30 IST) inside it.
- Zero-volume bars never enter an average. A ratio needs at least max(5, lookback ÷ 2) prior sessions; otherwise the
  inbox says the volume rule **cannot be evaluated** for that company instead of guessing.
- Yahoo EOD is not reconciled with the NSE bhavcopy (stated on every price receipt).
- Rules run when the app is opened. **FINN sends no push notifications.**

## Classification changes in this phase

Added after reading the 73 unresolved filings in the snapshot: NSE labels "Action(s) taken or orders passed" →
litigation and "Preferential issue" → fund raise; the headlines "Schedule of meet" and "Outcome of Analyst/
Institutional Investors Meet" → investor meetings; and a fix so "Qualified Institution Placement" matches fund
raise. Everything else that is vague (mostly "General Updates") stays **needs review** rather than being guessed.

## Known limits

- FINN reads the NSE subject and headline, not the attached PDF. A "General Updates" filing can be material
  (RELIANCE: "Proposed Initial Public Offer of Jio Platforms Limited"); it is shown as *needs review*, not hidden.
- Category bases are FINN's judgment, documented here, not a validated model of materiality.
- Snapshot freshness: the inbox is as fresh as the last `python -m finn.snapshot build --refresh-signals`.
