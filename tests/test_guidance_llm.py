"""Guidance contract + LLM-optional behaviour. No network, no credentials needed."""
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from finn import llm
from finn.guidance import GUIDANCE_SCHEMA, GuidanceItem, admit, judge_band
from finn.models import SourceRef
from finn.transcripts import fix_numeric_o, locate_quote, management_names, normalise, speaker_turns

EXP = json.loads((Path(__file__).parent / "fixtures" / "real" / "guidance_experiment.json").read_text())


def pages_of(sym):
    t = EXP["transcripts"][sym]["pages"]
    n = max(int(k) for k in t)
    return [t.get(str(i), "") for i in range(1, n + 1)]


@pytest.mark.parametrize("item", EXP["items"], ids=lambda i: f"{i['symbol']}-p{i['page']}-{i['kind']}")
def test_every_labelled_quote_is_located_on_its_page(item):
    q = locate_quote(item["quote"], pages_of(item["symbol"]), item["page"])
    assert q.ok and q.page == item["page"]


def test_paraphrase_is_rejected():
    paraphrase = "we are confident of sustaining EBITDA margins of 11% to 13% over the medium to long term"
    assert not locate_quote(paraphrase, pages_of("POLYCAB")).ok


def test_line_break_quote_needs_normalised_match():
    item = next(i for i in EXP["items"] if i["kind"] == "analyst_claim" and i["symbol"] == "POLYCAB")
    flat = " ".join(item["quote"].split())
    q = locate_quote(flat, pages_of("POLYCAB"), 8)
    assert q.ok and q.method == "normalised"


def test_text_artefacts():
    assert fix_numeric_o("Net profit 2O7OO.O3 for 3O.O9.2O26 On time") == "Net profit 20700.03 for 30.09.2026 On time"
    assert normalise("reﬂects taper o Ư diƯicult") == "reflects taper off difficult"
    assert normalise("medium - to long -term") == "medium-to long-term"


def test_speaker_carried_across_pages():
    pages = ["Samir Seksaria: margins will\n", "continue to inch up.\nRuchi Mukhija: Thank you.\n"]
    turns = speaker_turns(pages)
    assert [(t.speaker, t.page) for t in turns] == [("Samir Seksaria", 1), ("Ruchi Mukhija", 2)]
    assert "inch up" in turns[0].text


def test_management_header_parsed():
    names = management_names(pages_of("POLYCAB"))
    assert {"Niyant Maru", "Aditya Nathany", "Nikhil Jaisinghani"} <= names


def _item(**kw):
    # The POLYCAB 11-13% band is Wires & Cables segment guidance (corrected in Prompt 5; see the fixture's
    # metric_correction). Only the admission gate is tested here; no outcome is computed for it.
    base = dict(symbol="POLYCAB", quote=EXP["items"][0]["quote"], kind="explicit_numeric", speaker=None,
                speaker_role="management", said_on=date(2026, 10, 15),
                source=SourceRef("transcript", "fixture", datetime.now(timezone.utc), None, "fixture", location="p.7"),
                metric=EXP["items"][0]["metric"], target_low=11, target_high=13, target_unit="%")
    base.update(kw)
    return GuidanceItem(**base)


def test_polycab_band_is_labelled_as_segment_guidance():
    item = EXP["items"][0]
    assert item["symbol"] == "POLYCAB" and (item["lo"], item["hi"]) == (11, 13)
    assert item["metric"] == "segment_ebitda_margin:wires_and_cables"
    assert item["metric_as_first_labelled"] == "ebitda_margin" and "14.37" in item["metric_correction"]
    assert "Wires and Cables segment" in pages_of("POLYCAB")[6]     # the page the quote sits on says so


def test_admit_gate():
    pages = pages_of("POLYCAB")
    assert admit(_item(), pages, 7)[0]
    assert admit(_item(quote="EBITDA margins of 14% to 16% by FY30 are assured"), pages, 7) == (False, "quote not found in source text")
    assert not admit(_item(target_low=None, target_high=None), pages, 7)[0]
    assert not admit(_item(speaker_role="analyst"), pages, 7)[0]


# SYNTHETIC actuals that exercise judge_band on an 11-13 band. They are not POLYCAB outcomes: 14.37 was POLYCAB's
# consolidated EBITDA margin, which is not comparable with this segment band (Prompt 5 correction). The cases are kept
# so that the band logic stays tested, and "missed"/"pending" here say nothing about POLYCAB.
@pytest.mark.parametrize("actual,closed,verdict", [
    (12.0, True, "met"), (14.37, True, "missed"), (14.37, False, "pending"), (None, True, "unverifiable")])
def test_band_verdicts_are_deterministic(actual, closed, verdict):
    assert judge_band(actual, 11, 13, closed)[0] == verdict


# ---------- LLM optional ----------

@dataclass
class FakeProvider:
    responses: list
    name: str = "fake"
    model: str = "fake-1"
    calls: int = 0

    def complete_json(self, system, user, schema):
        self.calls += 1
        r = self.responses[min(self.calls - 1, len(self.responses) - 1)]
        if isinstance(r, Exception):
            raise r
        return r


GOOD = json.dumps({"items": [{"quote": "x" * 20, "page": 7, "kind": "commentary", "speaker": None, "metric": None,
                              "target_low": None, "target_high": None, "target_unit": None,
                              "forecast_period": None, "conditions": None}]})


def run(p, tmp_path, text="transcript text v1"):
    return llm.CachedExtractor(p, tmp_path).run(prompt_version="t", system="s", text=text, schema=GUIDANCE_SCHEMA)


def test_missing_credentials_degrades(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    r = run(llm.default_provider(), tmp_path)
    assert (r.ok, r.status) == (False, "unavailable")


def test_rate_limit_degrades(tmp_path):
    r = run(FakeProvider([llm.LLMUnavailable("RateLimitError")]), tmp_path)
    assert r.status == "unavailable" and "RateLimit" in r.reason


def test_malformed_then_valid_retries_once(tmp_path):
    p = FakeProvider(["{not json", GOOD])
    r = run(p, tmp_path)
    assert r.ok and p.calls == 2


def test_schema_violation_twice_is_invalid(tmp_path):
    bad = json.dumps({"items": [{"quote": "x", "kind": "promise"}]})
    r = run(FakeProvider([bad, bad]), tmp_path)
    assert r.status == "invalid" and "schema" in r.reason


def test_unchanged_document_not_resent_changed_document_is(tmp_path):
    p = FakeProvider([GOOD])
    assert run(p, tmp_path).status == "ok"
    assert run(p, tmp_path).status == "cached" and p.calls == 1
    assert run(p, tmp_path, text="transcript text v2").status == "ok" and p.calls == 2


def test_validator():
    assert llm.validate({"a": 1}, {"type": "object", "required": ["a", "b"], "properties": {"a": {"type": "string"}}}) == \
        ["$.b: required", "$.a: expected ['string'], got int"]
