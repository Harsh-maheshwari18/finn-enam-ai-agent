"""End-to-end UI tests: the real web app in headless Chromium at 360 x 780 CSS px, served by the real WSGI app over
the committed snapshot. Failures (timeout, 429, 500) are injected by intercepting requests in the browser; the
data itself is never mocked.

Needs Playwright + Chromium (not a runtime dependency): see docs/frontend.md. Skipped, with the reason, otherwise.
"""
import json
import os
import threading
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, make_server

import pytest

sync_api = pytest.importorskip("playwright.sync_api", reason="Playwright not installed (dev-only, see docs/frontend.md)")

from finn import api  # noqa: E402

ROOT = Path(__file__).parent.parent
SNAP = Path(os.environ.get("FINN_UI_TEST_SNAPSHOT") or ROOT / "snapshot" / "finn_snapshot.db")   # override: a candidate build
W, H = 360, 780


class _Quiet(WSGIRequestHandler):
    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def base_url():
    os.environ["FINN_SNAPSHOT"] = str(SNAP)
    srv = make_server("127.0.0.1", 0, api.app, handler_class=_Quiet)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}/"
    srv.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:                                      # browser binary or system libraries missing
            pytest.skip(f"Chromium could not start: {str(e).splitlines()[0]}")
        yield b
        b.close()


@pytest.fixture
def page(browser, base_url):
    ctx = browser.new_context(viewport={"width": W, "height": H}, has_touch=True, is_mobile=True)
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.base = base_url
    yield pg
    assert pg.errors == [], f"JavaScript errors: {pg.errors}"
    ctx.close()


def go(pg, route):
    pg.goto(pg.base + route)


def no_horizontal_scroll(pg):
    assert pg.evaluate("document.documentElement.scrollWidth") <= W, "page scrolls horizontally at 360 px"


def api_json(pg, path):
    return pg.evaluate(f"fetch({json.dumps(path)}).then(r => r.json())")


# ---------------------------------------------------------------- signals

def test_signal_inbox_loads_real_ranked_cards(page):
    go(page, "#/signals")
    page.wait_for_selector("[data-testid=summary]")
    no_horizontal_scroll(page)
    body = api_json(page, "/api/v1/signals?window=24h&move_pct=5&volume_x=2&lookback=20")
    cards = page.locator("[data-testid=signal-card]")
    assert cards.count() == len(body["signals"])
    if body["signals"]:
        assert cards.first.get_attribute("data-id") == body["signals"][0]["id"]
    assert "not live" in page.inner_text("#fresh") and "Snapshot" in page.inner_text("#fresh")


def test_window_control_changes_records(page):
    go(page, "#/signals")
    page.wait_for_selector("[data-testid=summary]")
    n24 = page.locator("[data-testid=signal-card]").count()
    page.click("[data-win='30d']")
    page.wait_for_selector("[data-win='30d'][aria-pressed=true]")
    page.wait_for_selector("[data-testid=summary]")
    n30 = page.locator("[data-testid=signal-card]").count()
    expected = len(api_json(page, "/api/v1/signals?window=30d&move_pct=5&volume_x=2&lookback=20")["signals"])
    assert n30 == expected and n30 > n24
    assert "30 days window" in page.inner_text("[data-testid=summary]")


def test_company_and_priority_filters(page):
    go(page, "#/signals")
    page.click("[data-win='30d']")
    page.wait_for_selector("[data-win='30d'][aria-pressed=true]")
    syms = page.eval_on_selector_all("[data-testid=signal-card]", "els => els.map(e => e.dataset.symbol)")
    target = max(set(syms), key=syms.count)
    page.select_option("[data-testid=f-symbol]", target)
    shown = page.eval_on_selector_all("[data-testid=signal-card]", "els => els.map(e => e.dataset.symbol)")
    assert shown and set(shown) == {target} and len(shown) == syms.count(target)
    page.select_option("[data-testid=f-symbol]", "all")
    page.select_option("[data-testid=f-priority]", "high")
    pr = page.eval_on_selector_all("[data-testid=signal-card]", "els => els.map(e => e.dataset.priority)")
    assert set(pr) <= {"high"}
    if not pr:
        page.wait_for_selector("[data-testid=filtered-empty]")


def test_empty_state_is_a_checked_result_not_a_failure(page):
    every = ["results", "M&A", "management_change", "litigation", "fund_raise", "pledging", "credit_rating", "bonus_split",
             "capex", "dividend", "earnings_call", "press_release", "needs_review", "price_move", "volume_spike"]
    go(page, "#/signals")
    page.evaluate(f"localStorage.setItem('finn.settings.v1', JSON.stringify({{window:'24h', mute:{json.dumps(every)}}}))")
    page.reload()
    page.wait_for_selector("[data-testid=empty]")
    assert "not a loading failure" in page.inner_text("[data-testid=empty]")
    assert page.locator("[data-testid=error]").count() == 0


def test_network_failure_then_retry(page):
    page.route("**/api/v1/signals**", lambda route: route.abort("failed"))
    go(page, "#/signals")
    page.wait_for_selector("[data-testid=error]")
    text = page.inner_text("[data-testid=error]")
    assert "Can't reach" in text and "not the same as" in text
    page.unroute("**/api/v1/signals**")
    page.click("[data-testid=retry]")
    page.wait_for_selector("[data-testid=summary]")


@pytest.mark.parametrize("status, phrase", [(429, "Too many requests"), (503, "server had a problem"), (500, "server had a problem")])
def test_http_errors_are_explained(page, status, phrase):
    page.route("**/api/v1/signals**", lambda route: route.fulfill(status=status, content_type="application/json",
                                                                    body=json.dumps({"error": "injected by test"})))
    go(page, "#/signals")
    page.wait_for_selector("[data-testid=error]")
    assert phrase in page.inner_text("[data-testid=error]")
    assert page.locator("[data-testid=retry]").bounding_box()["height"] >= 44


def test_slow_server_shows_wake_up_state(page):
    held = []
    page.route("**/api/v1/signals**", lambda route: held.append(route))     # hold the request: a sleeping server
    go(page, "#/signals")
    page.wait_for_selector("[data-testid=loading]")
    page.wait_for_selector("[data-testid=loading] >> text=Waking the FINN server", timeout=8000)   # CSP forbids eval polling
    assert page.locator("[data-testid=signal-card]").count() == 0
    for r in held:
        r.continue_()                                                         # the server wakes up
    page.wait_for_selector("[data-testid=summary]", timeout=15000)
    page.unroute_all(behavior="ignoreErrors")


# ---------------------------------------------------------------- receipt

def _first_results_signal(page):
    d = api_json(page, "/api/v1/signals?window=30d&move_pct=5&volume_x=2&lookback=20")
    return next((s for s in d["signals"] if s["category"] == "results" and s.get("numbers") and s["numbers"]["rows"]), None)


def test_receipt_preserves_timezones_and_links_source(page):
    go(page, "#/signals")
    page.wait_for_selector("[data-testid=summary]")
    sig = _first_results_signal(page)
    assert sig, "the snapshot's 30-day window should hold at least one results filing with verified numbers"
    go(page, f"#/signal/{sig['id']}")
    page.wait_for_selector("[data-testid=receipt]")
    no_horizontal_scroll(page)
    assert page.inner_text("[data-testid=published-raw]") == sig["published_at"] and sig["published_at"].endswith("+05:30")
    assert page.inner_text("[data-testid=retrieved-raw]").endswith("+00:00")
    assert "IST" in page.inner_text("[data-testid=receipt]") and "UTC" in page.inner_text("[data-testid=receipt]")
    href = page.get_attribute("[data-testid=document] a", "href")
    assert href == sig["source"]["document_url"]
    assert "not a probability" in page.inner_text("[data-testid=receipt]")
    labels = page.eval_on_selector_all("[data-testid=metric-label]", "els => els.map(e => e.firstChild.textContent.trim())")
    assert labels == [r["label"] for r in sig["numbers"]["rows"]]
    page.click("[data-testid=open-research]")
    page.wait_for_selector("[data-testid=company]")
    assert sig["symbol"] in page.inner_text("[data-testid=company]")


# ---------------------------------------------------------------- research / results cards

def _metrics(page):
    return page.eval_on_selector_all("[data-testid=metrics] .mrow", """els => els.map(e => ({
        metric: e.dataset.metric, label: e.querySelector('[data-testid=metric-label]').firstChild.textContent.trim(),
        value: e.querySelector('[data-testid=metric-value]').innerText.trim()}))""")


def test_indas_results_card_matches_api_without_relabelling(page):
    go(page, "#/company/TCS")
    page.wait_for_selector("[data-testid=results-card]")
    no_horizontal_scroll(page)
    card = api_json(page, "/api/v1/companies/TCS/results")
    got = _metrics(page)
    assert [m["metric"] for m in got] == [r["metric"] for r in card["rows"]]
    assert [m["label"] for m in got] == [r["label"] for r in card["rows"]] == ["Revenue", "EBITDA", "PBT", "PAT"]
    rev = next(m for m in got if m["metric"] == "revenue")
    assert rev["value"] == "₹73,188.00 cr"
    assert "+05:30" in page.inner_text("[data-testid=results-card]")


def test_bank_card_keeps_bank_labels(page):
    go(page, "#/company/HDFCBANK")
    page.wait_for_selector("[data-testid=results-card]")
    labels = [m["label"] for m in _metrics(page)]
    card = api_json(page, "/api/v1/companies/HDFCBANK/results")
    assert labels == [r["label"] for r in card["rows"]]
    assert "Revenue" not in labels and "Total income" in labels
    ebitda = next(m for m in _metrics(page) if m["metric"] == "ebitda")
    assert ebitda["value"] == "n/a"


def test_transcripts_and_honest_guidance_state(page):
    go(page, "#/company/POLYCAB")
    page.wait_for_selector("[data-testid=transcripts]")
    t = page.inner_text("[data-testid=transcripts]")
    assert "4 of 4" in t and "Q2 FY27" in t
    assert "Guidance analysis not yet available" in page.inner_text("[data-testid=guidance]")
    go(page, "#/company/ITC")
    page.wait_for_selector("[data-testid=transcripts]")
    assert "Not retrieved" in page.inner_text("[data-testid=transcripts]")
    assert "Guidance analysis not yet available" in page.inner_text("[data-testid=guidance]")


def test_unsupported_ticker_messages(page):
    go(page, "#/research")
    page.wait_for_selector("[data-testid=search]")
    no_horizontal_scroll(page)
    page.fill("[data-testid=search]", "ZOMATOX")
    page.wait_for_selector("[data-testid=unsupported]")
    assert "not in this snapshot" in page.inner_text("[data-testid=unsupported]")
    go(page, "#/company/ZOMATOX")
    page.wait_for_selector("[data-testid=unsupported-company]")
    assert "not in the committed snapshot" in page.inner_text("[data-testid=unsupported-company]")


def test_search_opens_company(page):
    go(page, "#/research")
    page.fill("[data-testid=search]", "polycab")
    page.press("[data-testid=search]", "Enter")
    page.wait_for_selector("[data-testid=company]")
    assert "POLYCAB" in page.inner_text("[data-testid=company]")


# ---------------------------------------------------------------- settings

def test_settings_persist_and_drive_the_request(page):
    go(page, "#/settings")
    page.wait_for_selector("[data-testid=settings]")
    no_horizontal_scroll(page)
    page.fill("#move_pct", "2.5")
    page.fill("#volume_x", "1.5")
    page.fill("#lookback", "10")
    with page.expect_request(lambda r: "/api/v1/signals" in r.url) as req:
        page.click("[data-testid=save]")
    assert "move_pct=2.5" in req.value.url and "volume_x=1.5" in req.value.url and "lookback=10" in req.value.url
    page.reload()
    go(page, "#/settings")
    page.wait_for_selector("[data-testid=settings]")
    assert page.input_value("#move_pct") == "2.5" and page.input_value("#lookback") == "10"


# ---------------------------------------------------------------- layout

def test_touch_targets_and_layout_at_360(page):
    go(page, "#/signals")
    page.wait_for_selector("[data-testid=summary]")
    small = page.evaluate("""() => [...document.querySelectorAll('.tabs a, .icon-btn, .seg button, select, .btn')]
        .filter(e => e.offsetParent !== null)
        .map(e => [e.className || e.tagName, e.getBoundingClientRect()])
        .filter(([, r]) => r.height < 44 || r.width < 44)
        .map(([n, r]) => `${n} ${Math.round(r.width)}x${Math.round(r.height)}`)""")
    assert small == []
    nav = page.locator(".tabs a").first.bounding_box()
    assert nav["height"] >= 44
    for route, sel in [("#/research", "[data-testid=search]"), ("#/company/HDFCBANK", "[data-testid=results-card]"),
                       ("#/company/BAJFINANCE", "[data-testid=results-card]"), ("#/settings", "[data-testid=settings]")]:
        go(page, route)
        page.wait_for_selector(sel)
        no_horizontal_scroll(page)
