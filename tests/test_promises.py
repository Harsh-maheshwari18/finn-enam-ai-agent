"""Management Promise Ledger. Two groups:

- committed artefacts (always run, offline): snapshot/promise_ledger.json, config/promise_ledger.json,
  config/promise_audit.json and the API over them;
- the real transcripts (run when the 12 PDFs are in the raw cache, data/raw, which is git-ignored; skipped otherwise):
  the build re-validates every quote and reproduces the committed ledger byte for byte.

Records marked SYNTHETIC below are made up to exercise the verdict rules; they never touch the ledger files.
"""
import copy
import io
import json
import sqlite3
from pathlib import Path

import pytest

from finn import api, promises, transcripts

ROOT = Path(__file__).parent.parent
SNAP = ROOT / "snapshot" / "finn_snapshot.db"
LEDGER = json.loads(promises.LEDGER_OUT.read_text())
RECORDS = json.loads(promises.RECORDS.read_text())
AUDIT = json.loads(promises.AUDIT.read_text())
ALL = [(sym, r) for sym, b in LEDGER["companies"].items() for r in b["records"]]


def _meta():
    c = sqlite3.connect(f"file:{SNAP}?mode=ro&immutable=1", uri=True)
    try:
        return dict(c.execute("SELECT key, value FROM snapshot_meta").fetchall())
    finally:
        c.close()


def call(path):
    out = {}
    body = b"".join(api.app({"PATH_INFO": path, "REQUEST_METHOD": "GET", "wsgi.input": io.BytesIO(), "QUERY_STRING": ""},
                            lambda s, h: out.update(status=s, headers=dict(h))))
    return out["status"], json.loads(body)


@pytest.fixture(autouse=True)
def _snapshot_env(monkeypatch):
    monkeypatch.setenv("FINN_SNAPSHOT", str(SNAP))
    api._ledger_cache.clear()


# --- committed ledger --------------------------------------------------------------------------------------

def test_ledger_matches_the_committed_snapshot_and_inputs():
    b = LEDGER["built_from"]
    assert b["snapshot_digest"] == _meta()["content_digest"]
    import hashlib
    assert b["records_sha256"] == hashlib.sha256(promises.RECORDS.read_bytes()).hexdigest(), "rebuild: python -m finn.promises build"
    assert b["audit_sha256"] == hashlib.sha256(promises.AUDIT.read_bytes()).hexdigest()


def test_every_record_was_admitted_and_none_excluded():
    assert sorted(r["id"] for _, r in ALL) == sorted(r["id"] for r in RECORDS["records"])
    assert all(not b["excluded"] for b in LEDGER["companies"].values())
    assert {s for s, _ in ALL} == {"TCS", "POLYCAB", "HDFCBANK"}


def test_every_quote_is_management_with_a_page_and_source():
    urls = {sym: {t["url"] for t in b["transcripts"]} for sym, b in LEDGER["companies"].items()}
    for sym, r in ALL:
        for ref in [r["statement"], *r["follow_ups"]]:
            assert ref["role"] == "management", (r["id"], ref["speaker"])
            assert ref["quote_check"] in ("exact", "normalised")
            assert isinstance(ref["page"], int) and ref["page"] >= 1
            assert ref["url"] in urls[sym] and ref["url"].startswith("https://nsearchives.nseindia.com/")
            assert ref["said_on"].endswith("+05:30")
        for f in r["follow_ups"]:
            if f.get("prompted_by"):
                assert f["prompted_by"]["role"] == "analyst"          # analyst words appear only as the question


def test_ledger_holds_short_excerpts_not_transcripts():
    for _, r in ALL:
        for ref in [r["statement"], *r["follow_ups"]]:
            assert len(ref["quote"]) < 400
    text = json.dumps(LEDGER)
    assert "pages" not in json.dumps([r for _, r in ALL])
    assert len(text) < 120_000
    assert all(set(x) == {"key", "symbol", "quarter", "page", "speaker", "label"} for x in AUDIT["items"])   # no sentences


def test_no_confidence_scores_anywhere():
    def keys(o):
        if isinstance(o, dict):
            for k, v in o.items():
                yield k
                yield from keys(v)
        elif isinstance(o, list):
            for v in o:
                yield from keys(v)
    assert not [k for k in keys(LEDGER) if "confidence" in k.lower() or "probability" in k.lower()]


def test_tcs_ebit_margin_is_computed_from_filed_values():
    r = next(r for _, r in ALL if r["id"] == "TCS-ebit-exit-25")
    o = r["outcome"]
    assert o["method"] == "computed"
    assert [(x["period_end"], x["value"]) for x in o["series"]] == [
        ("2025-09-30", 25.18), ("2026-06-30", 23.96), ("2026-09-30", 23.98)]
    assert o["status"] == "pending"                               # Q4 FY27 is not reported: never "missed"
    # "uphill task" is cautionary context, not a revision of the 25% target: no decisive stance, so pending (review 2026-10-27)
    assert r["verdict"]["status"] == "pending"
    assert [f["stance"] for f in r["follow_ups"]] == ["not_restated", "not_restated"]
    assert "uphill task" in r["interpretation"] and "MHP" in r["interpretation"]   # the risk note is kept
    assert r["horizon"]["stated"] is False                        # "exit" -> Q4 FY27 is FINN's reading, said so


def test_segment_and_days_guidance_is_never_compared_with_consolidated_numbers():
    by = {r["id"]: r for _, r in ALL}
    for rid in ("POLYCAB-wc-ebitda-11-13", "POLYCAB-fmeg-ebitda-8-10", "POLYCAB-epc-margin", "HDFCBANK-msme-growth"):
        assert by[rid]["outcome"]["method"] == "not_computed"
        assert "segment" in by[rid]["outcome"]["reason"]
    wc = by["POLYCAB-working-capital-days"]
    assert wc["outcome"]["method"] == "not_computed" and "does not substitute" in wc["outcome"]["reason"]
    assert wc["verdict"]["status"] == "unverifiable"


def test_verdicts_on_the_real_records():
    v = {r["id"]: r["verdict"]["status"] for _, r in ALL}
    assert v == {
        "TCS-ebit-exit-25": "pending", "TCS-aspiration-26-28": "unverifiable",
        "POLYCAB-wc-ebitda-11-13": "pending", "POLYCAB-fmeg-ebitda-8-10": "pending", "POLYCAB-capex-12-16bn": "pending",
        "POLYCAB-working-capital-days": "unverifiable", "POLYCAB-ehv-commissioning": "not_reaffirmed",
        "POLYCAB-cw-growth-1.5x": "pending", "POLYCAB-exports-10pct": "pending", "POLYCAB-epc-margin": "unverifiable",
        "POLYCAB-dividend-payout-30": "pending",
        "HDFCBANK-ldr-85-90": "pending", "HDFCBANK-ldr-fy26-90-96": "unverifiable",
        "HDFCBANK-growth-vs-system-fy26": "unverifiable",
        "HDFCBANK-growth-vs-system-fy27": "pending", "HDFCBANK-msme-growth": "unverifiable",
        "HDFCBANK-margin-change-2q": "unverifiable"}
    assert "met" not in v.values() and "missed" not in v.values()


def test_working_capital_record_keeps_the_original_range_and_its_revision():
    wc = next(r for _, r in ALL if r["id"] == "POLYCAB-working-capital-days")
    assert "50 to 55 days" in wc["statement"]["quote"] and (wc["target"]["low"], wc["target"]["high"]) == (50, 55)
    first = next(f for f in wc["follow_ups"] if f["stance"] in promises.DECISIVE)
    assert first["stance"] == "tightened" and "45 to 50 days" in first["quote"] and "50 to 55" in first["note"]
    reported = [f for f in wc["follow_ups"] if f["stance"] == "reported"]
    assert [f["quarter"] for f in reported] == ["Q3 FY26", "Q4 FY26", "Q1 FY27", "Q2 FY27"]   # management's own cycle, unchecked
    assert all("not checked" in f["note"] for f in reported)
    assert wc["verdict"]["status"] == "unverifiable"                # undated, and days are not in the snapshot


def test_audit_notes_cite_the_statement_page_they_describe():
    ex = next(r for _, r in ALL if r["id"] == "POLYCAB-exports-10pct")
    assert ex["statement"]["page"] == 8 and "p.8 sentence" in ex["audit_note"]
    assert any(m["symbol"] == "POLYCAB" and m["page"] == 8 and "exports" in m["why"] for m in AUDIT["known_misses"])


def test_fy26_ldr_record_is_unverifiable_not_missed():
    r = next(r for _, r in ALL if r["id"] == "HDFCBANK-ldr-fy26-90-96")
    assert r["statement"]["page"] == 6 and "90% to 96% in the year FY '26" in r["statement"]["quote"]
    assert r["statement"]["role"] == "management" and r["horizon"]["period_end"] == "2026-03-31"
    assert r["outcome"]["method"] == "not_computed"
    assert r["verdict"]["status"] == "unverifiable" and "horizon has passed" in r["verdict"]["reason"]
    assert any(m["symbol"] == "HDFCBANK" and m["page"] == 6 for m in AUDIT["known_misses"])


def test_fy27_ldr_clarification_is_recorded_without_changing_the_target():
    r = next(r for _, r in ALL if r["id"] == "HDFCBANK-ldr-85-90")
    assert (r["target"]["low"], r["target"]["high"]) == (85, 90) and r["statement"]["page"] == 6
    p8 = [f for f in r["follow_ups"] if f["quarter"] == "Q3 FY26" and f["page"] == 8]
    assert [f["stance"] for f in p8] == ["explained", "explained"]              # interpretation, never withdrawal
    assert "broad range" in p8[0]["quote"] and p8[0]["prompted_by"]["role"] == "analyst"
    assert not any("FY '26" in f["quote"] for f in p8)                         # FY26 figures stay on the FY26 record
    assert r["verdict"]["status"] == "pending"


def test_horizon_and_chronology_corrections_from_the_review():
    by = {r["id"]: r for _, r in ALL}
    cw = by["POLYCAB-cw-growth-1.5x"]
    assert cw["horizon"]["stated"] is True and cw["horizon"]["period_end"] == "2030-03-31"
    assert any("until FY30" in f["quote"] for f in cw["follow_ups"])            # the horizon is quoted, not inferred
    asp = by["TCS-aspiration-26-28"]
    assert (asp["statement"]["quarter"], asp["statement"]["page"]) == ("Q3 FY26", 23)
    assert asp["statement"]["speaker"] == "Samir Seksaria" and asp["statement"]["role"] == "management"


def test_audit_labels_cover_every_candidate():
    a = LEDGER["audit"]
    assert a["candidates"] == a["labelled"] == 164
    assert a["unlabelled_candidates"] == [] and a["labels_without_candidate"] == []
    assert a["labels"]["analyst"] == 44
    assert len(a["known_misses"]) == 7
    assert a["labels"] == {"analyst": 44, "explicit_numeric": 35, "measurable_qualitative": 14, "commentary": 29,
                           "actual_report": 12, "not_guidance": 30}


def test_every_relabel_is_logged_with_a_reason():
    items = {x["key"]: x["label"] for x in AUDIT["items"]}
    assert len(AUDIT["relabels"]) == 6
    for r in AUDIT["relabels"]:
        assert items[r["key"]] == r["to"] != r["from"] and r["why"]
    polycab = [(r["quarter"], r["page"]) for r in AUDIT["relabels"] if r["symbol"] == "POLYCAB"]
    assert sorted(polycab) == [("Q3 FY26", 5), ("Q3 FY26", 5), ("Q3 FY26", 7), ("Q3 FY26", 20), ("Q4 FY26", 7)]
    assert {r["to"] for r in AUDIT["relabels"] if r["symbol"] == "POLYCAB"} == {"actual_report"}


def test_hdfcbank_verdicts_do_not_rest_on_answers_that_omit_the_target():
    by = {r["id"]: r for _, r in ALL}
    for rid in ("HDFCBANK-ldr-85-90", "HDFCBANK-growth-vs-system-fy27"):
        r = by[rid]
        assert r["verdict"]["status"] == "pending"
        assert not [f for f in r["follow_ups"] if f["stance"] in promises.WEAKER]
        assert "not treat as withdrawal" in r["verdict"]["reason"]
    ldr = by["HDFCBANK-ldr-85-90"]
    assert ldr["statement"]["quote"].endswith("85% to 90% for FY '27.")                   # source quote preserved
    assert any("constrained by the CD ratio" in f["quote"] and f["quarter"] == "Q3 FY26" for f in ldr["follow_ups"])
    for rid in ("HDFCBANK-growth-vs-system-fy26", "HDFCBANK-growth-vs-system-fy27"):
        assert "loan growth" not in by[rid]["title"] and "'top line'" in by[rid]["title"]   # measure is not defined


def test_every_record_states_its_scope_and_only_consolidated_scope_is_computed():
    for _, r in ALL:
        assert r["scope"]
        if r["outcome"]["method"] == "computed":
            assert r["scope"] == "consolidated"
    wc = next(r for _, r in ALL if r["id"] == "POLYCAB-wc-ebitda-11-13")
    assert wc["scope"] == "segment: Wires & Cables" and "EBIT" in wc["audit_note"]


# --- verdict rules on SYNTHETIC records ----------------------------------------------------------------------

def _syn(**kw):
    rec = {"id": "SYNTHETIC", "symbol": "SYN", "kind": "explicit_numeric", "metric": "ebit_margin", "scope": "consolidated",
           "target": {"low": 25, "high": None, "unit": "%"}, "horizon": {"period_end": "2027-03-31"}, "follow_ups": []}
    rec.update(kw)
    return rec


def _f(stance, quarter="Q2 FY27", page=1):
    return {"stance": stance, "quarter": quarter, "page": page}


def test_silence_never_changes_a_verdict():
    out = {"method": "not_computed", "status": None, "reason": "x"}
    assert promises.verdict(_syn(), out, "2026-10-27")["status"] == "pending"
    assert promises.verdict(_syn(horizon={"period_end": "2026-03-31"}), out, "2026-10-27")["status"] == "unverifiable"


def test_latest_weaker_statement_means_not_reaffirmed_but_a_later_restatement_clears_it():
    out = {"method": "not_computed", "status": None, "reason": "x"}
    for s in ("softened", "widened", "delayed"):
        assert promises.verdict(_syn(follow_ups=[_f(s)]), out, "2026-10-27")["status"] == "not_reaffirmed"
    v = promises.verdict(_syn(follow_ups=[_f("widened"), _f("restated")]), out, "2026-10-27")
    assert v["status"] == "pending" and "later restated" in v["reason"]


def test_answers_that_do_not_repeat_a_target_neither_withdraw_nor_clear_it():
    out = {"method": "not_computed", "status": None, "reason": "x"}
    for neutral in ("not_restated", "reported", "explained"):
        assert promises.verdict(_syn(follow_ups=[_f(neutral), _f(neutral)]), out, "2026-10-27")["status"] == "pending"
        assert promises.verdict(_syn(follow_ups=[_f("softened"), _f(neutral)]), out, "2026-10-27")["status"] == "not_reaffirmed"


def test_commentary_is_never_scored():
    out = {"method": "computed", "status": None, "reason": "context only"}
    assert promises.verdict(_syn(kind="commentary"), out, "2026-10-27")["status"] == "unverifiable"


def test_only_a_reported_closed_period_can_be_met_or_missed():
    con = sqlite3.connect(f"file:{SNAP}?mode=ro&immutable=1", uri=True)
    try:
        open_ = promises.compute_outcome(_syn(symbol="TCS"), con)
        assert open_["status"] == "pending"
        closed = promises.compute_outcome(_syn(symbol="TCS", horizon={"period_end": "2026-09-30"}), con)
        assert closed["status"] == "missed"                       # 23.98 < 25 on a reported quarter
        met = promises.compute_outcome(_syn(symbol="TCS", target={"low": 23, "high": 25, "unit": "%"},
                                            horizon={"period_end": "2026-09-30"}), con)
        assert met["status"] == "met"
        seg = promises.compute_outcome(_syn(symbol="POLYCAB", metric="segment_ebitda_margin:wires_and_cables"), con)
        assert seg["method"] == "not_computed"                    # consolidated EBITDA exists but is not the metric
        scoped = promises.compute_outcome(_syn(symbol="TCS", scope="segment: BFSI"), con)
        assert scoped["method"] == "not_computed" and "consolidated" in scoped["reason"]   # metric right, scope wrong
    finally:
        con.close()
    assert promises.verdict(_syn(), closed, "2026-10-27")["status"] == "missed"
    assert promises.verdict(_syn(follow_ups=[_f("restated")]), open_, "2026-10-27")["status"] == "pending"


def test_shape_validation():
    assert promises._validate_shape({**_syn(), "title": "t", "statement": {}, "interpretation": "",
                                     "target": None}) == ["explicit_numeric without a numeric target"]
    no_scope = {k: v for k, v in _syn().items() if k != "scope"}
    assert "missing field scope" in promises._validate_shape({**no_scope, "title": "t", "statement": {}, "interpretation": ""})
    assert "unknown stance" in " ".join(promises._validate_shape(
        {**_syn(), "title": "t", "statement": {}, "interpretation": "", "follow_ups": [{"stance": "confirmed"}]}))


# --- API -------------------------------------------------------------------------------------------------------

def test_promises_endpoint_serves_the_ledger():
    s, b = call("/api/v1/companies/TCS/promises")
    assert s == "200 OK" and b["status"] == "ok" and b["stale"] is False
    assert [r["id"] for r in b["records"]] == ["TCS-ebit-exit-25", "TCS-aspiration-26-28"]
    assert b["ledger"]["snapshot_digest"] == b["snapshot"]["content_digest"]
    s, b = call("/api/v1/companies/polycab/promises")
    assert s == "200 OK" and len(b["records"]) == 9


def test_promises_for_unaudited_and_unknown_companies_are_honest():
    s, b = call("/api/v1/companies/ITC/promises")
    assert s == "200 OK" and b["status"] == "not_audited" and b["records"] == []
    s, b = call("/api/v1/companies/ZOMATOX/promises")
    assert s == "404 Not Found"


def test_stale_and_missing_ledger(monkeypatch, tmp_path):
    led = copy.deepcopy(LEDGER)
    led["built_from"]["snapshot_digest"] = "0" * 64
    p = tmp_path / "promise_ledger.json"
    p.write_text(json.dumps(led))
    monkeypatch.setattr(api, "ledger_path", lambda: p)
    s, b = call("/api/v1/companies/TCS/promises")
    assert b["status"] == "stale" and b["stale"] is True and "different snapshot" in b["stale_reason"]
    monkeypatch.setattr(api, "ledger_path", lambda: tmp_path / "absent.json")
    s, b = call("/api/v1/companies/TCS/promises")
    assert s == "200 OK" and b["status"] == "unavailable" and b["records"] == []


def test_promises_endpoint_is_listed():
    _, b = call("/api/v1")
    assert any("promises" in e for e in b["endpoints"])


# --- human-review pack ------------------------------------------------------------------------------------------

def _review_pack():
    import importlib.util
    spec = importlib.util.spec_from_file_location("promise_review_pack", ROOT / "scripts" / "promise_review_pack.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_review_pack_is_generated_from_the_current_ledger():
    pack = _review_pack()
    text = pack.render()
    assert pack.OUT.read_text(encoding="utf-8") == text, "run python scripts/promise_review_pack.py"
    for _, r in ALL:
        for q in [r["statement"], *r["follow_ups"], *[f["prompted_by"] for f in r["follow_ups"] if f.get("prompted_by")]]:
            assert q["quote"].replace("|", "\\|") in text and f"({q['url']}#page={q['page']})" in text


def test_review_pack_marks_only_decisions_a_person_made():
    text = _review_pack().render()
    prompts = json.loads((ROOT / "config" / "promise_review_questions.json").read_text(encoding="utf-8"))
    reviews = json.loads((ROOT / "config" / "promise_reviews.json").read_text(encoding="utf-8"))["reviews"]
    assert set(prompts["questions"]) == {r["id"] for _, r in ALL}
    assert set(reviews) == {"TCS-ebit-exit-25"}                      # R01 is the only record the reviewer decided personally
    assert text.count("**Status: PENDING. Not reviewed by a person.**") == len(ALL) - len(reviews)
    assert text.count("**Status: REVIEWED BY A PERSON:") == len(reviews)
    assert text.count("☑") == len(reviews) and "[x]" not in text.lower()   # one overall box per review; no check ticked on anyone's behalf
    blocks = text.split("\n### ")
    for _, r in ALL:
        block = next(b for b in blocks if b.startswith(f"R") and f" · {r['id']}\n" in b.split("\n", 1)[0] + "\n")
        assert ("☑" in block) == (r["id"] in reviews)
    assert "not yet reviewed by a person" in LEDGER["audited_by"]   # 16 of 17 records are still unreviewed


def test_a_review_no_longer_matching_the_verdict_is_refused(monkeypatch, tmp_path):
    pack = _review_pack()
    data = json.loads(pack.REVIEWS.read_text(encoding="utf-8"))
    data["reviews"]["TCS-ebit-exit-25"]["verdict_confirmed"] = "not_reaffirmed"
    stale = tmp_path / "reviews.json"
    stale.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(pack, "REVIEWS", stale)
    with pytest.raises(SystemExit, match="does not match the ledger"):
        pack.render()


# --- real transcripts (raw cache) ------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def docs():
    d = promises.load_transcripts(SNAP)
    if any(x["pages"] is None for x in d):
        pytest.skip("transcript PDFs not in the raw cache (data/raw, git-ignored); run python -m finn.snapshot build")
    return d


def _doc(docs, sym, q):
    d = next(x for x in docs if x["symbol"] == sym and x["fiscal_quarter"] == q)
    turns = promises.speaker_turns(d["pages"])
    return d, turns, promises.assign_roles(d["pages"], turns)


def test_build_reproduces_the_committed_ledger(docs):
    assert promises.build(out=None, docs=docs) == LEDGER


def test_quote_gate_rejects_paraphrase_wrong_page_wrong_speaker_and_analyst(docs):
    d, turns, roles = _doc(docs, "TCS", "Q1 FY27")
    ok = {"quote": "We want to exit at 25% plus and strive to achieve it sooner rather than later.", "page": 23,
          "speaker": "Samir Seksaria"}
    ev, probs = promises.check_quote(ok, d["pages"], turns, roles, "management")
    assert probs == [] and ev["role"] == "management"
    para = {**ok, "quote": "We want to exit at 25% or more and try to achieve it sooner rather than later."}
    assert promises.check_quote(para, d["pages"], turns, roles, "management")[0] is None
    assert "found on p.23" in promises.check_quote({**ok, "page": 22}, d["pages"], turns, roles, "management")[1][0]
    assert "belongs to 'Samir Seksaria'" in promises.check_quote({**ok, "speaker": "K Krithivasan"}, d["pages"], turns,
                                                                  roles, "management")[1][0]
    d, turns, roles = _doc(docs, "TCS", "Q2 FY27")
    q = {"quote": "In that context, how do we think about the margin commitment we had made around exiting FY27, at 25% "
                  "plus EBIT margin range?", "page": 16, "speaker": "Ruchi Mukhija"}
    _, probs = promises.check_quote(q, d["pages"], turns, roles, "management")
    assert any("is analyst" in p for p in probs)


def test_roles_from_the_documents(docs):
    _, turns, roles = _doc(docs, "TCS", "Q2 FY27")
    assert roles.role["K Krithivasan"] == "management"            # single-letter initial is a speaker here
    _, _, roles = _doc(docs, "HDFCBANK", "Q3 FY26")
    assert roles.role["Mahrukh Adajania"] == "analyst"
    seen = 0
    for q in ("Q3 FY26", "Q4 FY26", "Q1 FY27", "Q2 FY27"):
        r = promises.candidates(next(x for x in docs if x["symbol"] == "HDFCBANK" and x["fiscal_quarter"] == q),
                                frozenset({"Kaizad Bharucha", "Sashidhar Jagdishan", "Srinivasan Vaidyanathan"}))
        if "Kaizad Bharucha" in r["roles"]:
            seen += 1
            assert r["roles"]["Kaizad Bharucha"]["role"] == "management", q
    assert seen >= 3
    d, turns, roles = _doc(docs, "POLYCAB", "Q3 FY26")
    assert not [s for s, r in roles.role.items() if r == "management" and (s.isupper() or s in promises.NOT_A_SPEAKER)]


def test_analyst_labels_agree_with_document_roles(docs):
    labels = {x["key"]: x["label"] for x in AUDIT["items"]}
    heads = {}
    for d in docs:
        heads.setdefault(d["symbol"], set()).update(transcripts.management_names(d["pages"]))
    for d in docs:
        for c in promises.candidates(d, frozenset(heads[d["symbol"]]))["candidates"]:
            lab = labels[promises.candidate_key(d["symbol"], d["fiscal_quarter"], c["text"])]
            assert (lab == "analyst") == (c["role"] == "analyst"), (d["symbol"], d["fiscal_quarter"], c["page"])


def test_build_excludes_a_tampered_record(docs, tmp_path):
    cfg = copy.deepcopy(RECORDS)
    r = next(x for x in cfg["records"] if x["id"] == "TCS-ebit-exit-25")
    r["statement"]["quote"] = "We want to exit at 26% plus and strive to achieve it sooner rather than later."
    a = next(x for x in cfg["records"] if x["id"] == "TCS-aspiration-26-28")
    a["statement"] = {"quarter": "Q2 FY27", "page": 15, "speaker": "Ravi Menon",
                      "quote": "To get back towards 26%, which is the aspirational margin, do you think that we'll be able "
                               "to bring down subcontracting costs over time, or what are the key levers that could take "
                               "you towards 26%?"}
    p = tmp_path / "records.json"
    p.write_text(json.dumps(cfg))
    led = promises.build(records_path=p, out=None, docs=docs)
    ex = {e["id"]: e["problems"] for e in led["companies"]["TCS"]["excluded"]}
    assert "quote not found" in ex["TCS-ebit-exit-25"][0]
    assert any("is analyst" in x for x in ex["TCS-aspiration-26-28"])
    assert led["companies"]["TCS"]["records"] == []
