"""Management Promise Ledger: what did management say then, and what happened afterwards?

Two stages, both deterministic and offline (no LLM, no network):

    python -m finn.promises audit    # every transcript -> candidate statements (data/derived, git-ignored)
    python -m finn.promises build    # manually validated records -> snapshot/promise_ledger.json (committed)

1. Candidates. Each transcript is split into speaker turns. Every speaker gets a role from evidence in the
   same document: the moderator's "question comes from the line of X" introduces an analyst; a name under the
   MANAGEMENT header, or a speaker in the prepared remarks before the first analyst, is company side. Sentences
   from those turns are kept only if they pair a forward-looking word with a financial topic. A percentage on
   its own is not enough. Candidates are proposals for a human audit, never ledger entries.
2. Records. `config/promise_ledger.json` holds the records a person checked against the transcript. The build
   re-reads each cited PDF from the raw cache, admits a quote only if `transcripts.locate_quote` finds it
   (exact or reversible normalisation, no fuzzy matching), re-derives speaker and role from the turns, and
   computes outcomes from snapshot observations with the formula shown. A record that fails any check is
   written to the `excluded` list with the reason; it is never shown as a promise.

Transcript text is never written to a committed file; only the validated short excerpts are.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

from finn import http, transcripts
from finn.guidance import judge_band

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "snapshot" / "finn_snapshot.db"
RECORDS = ROOT / "config" / "promise_ledger.json"
AUDIT = ROOT / "config" / "promise_audit.json"
LEDGER_OUT = ROOT / "snapshot" / "promise_ledger.json"
CANDIDATES_OUT = ROOT / "data" / "derived" / "promise_candidates.json"
LEDGER_VERSION = 1

# The inventory's SPEAKER pattern needs two letters before the first space, so "K Krithivasan:" (TCS CEO) is
# not a turn and his words join the previous speaker's. The ledger allows single-letter initials. The
# inventory pattern is left as it is, because the snapshot's stored turn counts were computed with it.
SPEAKER = re.compile(r"(?m)^\s*((?:[A-Z]\.? )?[A-Z][A-Za-z.'\-]+(?: [A-Z][A-Za-z.'\-]+){0,3}|Moderator)\s*:\s")
NOT_A_SPEAKER = {"Sub", "Subject", "Note", "Encl", "Tel", "Fax", "Email", "CIN", "Website", "Regd. Office",
                 "Registered Office", "Corporate Office", "Ref", "Dear Sir", "Dear Sirs", "Moderator"}
ANALYST_INTRO = re.compile(
    r"(?:from the line of|question (?:is|comes) from|next question is from|we have)\s+"
    r"((?:Mr\.|Ms\.|Mrs\.)?\s*[A-Z][A-Za-z']+(?: [A-Z][A-Za-z']+){0,3})(?:\s*[.:,]|\s+(?:from|with|of)\s)", re.S)

FORWARD = re.compile(r"\b(expect\w*|guid\w*|target\w*|aim\w*|will|would|should|going forward|outlook|aspir\w*|"
                     r"plan\w*|intend\w*|anticipat\w*|endeavo\w*|confident|commit\w*|look(?:ing)? to|on track|"
                     r"trend towards|we'll|by (?:the end of )?(?:FY|March|this year|next year))\b", re.I)
TOPICS = {
    "margin": re.compile(r"\b(ebitda|ebit|operating margin|margins?|nim|net interest margin|spread)\b", re.I),
    "growth": re.compile(r"\b(grow\w*|double[- ]digit|cagr|volume|revenue|top ?line|loan book|deposits?|"
                         r"advances|market share)\b", re.I),
    "capex": re.compile(r"\b(capex|capital expenditure|investment of|invest\w* (?:about|around|₹|rs))\b", re.I),
    "capacity": re.compile(r"\b(capacity|capacities|plant|commission\w*|greenfield|brownfield)\b", re.I),
    "segment": re.compile(r"\b(segment|fmeg|wires?|cables?|epc|bfsi|retail|corporate banking|international)\b", re.I),
    "working_capital": re.compile(r"\b(working capital|receivables?|inventory days|cash conversion|free cash|"
                                  r"ocf|cash flow)\b", re.I),
    "cost_of_risk": re.compile(r"\b(credit cost|slippage|npa|provision\w*|ldr|loan[- ]to[- ]deposit|cost to income)\b", re.I),
    "timeline": re.compile(r"\b(FY ?'?\d{2}|next (?:two|2|three|3|few) (?:quarters|years)|medium[- ]?term|"
                           r"long[- ]?term|by (?:the )?end of)\b", re.I),
    # guidance vocabulary and softening count as substance: "26%-28% as our guiding beacon", "an uphill task"
    "guidance_language": re.compile(r"\b(guidance|guided|guiding|aspiration\w*|beacon|projected targets?|"
                                    r"you (?:had )?(?:said|guided|mentioned|committed)|commitment)\b", re.I),
    "softening": re.compile(r"\b(uphill|endeavo\w*|difficult to|challenging|not in a position|no longer|defer\w*|"
                            r"push(?:ed)? out|delay\w*)\b", re.I),
    "reaffirm": re.compile(r"\b(reiterat\w*|reaffirm\w*|remains? unchanged|stay(?:s)? the same|maintain\w* (?:our|the) "
                           r"guidance|revis\w*|on track)\b", re.I),
}
NUMBER = re.compile(r"(\d+(?:\.\d+)?)\s*(%|percent|per cent|bps|basis points|days|x\b|times|crore|cr\b|billion)", re.I)
SENTENCE = re.compile(r"(?<=[.?!])\s+(?=[A-Z\"'(])")


@dataclass(frozen=True)
class Turn:
    speaker: str
    page: int
    text: str


def speaker_turns(pages: list[str]) -> list[Turn]:
    """Same algorithm as transcripts.speaker_turns, with the initials-aware pattern above."""
    turns: list[Turn] = []
    current, buf, start_page = None, [], 1
    for pno, page in enumerate(pages, start=1):
        pos = 0
        for m in SPEAKER.finditer(page):
            buf.append(page[pos:m.start()])
            if current is not None:
                turns.append(Turn(current, start_page, "".join(buf).strip()))
            current, buf, start_page, pos = m.group(1), [], pno, m.end()
        buf.append(page[pos:])
    if current is not None:
        turns.append(Turn(current, start_page, "".join(buf).strip()))
    return turns


def _clean_name(n: str) -> str:
    return re.sub(r"^(?:Mr\.|Ms\.|Mrs\.)\s*", "", " ".join(n.split())).strip()


@dataclass
class Roles:
    role: dict = field(default_factory=dict)        # speaker -> management | analyst | moderator | unknown
    evidence: dict = field(default_factory=dict)    # speaker -> why


def assign_roles(pages: list[str], turns: list[Turn], company_management: frozenset = frozenset()) -> Roles:
    """Role from evidence in the same document only. A speaker the moderator introduced as a questioner is an
    analyst, even if they also appear earlier. Company side = MANAGEMENT header, or spoke in the prepared remarks
    (after the moderator opens the call, before the first analyst turn), or listed under the MANAGEMENT header of
    another transcript of the same company. Anyone else is unknown, and unknown speech is never admitted."""
    r = Roles()
    analysts = {_clean_name(m.group(1)) for m in ANALYST_INTRO.finditer(" ".join(" ".join(pages).split()))}
    header = transcripts.management_names(pages)
    speakers = [t.speaker for t in turns]

    def is_analyst(s: str) -> bool:      # "Sonali" is introduced as "Sonali Salgaonkar"; "Chintan" as "Chintan Joshi"
        return any(s == a or a.startswith(s + " ") or s.startswith(a + " ") for a in analysts)

    opened = next((i for i, s in enumerate(speakers) if s == "Moderator"), 0)    # cover letter comes before
    first_q = next((i for i, s in enumerate(speakers) if is_analyst(s)), len(speakers))
    prepared = set(speakers[opened:first_q])
    for s in dict.fromkeys(speakers):
        if s == "Moderator":
            r.role[s], r.evidence[s] = "moderator", "operator"
        elif s in NOT_A_SPEAKER or s.isupper() or speakers.index(s) < opened:
            r.role[s], r.evidence[s] = "unknown", "cover-letter field, not a speaker"
        elif is_analyst(s):
            r.role[s], r.evidence[s] = "analyst", "introduced by the moderator as a questioner"
        elif s in header:
            r.role[s], r.evidence[s] = "management", "listed under the MANAGEMENT header"
        elif s in prepared:
            r.role[s], r.evidence[s] = "management", "spoke in the prepared remarks before the first analyst"
        elif s in company_management:
            r.role[s], r.evidence[s] = "management", "listed under the MANAGEMENT header of another transcript"
        else:
            r.role[s], r.evidence[s] = "unknown", "not introduced as an analyst and not in the prepared remarks"
    return r


def load_transcripts(db: Path = SNAPSHOT) -> list[dict]:
    """The audited earnings-call transcripts from the snapshot, with their pages read from the raw cache."""
    c = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
    rows = c.execute("""SELECT t.symbol, t.seq_id, t.fiscal_quarter, t.period_end, t.broadcast_at, t.url, t.sha256
                        FROM transcript_filings t JOIN transcript_coverage v ON v.seq_id = t.seq_id
                        WHERE v.status = 'available' ORDER BY t.symbol, t.period_end""").fetchall()
    out = []
    for symbol, seq_id, fq, pe, bcast, url, sha in rows:
        got = http.read_cache(url)
        doc = {"symbol": symbol, "seq_id": seq_id, "fiscal_quarter": fq, "period_end": pe, "broadcast_at": bcast,
               "url": url, "sha256": sha, "pages": None, "problem": None}
        if got is None:
            doc["problem"] = "not in the raw cache (run python -m finn.snapshot build to fetch it)"
        elif hashlib.sha256(got.body).hexdigest() != sha:
            doc["problem"] = "cached bytes do not match the snapshot sha256"
        else:
            doc["pages"] = transcripts.pdf_pages(io.BytesIO(got.body))
        out.append(doc)
    return out


def _page_of(sentence: str, pages: list[str], start: int) -> Optional[int]:
    q = transcripts.locate_quote(sentence, pages, start)
    return q.page if q.ok else None


def candidates(doc: dict, company_management: frozenset = frozenset()) -> dict:
    """Candidate statements in one transcript, with the speaker's role and the topics that triggered them."""
    pages = doc["pages"]
    turns = speaker_turns(pages)
    roles = assign_roles(pages, turns, company_management)
    out = []
    for ti, t in enumerate(turns):
        role = roles.role[t.speaker]
        if role in ("moderator",) or roles.evidence[t.speaker].startswith("cover-letter"):
            continue
        for sent in SENTENCE.split(t.text):
            flat = " ".join(sent.split())
            if len(flat) < 25:
                continue
            topics = sorted(k for k, rx in TOPICS.items() if rx.search(flat))
            fwd = FORWARD.search(flat)
            nums = NUMBER.findall(flat)
            substantive = [k for k in topics if k not in ("timeline", "reaffirm", "softening")]
            if not substantive or not (fwd or {"reaffirm", "guidance_language"} & set(topics)):
                continue
            if not (nums or {"timeline", "reaffirm", "softening"} & set(topics)):
                continue
            q = transcripts.locate_quote(sent.strip(), pages, t.page)
            out.append({"turn": ti, "speaker": t.speaker, "role": role, "topics": topics,
                        "numbers": [f"{n}{u}" for n, u in nums], "forward_word": fwd.group(0) if fwd else None,
                        "page": q.page if q.ok else None, "quote_check": q.method if q.ok else "not_located",
                        "text": flat})
    return {"symbol": doc["symbol"], "fiscal_quarter": doc["fiscal_quarter"], "url": doc["url"],
            "sha256": doc["sha256"], "turns": len(turns),
            "roles": {s: {"role": roles.role[s], "evidence": roles.evidence[s]} for s in roles.role},
            "candidates": out}


def audit(out: Path = CANDIDATES_OUT) -> dict:
    docs = load_transcripts()
    headers: dict[str, set] = {}
    for d in docs:
        if d["pages"]:
            headers.setdefault(d["symbol"], set()).update(transcripts.management_names(d["pages"]))
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "transcripts": []}
    for d in docs:
        if d["problem"]:
            report["transcripts"].append({"symbol": d["symbol"], "fiscal_quarter": d["fiscal_quarter"],
                                          "problem": d["problem"]})
            continue
        report["transcripts"].append(candidates(d, frozenset(headers.get(d["symbol"], ()))))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False))
    return report


def summary(report: dict) -> list[dict]:
    rows = []
    for t in report["transcripts"]:
        if "problem" in t:
            rows.append({"symbol": t["symbol"], "quarter": t["fiscal_quarter"], "problem": t["problem"]})
            continue
        c = t["candidates"]
        by_role = Counter(x["role"] for x in c)
        rows.append({"symbol": t["symbol"], "quarter": t["fiscal_quarter"], "turns": t["turns"],
                     "candidates": len(c), "management": by_role["management"], "analyst": by_role["analyst"],
                     "unknown": by_role["unknown"],
                     "with_number": sum(1 for x in c if x["numbers"]),
                     "located": sum(1 for x in c if x["page"]),
                     "topics": dict(Counter(k for x in c for k in x["topics"]))})
    return rows


# --- build: validated records -> ledger --------------------------------------------------------------------

STANCES = {"restated", "tightened", "reported", "explained", "not_restated", "softened", "widened", "delayed"}
WEAKER = {"softened", "widened", "delayed"}      # explicit weakening words from management
# Only these decide whether a commitment still stands; the last one wins. "not_restated" (an answer that does not
# repeat the target), "reported" and "explained" are evidence, never withdrawal: silence proves nothing.
DECISIVE = WEAKER | {"restated", "tightened"}
COMMITMENT_LABELS = {"explicit_numeric", "measurable_qualitative", "commentary"}
KINDS = {"explicit_numeric", "measurable_qualitative", "commentary"}
# Only metrics FINN can compute from the snapshot, on the basis the guidance uses. TCS reports its operating margin
# as EBIT; (EBITDA - D&A) / revenue on the consolidated filing reproduces the figure TCS states (audit_note).
COMPUTED = {"ebit_margin": ("(EBITDA - depreciation & amortisation) / revenue x 100, consolidated",
                            ("ebitda", "dna", "revenue"))}
NOT_COMPUTED = {
    "segment": "segment results are not in the snapshot; FINN does not compare segment guidance with consolidated figures",
    "capex": "no capex figure is in the snapshot",
    "working_capital_days": "working-capital days are not in the snapshot; FINN does not substitute a balance-sheet ratio",
    "milestone": "a commissioning date is not a reported number; it is checked only against later management statements",
    "relative_growth": "needs market or banking-system growth, which FINN does not hold",
    "export_share_of_revenue": "export revenue is not in the snapshot",
    "loan_to_deposit_ratio": "loans and deposits are not in the snapshot",
    "net_interest_margin_vs_peers": "peer margins are not in the snapshot",
    "dividend_payout_ratio": "dividends declared are not in the snapshot",
}


def candidate_key(symbol: str, quarter: str, text: str) -> str:
    return hashlib.sha256(f"{symbol}|{quarter}|{transcripts.normalise(text)}".encode()).hexdigest()[:12]


def _turn_with(quote: str, turns: list[Turn]) -> Optional[Turn]:
    nq = transcripts.normalise(quote)
    return next((t for t in turns if nq in transcripts.normalise(t.text)), None)


def check_quote(ref: dict, pages: list[str], turns: list[Turn], roles: Roles, expect_role: str) -> tuple[Optional[dict], list[str]]:
    """Admit a cited quote only if it is in the text at the cited page, inside a turn of the cited speaker, and that
    speaker's role (from the same document) is the expected one. Returns (evidence, problems)."""
    problems = []
    q = transcripts.locate_quote(ref.get("quote", ""), pages, ref.get("page"))
    if not q.ok:
        return None, [f"quote not found in the transcript text: {ref.get('quote', '')[:60]!r}"]
    if q.page != ref.get("page"):
        problems.append(f"quote cited at p.{ref.get('page')} but found on p.{q.page}")
    t = _turn_with(ref["quote"], turns)
    if t is None:
        problems.append("quote is not inside a single speaker turn")
        return None, problems
    if t.speaker != ref.get("speaker"):
        problems.append(f"quote belongs to {t.speaker!r}, not {ref.get('speaker')!r}")
    role = roles.role.get(t.speaker, "unknown")
    if role != expect_role:
        problems.append(f"{t.speaker} is {role} in this transcript ({roles.evidence.get(t.speaker)}), expected {expect_role}")
    return {"quote": ref["quote"], "page": q.page, "quote_check": q.method, "speaker": t.speaker, "role": role,
            "role_evidence": roles.evidence.get(t.speaker)}, problems


def metric_series(con, symbol: str, metric: str) -> list[dict]:
    formula, inputs = COMPUTED[metric]
    rows = con.execute(f"""SELECT o.period_end, o.metric, o.value, s.url FROM observations o JOIN sources s ON s.id = o.source_id
                           WHERE o.symbol = ? AND o.basis = 'consolidated' AND o.metric IN ({",".join("?" * len(inputs))})
                           ORDER BY o.period_end""", (symbol, *inputs)).fetchall()
    by: dict[str, dict] = {}
    for pe, m, v, url in rows:
        by.setdefault(pe, {"urls": set()})[m] = Decimal(v)
        by[pe]["urls"].add(url)
    out = []
    for pe, x in sorted(by.items()):
        if any(k not in x for k in inputs) or not x["revenue"]:
            continue
        pct = (x["ebitda"] - x["dna"]) / x["revenue"] * 100
        out.append({"period_end": pe, "value": float(round(pct, 2)), "unit": "%",
                    "inputs_crore": {k: float(x[k] / Decimal(10**7)) for k in inputs}, "sources": sorted(x["urls"])})
    return out


def compute_outcome(rec: dict, con) -> dict:
    metric = rec.get("metric") or ""
    if metric not in COMPUTED:
        family = next((k for k in NOT_COMPUTED if metric == k or metric.startswith(k + "_") or metric.startswith(k + ":")), None)
        return {"method": "not_computed", "status": None,
                "reason": NOT_COMPUTED.get(family, "FINN cannot compute this metric from the snapshot")}
    if rec.get("scope") != "consolidated":     # COMPUTED metrics come from consolidated filings only
        return {"method": "not_computed", "status": None,
                "reason": f"the guidance is for {rec.get('scope')}; FINN's {metric} is consolidated and is not compared with it"}
    series = metric_series(con, rec["symbol"], metric)
    out = {"method": "computed", "formula": COMPUTED[metric][0], "series": series, "status": None}
    target, end = rec.get("target"), (rec.get("horizon") or {}).get("period_end")
    if not series:
        out["reason"] = "no observations for this metric in the snapshot"
    elif rec["kind"] == "commentary" or not target or not end:
        out["reason"] = f"context only: latest {series[-1]['value']:.2f}% (quarter ended {series[-1]['period_end']}); " \
                        "an undated aspiration cannot be met or missed"
    else:
        at = next((x for x in series if x["period_end"] == end), None)
        closed = at is not None
        actual = (at or series[-1])["value"]
        out["status"], why = judge_band(actual, target.get("low"), target.get("high"), closed)
        out["reason"] = why if closed else f"results for the quarter ended {end} are not in the snapshot; latest " \
                                           f"{actual:.2f}% (quarter ended {series[-1]['period_end']}) is " \
                                           f"{'inside' if 'inside' in why else 'outside'} the target"
    return out


def verdict(rec: dict, outcome: dict, as_of: str) -> dict:
    """Precedence: a computed met/missed on a closed period; then "not reaffirmed" if management's last decisive
    statement (restated, tightened, softened, widened, delayed) weakened it; then pending while the stated horizon is
    open; otherwise unverifiable. Silence, and answers that merely do not repeat the target, never change a verdict."""
    if outcome.get("status") in ("met", "missed"):
        return {"status": outcome["status"], "reason": outcome["reason"]}
    weaker = [f for f in rec["follow_ups"] if f["stance"] in WEAKER]
    decisive = [f for f in rec["follow_ups"] if f["stance"] in DECISIVE]
    if decisive and decisive[-1]["stance"] in WEAKER:
        f = decisive[-1]
        return {"status": "not_reaffirmed",
                "reason": f"management's latest statement on it ({f['quarter']} p.{f['page']}) {f['stance']} the commitment"}
    quiet = [f for f in rec["follow_ups"] if f["stance"] == "not_restated"]
    if rec["kind"] == "commentary":
        return {"status": "unverifiable", "reason": "commentary or aspiration, not a measurable commitment"}
    end = (rec.get("horizon") or {}).get("period_end")
    if end and end > as_of[:10]:
        why = "horizon still open" + ("" if outcome["method"] == "computed" else f"; {outcome['reason']}")
        if weaker:
            why += "; an earlier statement was weakened and later restated"
        if quiet:
            why += f"; {len(quiet)} later answer(s) did not repeat the target, which FINN does not treat as withdrawal"
        return {"status": "pending", "reason": why}
    if not end:
        return {"status": "unverifiable", "reason": f"no date was given; {outcome['reason']}"}
    return {"status": "unverifiable", "reason": f"horizon has passed; {outcome['reason']}"}


def _validate_shape(rec: dict) -> list[str]:
    p = []
    for k in ("id", "symbol", "title", "kind", "scope", "statement", "follow_ups", "interpretation"):
        if k not in rec:
            p.append(f"missing field {k}")
    if rec.get("kind") not in KINDS:
        p.append(f"kind must be one of {sorted(KINDS)}")
    if rec.get("kind") == "explicit_numeric" and not (rec.get("target") or {}).get("low") and not (rec.get("target") or {}).get("high"):
        p.append("explicit_numeric without a numeric target")
    for f in rec.get("follow_ups", []):
        if f.get("stance") not in STANCES:
            p.append(f"unknown stance {f.get('stance')!r}")
    return p


def _label_index(audit_doc: dict) -> dict:
    return {x["key"]: x for x in audit_doc["items"]}


def build(records_path: Path = RECORDS, audit_path: Path = AUDIT, db: Path = SNAPSHOT, out: Optional[Path] = LEDGER_OUT,
          docs: Optional[list[dict]] = None) -> dict:
    """Validate every record against the transcripts and compute outcomes. Deterministic: no clock, no network."""
    cfg = json.loads(records_path.read_text())
    audit_doc = json.loads(audit_path.read_text())
    labels = _label_index(audit_doc)
    docs = docs if docs is not None else load_transcripts(db)
    con = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
    meta = dict(con.execute("SELECT key, value FROM snapshot_meta").fetchall())

    headers: dict[str, set] = {}
    for d in docs:
        if d["pages"]:
            headers.setdefault(d["symbol"], set()).update(transcripts.management_names(d["pages"]))
    parsed, cand_keys, problems_docs = {}, {}, []
    for d in docs:
        if not d["pages"]:
            problems_docs.append({"symbol": d["symbol"], "quarter": d["fiscal_quarter"], "problem": d["problem"]})
            continue
        turns = speaker_turns(d["pages"])
        roles = assign_roles(d["pages"], turns, frozenset(headers.get(d["symbol"], ())))
        parsed[(d["symbol"], d["fiscal_quarter"])] = (d, turns, roles)
        for c in candidates(d, frozenset(headers.get(d["symbol"], ())))["candidates"]:
            cand_keys[candidate_key(d["symbol"], d["fiscal_quarter"], c["text"])] = (d["symbol"], d["fiscal_quarter"], c)

    companies: dict[str, dict] = {}
    for d in docs:
        companies.setdefault(d["symbol"], {"records": [], "excluded": [], "transcripts": []})["transcripts"].append(
            {"quarter": d["fiscal_quarter"], "period_end": d["period_end"], "url": d["url"], "sha256": d["sha256"],
             "broadcast_at": d["broadcast_at"], "readable": d["pages"] is not None})

    def ref_out(ref, quarter, symbol, expect_role):
        key = (symbol, quarter)
        if key not in parsed:
            return None, [f"no readable transcript for {symbol} {quarter}"]
        d, turns, roles = parsed[key]
        ev, probs = check_quote(ref, d["pages"], turns, roles, expect_role)
        if ev:
            ev.update({"quarter": quarter, "url": d["url"], "said_on": d["broadcast_at"], "sha256": d["sha256"]})
        return ev, probs

    for rec in cfg["records"]:
        sym = rec.get("symbol")
        bucket = companies.setdefault(sym, {"records": [], "excluded": [], "transcripts": []})
        probs = _validate_shape(rec)
        st = rec.get("statement") or {}
        stmt, p = ref_out(st, st.get("quarter"), sym, "management")
        probs += p
        label = None
        if stmt:     # the audit label of the candidate this quote came from, if the filter proposed it
            nq = transcripts.normalise(st["quote"])
            for k, (s, q, c) in cand_keys.items():
                if s == sym and q == st["quarter"] and nq in transcripts.normalise(c["text"]):
                    label = (labels.get(k) or {}).get("label", "unlabelled")
                    break
            if label and label not in COMMITMENT_LABELS:
                probs.append(f"audit label of this sentence is {label!r}, not a management commitment")
            elif label and label != rec.get("kind"):
                probs.append(f"record kind {rec.get('kind')!r} disagrees with the audit label {label!r}")
            stmt["candidate_label"] = label or "not proposed by the filter (found by reading)"
        follows = []
        for f in rec.get("follow_ups", []):
            ev, p = ref_out(f, f.get("quarter"), sym, "management")
            probs += [f"follow-up {f.get('quarter')} p.{f.get('page')}: {x}" for x in p]
            if ev:
                ev.update({"stance": f.get("stance"), "note": f.get("note")})
                if f.get("prompted_by"):
                    pb = {**f["prompted_by"], "quarter": f["quarter"]}
                    pev, pp = ref_out(pb, f["quarter"], sym, "analyst")
                    probs += [f"question before {f.get('quarter')} p.{f.get('page')}: {x}" for x in pp]
                    ev["prompted_by"] = pev
                follows.append(ev)
        if probs:
            bucket["excluded"].append({"id": rec.get("id"), "title": rec.get("title"), "problems": probs})
            continue
        out_rec = {k: rec.get(k) for k in ("id", "title", "kind", "scope", "metric", "target", "horizon", "conditions",
                                           "interpretation", "audit_note")}
        out_rec.update({"statement": stmt, "follow_ups": follows})
        out_rec["outcome"] = compute_outcome(rec, con)
        out_rec["verdict"] = verdict(rec, out_rec["outcome"], meta.get("as_of", ""))
        bucket["records"].append(out_rec)

    labelled = Counter(x["label"] for x in audit_doc["items"])
    unlabelled = sorted(k for k in cand_keys if k not in labels)
    vanished = sorted(k for k in labels if k not in cand_keys)
    for sym, b in companies.items():
        b["analyst_pointers"] = [{"quarter": labels[k]["quarter"], "page": labels[k]["page"], "speaker": labels[k]["speaker"]}
                                 for k in sorted(labels) if labels[k]["symbol"] == sym and labels[k]["label"] == "analyst"]
        b["counts"] = dict(Counter(r["verdict"]["status"] for r in b["records"]))
    ledger = {
        "ledger_version": LEDGER_VERSION,
        "built_from": {"snapshot_digest": meta.get("content_digest"), "snapshot_as_of": meta.get("as_of"),
                       "records_sha256": hashlib.sha256(records_path.read_bytes()).hexdigest(),
                       "audit_sha256": hashlib.sha256(audit_path.read_bytes()).hexdigest()},
        "audited_by": cfg.get("audited_by"),
        "method": "Quotes are admitted only if found in the cited transcript page (exact or reversible normalisation, no "
                  "fuzzy matching), inside a turn of the cited speaker whose role comes from the same document. Outcomes "
                  "are computed only for metrics the snapshot holds on the matching basis. No LLM is used.",
        "audit": {"candidates": len(cand_keys), "labelled": sum(labelled.values()), "labels": dict(labelled),
                  "unlabelled_candidates": unlabelled, "labels_without_candidate": vanished,
                  "known_misses": audit_doc.get("known_misses", []), "unreadable_transcripts": problems_docs},
        "companies": dict(sorted(companies.items())),
    }
    con.close()
    if out is not None:
        out.write_text(json.dumps(ledger, indent=1, ensure_ascii=False) + "\n")
    return ledger


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m finn.promises")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("audit", help="candidate statements from every cached transcript (git-ignored output)")
    sub.add_parser("build", help="validate config/promise_ledger.json and write snapshot/promise_ledger.json")
    a = ap.parse_args(argv)
    if a.cmd == "audit":
        for row in summary(audit()):
            print(json.dumps(row, ensure_ascii=False))
    elif a.cmd == "build":
        led = build()
        for sym, b in led["companies"].items():
            print(f"{sym}: {len(b['records'])} records {b['counts']}, {len(b['excluded'])} excluded")
            for e in b["excluded"]:
                print(f"  EXCLUDED {e['id']}: {'; '.join(e['problems'])}")
        a_ = led["audit"]
        print(f"audit: {a_['candidates']} candidates, {a_['labelled']} labelled, {len(a_['unlabelled_candidates'])} "
              f"unlabelled, {len(a_['labels_without_candidate'])} labels without a candidate")
        return 1 if any(b["excluded"] for b in led["companies"].values()) or a_["unlabelled_candidates"] else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
