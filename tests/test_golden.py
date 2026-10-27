"""Golden set: XBRL parsing must reproduce values transcribed from the signed results PDFs."""
import json
from datetime import date, datetime, timezone
from decimal import Decimal as D
from pathlib import Path

import pytest

from finn import metrics
from finn.adapters import nse_results
from finn.models import SourceRef

FIX = Path(__file__).parent / "fixtures" / "real"
GOLD = json.loads((FIX / "golden_set.json").read_text())
TAX = {"TCS": "indas", "POLYCAB": "indas", "HDFCBANK": "banking"}
QE = {"2026-09-30": "30-SEP-2026", "2026-06-30": "30-JUN-2026", "2025-09-30": "30-SEP-2025"}


def extracted(symbol: str, period_end: str) -> dict:
    p = nse_results.parse_instance((FIX / f"xbrl_{symbol}_{QE[period_end]}_C.xml").read_bytes())
    ctx = nse_results.quarter_context(p, date.fromisoformat(period_end))
    src = SourceRef("xbrl_result", "fixture", datetime(2026, 10, 27, tzinfo=timezone.utc), None, "fixture")
    return metrics.extract(p, ctx, TAX[symbol], symbol=symbol, basis="consolidated", source=src)


@pytest.mark.parametrize("g", GOLD["observations"], ids=lambda g: f"{g['symbol']}-{g['period_end']}-{g['metric']}")
def test_matches_signed_pdf(g):
    unit = GOLD["documents"][g["doc"]]["unit"]
    expected = metrics.from_reported(D(g["reported"]), unit)
    got = extracted(g["symbol"], g["period_end"])[g["metric"]]
    assert got.status in ("extracted", "derived")
    assert metrics.to_crore(got.value) == metrics.to_crore(expected), g["line"]


def test_quarter_context_selected_by_dates_not_name():
    o = extracted("TCS", "2026-09-30")["revenue"]
    assert (o.period_start, o.period_end, o.months) == (date(2026, 7, 1), date(2026, 9, 30), 3)


@pytest.mark.parametrize("sym", ["TCS", "POLYCAB"])
@pytest.mark.parametrize("pe", list(QE))
def test_ebitda_reconciles_to_screener_operating_profit(sym, pe):
    """Secondary cross-check only: screener rounds to whole crores."""
    ebitda = metrics.to_crore(extracted(sym, pe)["ebitda"].value)
    assert abs(ebitda - D(GOLD["screener_crosscheck_crore"][sym][pe]["operating_profit"])) <= 1


def test_ebitda_excludes_exceptional_items():
    o = extracted("TCS", "2026-06-30")
    assert metrics.to_crore(o["exceptional"].value) == D("-668.00")
    assert metrics.to_crore(o["ebitda"].value) == D("18556.00")      # not 17,888


def test_hand_computed_changes():
    cur, q, y = (extracted("TCS", pe) for pe in ("2026-09-30", "2026-06-30", "2025-09-30"))
    assert metrics.compare(cur["revenue"], q["revenue"], "qoq").pct == D("1.26")     # 913 / 72,275
    assert metrics.compare(cur["revenue"], y["revenue"], "yoy").pct == D("11.23")    # 7,389 / 65,799
    hc, hq = extracted("HDFCBANK", "2026-09-30"), extracted("HDFCBANK", "2026-06-30")
    assert metrics.compare(hc["pat"], hq["pat"], "qoq").pct == D("7.56")             # 1,455.32 / 19,244.71


def test_bank_ebitda_not_applicable_and_no_revenue_relabel():
    o = extracted("HDFCBANK", "2026-09-30")
    assert o["ebitda"].status == "not_applicable" and o["ebitda"].value is None
    assert "revenue" not in o
    assert metrics.HEADLINE["banking"][0] == "total_income"


def test_bank_minority_mistag_detected_and_corrected():
    sep, jun = extracted("HDFCBANK", "2026-09-30"), extracted("HDFCBANK", "2026-06-30")
    assert sep["pbt"].formula == metrics.BANK_PBT_FORMULA and "mis-tagged" in sep["pbt"].note
    assert jun["pbt"].status == "extracted"                       # correctly tagged quarter untouched
    assert any(c["status"] == "warn" for c in metrics.integrity_checks(sep, "banking"))


def test_standalone_bank_exceptional_is_not_reinterpreted():
    p = nse_results.parse_instance((FIX / "xbrl_HDFCBANK_30-SEP-2026_C.xml").read_bytes())
    ctx = nse_results.quarter_context(p, date(2026, 9, 30))
    src = SourceRef("xbrl_result", "fixture", datetime(2026, 10, 27, tzinfo=timezone.utc), None, "fixture")
    o = metrics.extract(p, ctx, "banking", symbol="HDFCBANK", basis="standalone", source=src)
    assert o["pbt"].reported_tag == "ProfitLossFromOrdinaryActivitiesBeforeTax"


@pytest.mark.parametrize("sym", list(TAX))
@pytest.mark.parametrize("pe", list(QE))
def test_integrity_identities_hold(sym, pe):
    checks = metrics.integrity_checks(extracted(sym, pe), TAX[sym])
    assert not [c for c in checks if c["status"] == "fail"], checks


def test_missing_input_makes_ebitda_missing_not_zero():
    p = nse_results.parse_instance((FIX / "xbrl_TCS_30-SEP-2026_C.xml").read_bytes())
    p["facts"] = {k: v for k, v in p["facts"].items() if k[0] != "FinanceCosts"}
    src = SourceRef("xbrl_result", "fixture", datetime(2026, 10, 27, tzinfo=timezone.utc), None, "fixture")
    o = metrics.extract(p, "OneD", "indas", symbol="TCS", basis="consolidated", source=src)
    assert o["ebitda"].status == "missing" and o["ebitda"].value is None and "finance_costs" in o["ebitda"].note
