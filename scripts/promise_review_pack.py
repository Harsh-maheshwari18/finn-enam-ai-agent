"""Write docs/promise-ledger-human-review.md, the human-review pack for the Promise Ledger.

    python scripts/promise_review_pack.py           # regenerate the pack
    python scripts/promise_review_pack.py --check   # exit 1 if the committed pack is out of date

Every fact (quote, page, speaker, kind, scope, target, horizon, verdict, outcome, hash) is copied from
snapshot/promise_ledger.json and config/promise_audit.json; computed margins are recomputed from their inputs.
The reviewer questions, preparer flags and the list of omitted commitments are hand-written and live in
config/promise_review_questions.json. Nothing here records a review outcome: every box is left empty."""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LEDGER = REPO / "snapshot" / "promise_ledger.json"
AUDIT = REPO / "config" / "promise_audit.json"
PROMPTS = REPO / "config" / "promise_review_questions.json"
REVIEWS = REPO / "config" / "promise_reviews.json"   # decisions a person made; the only source of a ticked box
OUT = REPO / "docs" / "promise-ledger-human-review.md"
ORDER = ["TCS", "POLYCAB", "HDFCBANK"]
LABELS = ["explicit_numeric", "measurable_qualitative", "commentary", "actual_report", "not_guidance", "analyst"]
STANCE = {"restated": "restated (decisive)", "tightened": "tightened (decisive)", "softened": "softened (decisive)",
          "widened": "widened (decisive)", "delayed": "delayed (decisive)", "not_restated": "not restated (neutral)",
          "reported": "reported (neutral)", "explained": "explained (neutral)"}
CHANGED = {"tightened", "softened", "widened", "delayed"}
OVERALL = ["Accept", "Needs correction", "Uncertain"]
CHECKS = ["1. Quote accuracy (open the link, compare word for word)", "2. Speaker attribution and role",
          "3. Management guidance versus commentary (`kind`)", "4. Metric, unit and segment/consolidated scope",
          "5. Reporting period and target horizon", "6. Verdict follows from the evidence",
          "7. Missing evidence handled honestly (nothing inferred from silence or substituted)"]


def link(q: dict) -> str:
    return f"[{q['quarter']} p.{q['page']}]({q['url']}#page={q['page']})"


def cell(s) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def target(r: dict) -> str:
    t = r["target"]
    if not t:
        return "no number"
    lo = ("more than " if t.get("low_exclusive") else "") + f"{t['low']}"
    rng = f"{lo} to {t['high']}" if t.get("high") is not None else (lo if t.get("low_exclusive") else f"{lo} or more")
    return f"{rng} ({t['unit']})"


def quotes(r: dict) -> list[dict]:
    return [r["statement"], *r["follow_ups"], *[f["prompted_by"] for f in r["follow_ups"] if f.get("prompted_by")]]


def review_block(rv: dict | None = None) -> list[str]:
    out = ["| Check | Accept | Needs correction | Uncertain | Reviewer note |", "|---|:-:|:-:|:-:|---|"]
    out += [f"| {c} | ☐ | ☐ | ☐ | |" for c in CHECKS]
    if not rv:
        return out + ["", "**Overall:** ☐ Accept · ☐ Needs correction · ☐ Uncertain", "",
                      "**Reviewer:** ________ · **Date:** ________", "", "**Status: PENDING. Not reviewed by a person.**"]
    overall = " · ".join(f"{'☑' if o == rv['overall'] else '☐'} {o}" for o in OVERALL)
    return out + ["", f"**Overall:** {overall}", "", f"**Reviewer note:** {cell(rv['note'])}", "",
                  f"**Reviewer:** {rv.get('reviewer') or '________ (name not yet entered)'} · **Date:** {rv['date']}", "",
                  f"**Status: REVIEWED BY A PERSON: {rv['overall']}, verdict {rv['verdict_confirmed']} ({rv['date']}).** "
                  + ("" if rv.get("checks_marked") else "The decision was given for the record as a whole, so the seven checks above are not marked one by one. ")
                  + "Recorded by Claude on the reviewer's instruction."]


def record(n: int, sym: str, r: dict, prompts: dict, reviews: dict) -> list[str]:
    st, h, o = r["statement"], r["horizon"], r["outcome"]
    changes = [f"{link(f)} {f['stance']}: “{cell(f['quote'])}”" for f in r["follow_ups"] if f["stance"] in CHANGED]
    out = [f"### R{n:02d} · {r['id']}", "", f"**{cell(r['title'])}**", "",
           "| Field | Value |", "|---|---|",
           f"| Company · transcript quarter | {sym} · {st['quarter']} (said {st['said_on'][:10]}) |",
           f"| Source | {link(st)} · sha256 `{st['sha256'][:16]}…` · quote check: {st['quote_check']} |",
           f"| Speaker · role | {cell(st['speaker'])} · {st['role']} ({cell(st.get('role_evidence', ''))}) |",
           f"| How the sentence was found | {cell(st.get('candidate_label') or '')} |",
           f"| Classification (`kind`) | {r['kind']} |",
           f"| Metric · scope | `{r['metric']}` · {cell(r['scope'])} |",
           f"| Target · unit (as in the statement) | {target(r)} |",
           f"| Later changes to the commitment | {'<br>'.join(changes) if changes else 'none recorded'} |",
           f"| Horizon | {cell(h['label'])}" + (f" · period end {h['period_end']}" if h.get("period_end") else "")
           + f" · {'stated by management' if h.get('stated') else 'inferred by FINN'}"
           + (f" ({cell(h['basis'])})" if h.get("basis") else "") + " |",
           f"| Conditions | {cell(r.get('conditions') or 'none stated')} |",
           f"| **Current verdict** | **{r['verdict']['status']}**: {cell(r['verdict']['reason'])} |", "",
           "Management statement:", "", f"> {st['quote']}", "", f"FINN's reading: {r['interpretation']}", ""]
    if r.get("audit_note"):
        out += [f"Audit note: {r['audit_note']}", ""]
    if r["follow_ups"]:
        out += ["Follow-ups (management, in call order):", "",
                "| # | Source | Speaker | Stance | Quote | Note | Prompted by (analyst) |", "|---|---|---|---|---|---|---|"]
        for i, f in enumerate(r["follow_ups"], 1):
            pb = f.get("prompted_by")
            asked = f"{cell(pb['speaker'])}, {link(pb)}: “{cell(pb['quote'])}”" if pb else ""
            out.append(f"| {i} | {link(f)} | {cell(f['speaker'])} | {STANCE[f['stance']]} | “{cell(f['quote'])}” | "
                       f"{cell(f.get('note') or '')} | {asked} |")
        out.append("")
    else:
        out += ["Follow-ups: none recorded.", ""]
    out += ["Outcome evidence:", ""]
    if o.get("method") == "computed":
        out += [f"- Method: computed. Formula: {o['formula']}.", f"- Status: {o.get('status') or 'context only'}. {o.get('reason', '')}", "",
                "| Quarter ended | Value | EBITDA (₹ cr) | D&A (₹ cr) | Revenue (₹ cr) | Recomputed | Filing |", "|---|---|---|---|---|---|---|"]
        for p in o["series"]:
            i = p["inputs_crore"]
            again = round((i["ebitda"] - i["dna"]) / i["revenue"] * 100, 2)
            if again != p["value"]:
                raise SystemExit(f"{r['id']} {p['period_end']}: ledger says {p['value']}, inputs give {again}")
            out.append(f"| {p['period_end']} | {p['value']}{p['unit']} | {i['ebitda']:,.0f} | {i['dna']:,.0f} | {i['revenue']:,.0f} | "
                       f"{again}% ✓ | " + ", ".join(f"[XBRL]({u})" for u in p["sources"]) + " |")
        out.append("")
    else:
        out += [f"- Not computed: {o.get('reason')}.",
                "- Any figures quoted above as management's own (follow-ups marked *reported* or *explained*) are shown as said. "
                "FINN has not checked them against filings.", ""]
    if r["id"] in prompts["flags"]:
        out += [f"⚠ **Preparer flag:** {prompts['flags'][r['id']]}", ""]
    return out + [f"**Question for the reviewer:** {prompts['questions'][r['id']]}", ""] + review_block(reviews.get(r["id"])) + ["", "---", ""]


def render() -> str:
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    prompts = json.loads(PROMPTS.read_text(encoding="utf-8"))
    rvf = json.loads(REVIEWS.read_text(encoding="utf-8"))
    reviews = rvf["reviews"]
    recs = [(s, r) for s in ORDER for r in ledger["companies"][s]["records"]]
    ids = {r["id"] for _, r in recs}
    if set(prompts["questions"]) != ids or not set(prompts["flags"]) <= ids:
        raise SystemExit(f"{PROMPTS.name} does not match the ledger: "
                         f"no question for {sorted(ids - set(prompts['questions']))}, unknown {sorted(set(prompts['questions']) - ids)}")
    rn = {r["id"]: f"R{n:02d}" for n, (_, r) in enumerate(recs, 1)}
    status = {r["id"]: r["verdict"]["status"] for _, r in recs}
    for rid, rv in reviews.items():   # a review stands only for the record and verdict the person actually saw
        if rid not in ids or rv["overall"] not in OVERALL or rv["verdict_confirmed"] != status[rid]:
            raise SystemExit(f"{REVIEWS.name}: review of {rid} does not match the ledger (verdict now {status.get(rid)})")
    done = [rn[i] for i in rn if i in reviews]
    by = Counter((i["symbol"], i["label"]) for i in audit["items"])
    tot = Counter(i["label"] for i in audit["items"])
    v = Counter(r["verdict"]["status"] for _, r in recs)
    fus = [f for _, r in recs for f in r["follow_ups"]]
    asked = [f["prompted_by"] for f in fus if f.get("prompted_by")]
    allq = [q for _, r in recs for q in quotes(r)]
    shown = [r["statement"] for _, r in recs] + fus
    xbrl = [u for _, r in recs for p in (r["outcome"].get("series") or []) for u in p["sources"]]
    off_page = sum(1 for f in fus if f.get("prompted_by") and f["prompted_by"]["page"] != f["page"])
    found = sum(1 for _, r in recs if not str(r["statement"].get("candidate_label", "")).startswith("not proposed"))
    eligible = tot["explicit_numeric"] + tot["measurable_qualitative"] + tot["commentary"]
    bf = ledger["built_from"]
    same = Counter(r["statement"]["quote"] for _, r in recs)
    shared = " and ".join(rn[r["id"]] for _, r in recs if same[r["statement"]["quote"]] > 1)
    xrec = sum(1 for _, r in recs if r["outcome"].get("series"))
    seen = Counter(q["quote"] for _, r in recs for q in quotes(r))
    repeats = "; ".join(f"“{t[:60]}{'…' if len(t) > 60 else ''}” in " + " and ".join(rn[r["id"]] for _, r in recs if any(q["quote"] == t for q in quotes(r)))
                        for t, n in seen.items() if n > 1)

    md = [
        "# Promise Ledger: human review pack", "",
        (f"**Status: {len(done)} of {len(recs)} records reviewed by a person ({', '.join(done)}); the other {len(recs) - len(done)} are PENDING.** "
         if done else "**Status: PENDING. No record in this pack has been reviewed by a person.** ")
        + "Each ☐ stays empty until a reviewer fills it in. Decisions Claude made at the reviewer's request are not reviews and tick nothing.", "",
        "Generated by `python scripts/promise_review_pack.py` from `snapshot/promise_ledger.json` and `config/promise_audit.json`. "
        "Do not edit this file by hand: change the records, `config/promise_review_questions.json` or `config/promise_reviews.json` (decisions a person made), rebuild, and regenerate.", "",
        "## Read this first",
        f"- **What you are reviewing.** `snapshot/promise_ledger.json`, built from snapshot `{bf['snapshot_digest'][:8]}…` (as of {bf['snapshot_as_of']}), "
        f"records file sha256 `{bf['records_sha256'][:12]}…` and audit file sha256 `{bf['audit_sha256'][:12]}…`.",
        f"- **Who prepared it.** {ledger['audited_by']}. The same assistant wrote the labels, records and verdicts under review, "
        "so **this pack is not an independent review**. It lays the audit out for a person to check. Treat the reviewer questions as prompts, not conclusions.",
        "- **What is machine-checked.** The build admits a quote only if it appears on the cited page (exact match, or reversible whitespace or glyph repair; "
        "no fuzzy matching) and inside a turn of the cited speaker. The speaker's role must come from the same transcript. These checks prove the words are on the page. "
        "They **do not** prove the judgements: kind, stance, scope, horizon, verdict and selection. Those are what this review is for.",
        "- **What it does not contain.** No transcript text beyond the short quotes. Open the PDF links to read each quote in context.", "",
        f"## Why {len(recs)} records, not 15",
        f"The first review covered 15 records. {len(prompts['additions'])} were added later. Each was in a transcript the audit had already read, "
        "but the candidate filter missed it. Each meets the same criteria as every other record: management speaker; this company's future; "
        "a measurable target with a stated horizon; an outcome investors track; not a restatement of another record; and not withdrawn in the same answer. "
        "Each passes the same build checks and, like the others, awaits review.", ""]
    md += [f"- **{x['record']}** («{x['record']}»): {x['why']}" for x in prompts["additions"]]
    md += ["",
        "## Counts and what each one measures", "",
        "| Figure | Count | Unit |", "|---|--:|---|",
        f"| Ledger records | {len(recs)} | Commitments selected for the ledger |",
        f"| Audit labels | {len(audit['items'])} | One label for each candidate sentence the keyword filter proposed from the 12 transcripts |",
        f"| Labels eligible to be records | {eligible} | explicit numeric {tot['explicit_numeric']} + measurable qualitative {tot['measurable_qualitative']} + commentary {tot['commentary']} |",
        f"| Known misses | {len(audit['known_misses'])} | Real commitments the filter did not propose, found by reading |",
        f"| Quotes in the ledger | {len(allq)} | {len(recs)} statements + {len(fus)} follow-ups + {len(asked)} analyst questions. Each is re-checked by the build |",
        f"| Distinct quote texts | {len({q['quote'] for q in allq})} | {len(allq) - len({q['quote'] for q in allq})} quote(s) appear in more than one record: {repeats} |",
        f"| Source links on the live cards | {len(shown)} | One per statement and follow-up ({len(recs)} + {len(fus)}). Analyst questions show their page number but have no link of their own; {off_page} of the {len(asked)} are on a different page from the answer they prompted |",
        f"| Distinct transcript pages cited | {len({(q['url'], q['page']) for q in allq})} | Pages holding at least one quote, in {len({q['url'] for q in allq})} of the 12 transcripts |",
        f"| Transcript links in this pack | {len(allq) + len(recs)} | One per quote ({len(allq)}) + one per row of the summary table ({len(recs)}) |",
        f"| XBRL filing links in this pack | {len(xbrl)} | {len(set(xbrl))} distinct filings behind the TCS margin series, which appears in {xrec} records |", "",
        "Earlier figures, kept for the record:",
        "- \"50 quotes: 15 statements, 25 follow-ups and 10 analyst questions\" was how the first review described the 15 original records. "
        "The total was right, but the split was 15, 30 and 5. The final corrections then added 1 statement (the dividend record) and 4 follow-ups "
        "(the LDR \"not a constraint\" remark from Q3 FY26 p.4, two C&W 1.5× answers and the capex split), which gives 55.",
        "- \"56 source links\" in one verification report was an arithmetic error. The cards then held 50 links.",
        "- Before the review corrections of 2026-10-27 the ledger held 16 records and 55 quotes (16 statements, 34 follow-ups, 5 analyst questions), "
        "and the cards held 50 links. The corrections added one record and further follow-ups (listed in the next section), which gives the figures above.", "",
        "## Corrections made before this review", "",
        "| Record | Correction |", "|---|---|"]
    md += [f"| {c['record']} ({rn[c['record']]}) | {cell(c['what'])} |" for c in prompts["corrections_before_review"]]
    if rvf["changes_during_review"]:
        md += ["", "## Changes made during the review", "",
               "Applied with the reviewer's approval. They add evidence or wording and change no verdict.", "",
               "| Record | Change |", "|---|---|"]
        md += [f"| {c['record']} ({rn[c['record']]}) | {cell(c['what'])} |" for c in rvf["changes_during_review"]]
    md += ["",
           "## How to review",
           "Open each source link; it opens the NSE PDF at the cited page. For each record, mark one status per check, write a note for anything other than Accept, and set an overall status.", "",
           "| Status | Meaning |", "|---|---|",
           "| **Accept** | The evidence supports the record as written |",
           "| **Needs correction** | Something is wrong. Say what, and what it should be |",
           "| **Uncertain** | You cannot decide from the evidence. Say what would settle it |", "",
           "Checklist, applied to every record:",
           "1. **Quote accuracy.** The words match the PDF on the cited page, and the quote is not cut so that its meaning changes.",
           "2. **Speaker attribution.** The named person said it and is management. Analyst words appear only as the question that prompted an answer.",
           "3. **Guidance versus commentary.** The `kind` fits: `explicit_numeric` has a number or range; `measurable_qualitative` has a checkable target without one; `commentary` is aspiration or tone and is never scored.",
           "4. **Metric, unit and scope.** The metric is the one management named, in the same unit. A segment target is not compared with a consolidated figure, and EBIT is not matched to EBITDA.",
           "5. **Period and horizon.** The target period is the one stated. Any horizon FINN inferred is marked as inferred and is reasonable.",
           "6. **Verdict follows from the evidence.** Check the stated precedence: (1) computed met or missed on a reported target period; (2) not reaffirmed only if the last *decisive* follow-up softened, widened or delayed the commitment; (3) commentary is unverifiable; (4) pending while the horizon is open; (5) otherwise unverifiable.",
           "7. **Missing evidence handled honestly.** Silence or not repeating a target is never treated as withdrawal. Nothing missing from the snapshot is substituted. Management's own figures are labelled as unchecked.", "",
           "## Summary of the records", "",
           "| # | Record | Company · source | Kind | Scope | Verdict |", "|---|---|---|---|---|---|"]
    md += [f"| {rn[r['id']]} | {r['id']} | {s} · {link(r['statement'])} | {r['kind']} | {cell(r['scope'])} | **{r['verdict']['status']}** |" for s, r in recs]
    md += ["", f"Verdicts: not reaffirmed {v['not_reaffirmed']} · pending {v['pending']} · unverifiable {v['unverifiable']} · met {v['met']} · missed {v['missed']}.", "",
           "## The audit labels and how they relate to the records", "",
           "`config/promise_audit.json` labels every candidate sentence the keyword filter proposed from the 12 transcripts (3 companies × 4 quarters). "
           "It stores only a hash, page and speaker for each label, never the text. The labels were written by the same assistant and have not been reviewed by a person.", "",
           "| Label | TCS | POLYCAB | HDFCBANK | Total |", "|---|--:|--:|--:|--:|"]
    md += [f"| {k} | {by[('TCS', k)]} | {by[('POLYCAB', k)]} | {by[('HDFCBANK', k)]} | **{tot[k]}** |" for k in LABELS]
    md += [f"| **Total** | {sum(by[('TCS', k)] for k in LABELS)} | {sum(by[('POLYCAB', k)] for k in LABELS)} | {sum(by[('HDFCBANK', k)] for k in LABELS)} | **{len(audit['items'])}** |", "",
           "How the labels feed the ledger:",
           f"- **{eligible} labelled sentences can become records.** The other {len(audit['items']) - eligible} are analyst words ({tot['analyst']}), reports of results ({tot['actual_report']}) or not guidance ({tot['not_guidance']}), and none of them can be a record.",
           f"- **{found} of the {len(recs)} record statements came from labelled candidates.** {shared} share one sentence. The build checks that each record's `kind` matches its sentence's label.",
           f"- **{len(recs) - found} record statements were not proposed by the filter.** They were found by reading and are listed under the known misses below. "
           "Because the filter misses real commitments, the labels are **not a complete inventory**.",
           "- **Follow-ups are linked to their record by hand.** The ledger stores no label for each follow-up, so judge each stance directly from the quote.",
           "- **Most of the remaining eligible sentences are restatements** already attached to a record as follow-ups. The commitments that were left out are listed further down.", "",
           "Label changes logged in the audit file (reviewers may challenge any of them):", "",
           "| Where | From → to | Reason given |", "|---|---|---|"]
    md += [f"| {x['symbol']} {x['quarter']} p.{x['page']} | {x['from']} → {x['to']} | {cell(x['why'])} |" for x in audit["relabels"]]
    md += [f"| record {x['record']} | {x['from']} → {x['to']} | {cell(x['why'])} |" for x in audit["record_kind_changes"]]
    md += [f"| {x['symbol']} {x['quarter']} p.{x['page']} | kept as {x['label']} | {cell(x['why'])} |" for x in audit["labels_retained_after_review"]]
    md += ["", "Known misses (real commitments the filter did not propose):", ""]
    md += [f"- {m['symbol']} {m['quarter']} p.{m['page']}: {m['why']}" for m in audit["known_misses"]]
    md += ["", "## Issues a reviewer should look at first", "",
           "1. **POLYCAB segment margin («POLYCAB-wc-ebitda-11-13»).** The Prompt 2 experiment mapped the 11–13% band to the *consolidated* EBITDA margin and compared it with a consolidated 14.37%. That was wrong. "
           "The band is a Wires & Cables *segment* EBITDA target. The record has segment scope and is never computed, and the Prompt 2 fixture and report carry a correction note. "
           "Management reports the segment at EBIT (13.3%, 14.2%), a different measure, so the two are not compared.",
           "2. **Two HDFCBANK verdicts revised from not reaffirmed to pending («HDFCBANK-ldr-85-90», «HDFCBANK-growth-vs-system-fy27»).** The LDR \"not a constraint\" remark had already been made on the call that set the range (Q3 FY26 p.4), "
           "and the growth answers contain no weakening language. Both are now `not_restated`, a neutral stance, so the verdict is *pending*. "
           "A reviewer who reads those answers as weakening should mark **Needs correction**; the verdicts would then return to *not reaffirmed*.",
           "3. **TCS 25% exit («TCS-ebit-exit-25») changed from not reaffirmed to pending on the reviewer's instruction.** \"While it's an uphill task\" (Q2 FY27 p.16) "
           "is now read as cautionary context, not an explicit revision or withdrawal of the 25% target, so both Q2 FY27 answers are `not_restated`. "
           "The risk note (MHP dilution, furlough seasonality, investment priorities, the latest 23.98%) is kept, as is the margin-formula caveat. "
           "\"Exit\" is still read as Q4 FY27, marked as inferred. The reviewer accepted this reading on 2026-10-27 («TCS-ebit-exit-25»).",
           "4. **Record added: HDFCBANK FY26 LDR of 90% to 96% («HDFCBANK-ldr-fy26-90-96»).** In the same answer that gives the FY27 range (Q3 FY26 p.6), the CEO says "
           "\"we will try and be in a range of somewhere between 90% to 96% in the year FY '26, which is… what we are very confident about\", and repeats it on p.8. "
           "The filter did not propose the sentence. It meets the inclusion criteria (see the start of this pack). FY26 has closed, but FINN holds no loan or deposit "
           "figures and management states no FY26 ratio in the later calls, so it is **unverifiable**: not met, not missed, not withdrawn.",
           "5. **Chronology and horizon corrections from the review.** TCS 26–28% («TCS-aspiration-26-28») now starts at the CFO's Q3 FY26 p.23 answer, which the audit had "
           "called analyst-only. POLYCAB C&W 1.5× («POLYCAB-cw-growth-1.5x») now has the horizon management states (\"until FY30\", Q1 FY27 p.18), so it is *pending*, "
           "not *unverifiable*. POLYCAB working capital («POLYCAB-working-capital-days») now shows management's reported cycle (27, 25, 15, 11 days) as unchecked context. "
           "Each verdict change follows FINN's existing rules; none rests on silence.",
           "6. **HDFCBANK FY27 LDR clarified, not revised («HDFCBANK-ldr-85-90»).** Answering a direct question about the FY27 range (Q3 FY26 p.8), the CEO calls it \"a broad range\", "
           "says 90% means \"maybe around the 88%, 89%… or 90% to 91%\", and that \"somewhere around the 90%\" would satisfy management. Both passages are now `explained` follow-ups. "
           "The stated 85% to 90% stays the target; the verdict stays *pending*. Open point: management's own reading (up to 91%) reaches above the stated range.",
           "7. **Analyst words versus management commitments.** Analysts' paraphrases of guidance (for example \"you said LDR is no longer kind of relevant\", "
           "or \"exiting FY27, at 25% plus EBIT margin\") appear only as the question behind a management answer. They never set a target or a stance. "
           "\"EBIT\" in the TCS record title was replaced by \"operating margin\", management's term.",
           "8. **Ambiguous horizons, units and incomplete outcome data. FINN stated an assumption in each case rather than deciding:**",
           "   - TCS \"exit\" read as Q4 FY27 (inferred, marked in the UI);",
           "   - TCS operating margin taken as (EBITDA − D&A) / revenue, justified only because it reproduces TCS's stated 25.2%, 24% and 24%;",
           "   - HDFCBANK \"top line growth\" left undefined («HDFCBANK-growth-vs-system-fy26», «HDFCBANK-growth-vs-system-fy27»);",
           "   - HDFCBANK MSME \"18% to 20%, 21%\" recorded as 18–21% («HDFCBANK-msme-growth»);",
           "   - POLYCAB working capital: original 50–55 days kept as the target, the later 45–50 recorded as a tightening («POLYCAB-working-capital-days»);",
           "   - POLYCAB C&W 1.5× market growth kept apart from \"1.5x of GDP growth\"; management describes it as a volume target («POLYCAB-cw-growth-1.5x»);",
           "   - HDFCBANK FY26 LDR: whether \"we will try… very confident\" is a commitment or an aspiration («HDFCBANK-ldr-fy26-90-96»);",
           "   - POLYCAB dividend payout base (which profit) not stated («POLYCAB-dividend-payout-30»);",
           "   - POLYCAB BharatNet \"maybe INR 800 crores to INR 1,000 crores\" kept as commentary and not made a record;",
           "   - no outcome is computed for segment margins, working-capital days, capex, exports, payout, LDR, MSME growth, growth against the system or peer margins, because the snapshot does not hold them on a comparable basis.", "",
           "## Commitments examined and not made into records", "",
           "A reviewer may decide any of these should be a record.", "",
           "| Statement (source) | Decision | Reason given |", "|---|---|---|"]
    md += [f"| {cell(a)} | {cell(b)} | {cell(c)} |" for a, b, c in prompts["omitted_commitments"]]
    md += ["", "The ledger covers only TCS, POLYCAB and HDFCBANK. The other companies in the snapshot are `not_audited` and show no records; nothing was created for them.", "",
           "## Records", ""]
    for n, (s, r) in enumerate(recs, 1):
        md += record(n, s, r, prompts, reviews)
    md += ["## Sign-off", "", "| | |", "|---|---|",
           f"| Records accepted | __ / {len(recs)} |", "| Records needing correction | __ |", "| Records uncertain | __ |",
           "| Reviewer name and role | |", "| Date | |", "| Independent of the original audit? | ☐ yes ☐ no |", "",
           "Until a person fills in this table, the ledger's `audited_by` field (\"not yet reviewed by a person\") and the UI notice stay as they are. "
           "Make any corrections in `config/promise_ledger.json` or `config/promise_audit.json`, rebuild with `python -m finn.promises build`, "
           "and regenerate this pack. Never edit the built snapshot.", ""]
    text = re.sub(r"«([^»]+)»", lambda m: rn[m.group(1)], "\n".join(md))
    if "«" in text:
        raise SystemExit("unresolved record reference")
    return text


def main(argv: list[str]) -> int:
    text = render()
    if "--check" in argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.relative_to(REPO)} is out of date: run python scripts/promise_review_pack.py")
            return 1
        print(f"{OUT.relative_to(REPO)} is up to date")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
