"""Deterministic calculations. Synthetic inputs here are arithmetic cases, not financial data."""
from datetime import date, datetime, timezone
from decimal import Decimal as D

import pytest

from finn import metrics
from finn.models import Observation, SourceRef

SRC = SourceRef("xbrl_result", "synthetic://test", datetime(2026, 10, 27, tzinfo=timezone.utc), None, "fixture")


def obs(metric="revenue", value=D(100), start=date(2026, 7, 1), end=date(2026, 9, 30), basis="consolidated"):
    return Observation("X", metric, value, start, end, basis, "extracted", SRC)


class TestPctChange:
    def test_normal(self):
        c = metrics.pct_change(D("73188"), D("72275"))
        assert (c.status, c.pct) == ("ok", D("1.26"))

    def test_decline(self):
        assert metrics.pct_change(D(90), D(100)).pct == D("-10.00")

    def test_valid_zero_current_is_not_missing(self):
        c = metrics.pct_change(D(0), D(50))
        assert (c.status, c.pct) == ("ok", D("-100.00"))

    def test_zero_base(self):
        assert metrics.pct_change(D(10), D(0)).status == "zero_base"

    @pytest.mark.parametrize("cur,prev", [(None, D(1)), (D(1), None), (None, None)])
    def test_missing(self, cur, prev):
        c = metrics.pct_change(cur, prev)
        assert c.status == "missing" and c.pct is None

    def test_sign_change_loss_to_profit(self):
        c = metrics.pct_change(D(50), D(-20))
        assert c.status == "sign_change" and c.pct is None

    def test_both_negative_shrinking_loss(self):
        c = metrics.pct_change(D(-50), D(-100))
        assert (c.status, c.pct) == ("negative_base", D("50.00"))


class TestMargin:
    def test_margin(self):
        assert metrics.margin(D("18815"), D("73188")) == D("25.71")

    @pytest.mark.parametrize("num,rev", [(None, D(1)), (D(1), None), (D(1), D(0)), (D(1), D(-5))])
    def test_refuses(self, num, rev):
        assert metrics.margin(num, rev) is None


class TestPeriods:
    @pytest.mark.parametrize("end,qoq", [
        (date(2026, 9, 30), date(2026, 6, 30)), (date(2026, 6, 30), date(2026, 3, 31)),
        (date(2026, 3, 31), date(2025, 12, 31)), (date(2025, 12, 31), date(2025, 9, 30)),
    ])
    def test_quarter_before(self, end, qoq):
        assert metrics.expected_prior(end, "qoq") == qoq

    def test_yoy(self):
        assert metrics.expected_prior(date(2026, 9, 30), "yoy") == date(2025, 9, 30)

    def test_align_ok(self):
        prev = obs(start=date(2026, 4, 1), end=date(2026, 6, 30))
        assert metrics.align(obs(), prev, "qoq") is None

    def test_basis_mismatch_rejected(self):
        prev = obs(start=date(2026, 4, 1), end=date(2026, 6, 30), basis="standalone")
        c = metrics.compare(obs(), prev, "qoq")
        assert c.status == "misaligned" and "basis" in c.note

    def test_ytd_never_compared(self):
        ytd = obs(start=date(2026, 4, 1), end=date(2026, 9, 30))
        prev = obs(start=date(2025, 4, 1), end=date(2025, 9, 30))
        assert "single quarters" in metrics.align(ytd, prev, "yoy")

    def test_wrong_comparator_period(self):
        prev = obs(start=date(2026, 1, 1), end=date(2026, 3, 31))
        assert "expected period ending 2026-06-30" in metrics.align(obs(), prev, "qoq")

    def test_missing_comparator(self):
        assert metrics.compare(obs(), None, "yoy").status == "missing"


class TestUnits:
    def test_reported_units(self):
        # POLYCAB prints millions, TCS/HDFCBANK print crores (verified PDFs); same absolute INR result.
        assert metrics.from_reported(D("98989.01"), "millions") == D("98989010000.00")
        assert metrics.to_crore(metrics.from_reported(D("98989.01"), "millions")) == D("9898.90")
        assert metrics.from_reported(D("73188"), "Crores") == metrics.from_reported(D("7318800"), "lakhs")

    def test_unknown_unit_raises(self):
        with pytest.raises(ValueError):
            metrics.from_reported(D(1), "thousands of rupees")
