"""Vertical slice: results ingest -> SQLite -> results card. Symbol-agnostic: nothing here names a ticker."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from finn import http, metrics, store
from finn.adapters import nse_filings, nse_results, prices
from finn.classify import classify
from finn.models import ResultFilingRef, Unavailable, to_jsonable


def _prov(f: http.Fetched) -> str:
    if not f.ok:
        return "unavailable"
    return "cached" if f.from_cache else "live"


def pick_periods(refs: list[ResultFilingRef]) -> tuple[Optional[str], list[ResultFilingRef]]:
    """Latest quarter + its QoQ and YoY comparators on ONE basis (consolidated preferred)."""
    for basis in ("consolidated", "standalone"):
        same = {r.period_end: r for r in refs if r.basis == basis and r.xbrl_url}
        if not same:
            continue
        latest = max(same)
        wanted = [latest, metrics.expected_prior(latest, "qoq"), metrics.expected_prior(latest, "yoy")]
        return basis, [same[d] for d in wanted if d in same]
    return None, []


def ingest_results(con, symbol: str, *, offline: bool = False) -> list[Unavailable]:
    """Every problem, including an unreachable listing, is stored so the card can say why data is missing."""
    problems = _ingest_results(con, symbol, offline=offline)
    for p in problems:
        store.put_unavailable(con, symbol, p)
    con.commit()
    return problems


def _ingest_results(con, symbol: str, *, offline: bool) -> list[Unavailable]:
    problems: list[Unavailable] = []
    url = nse_results.LIST_URL.format(symbol=symbol)
    f = http.fetch(url, offline=offline, max_age_s=6 * 3600)
    if not f.ok:
        problems.append(Unavailable("nse_results_listing", f.reason or "unknown", url, f.status))
        return problems
    try:
        refs = nse_results.parse_listing(f.body, symbol)
    except (ValueError, KeyError) as e:
        problems.append(Unavailable("nse_results_listing", f"unparseable: {e}", url))
        return problems
    basis, chosen = pick_periods(refs)
    if not chosen:
        problems.append(Unavailable("nse_results_listing", "no XBRL results listed for this symbol", url))
        return problems
    for ref in chosen:
        x = http.fetch(ref.xbrl_url, offline=offline)       # filings are immutable: any cached copy is valid
        if not x.ok:
            problems.append(Unavailable("nse_xbrl", x.reason or "unknown", ref.xbrl_url, x.status))
            continue
        try:
            parsed = nse_results.parse_instance(x.body)
            ctx = nse_results.quarter_context(parsed, ref.period_end)
        except Exception as e:                                # malformed XML is a data problem, not a crash
            problems.append(Unavailable("nse_xbrl", f"unparseable XBRL: {type(e).__name__}: {e}", ref.xbrl_url))
            continue
        if ctx is None:
            problems.append(Unavailable("nse_xbrl", f"no quarter context ending {ref.period_end}", ref.xbrl_url))
            continue
        if ref.taxonomy == "other":
            problems.append(Unavailable("nse_xbrl", "unsupported XBRL taxonomy (not Ind-AS or banking)", ref.xbrl_url))
            continue
        rounding = parsed["facts"].get(("LevelOfRounding", ctx)) or parsed["facts"].get(("LevelOfRoundingUsedInFinancialStatements", ctx))
        src = nse_results.source_for(ref, x.fetched_at, x.sha256, _prov(x))
        obs = metrics.extract(parsed, ctx, ref.taxonomy, symbol=symbol, basis=ref.basis, source=src, rounding=rounding)
        store.put_observations(con, list(obs.values()), ref.taxonomy)
        store.put_integrity(con, symbol, ref.period_end, ref.basis, metrics.integrity_checks(obs, ref.taxonomy))
    return problems


def results_card(con, symbol: str) -> dict:
    """What a Push results card / Pull financial snapshot consumes. Every number carries its source."""
    rows = store.get_observations(con, symbol)
    if not rows:
        return {"symbol": symbol, "status": "unavailable", "reason": "no results ingested"}
    latest_end = max(r["period_end"] for r in rows)
    basis = next(r["basis"] for r in rows if r["period_end"] == latest_end)
    taxonomy = next(r["taxonomy"] for r in rows if r["period_end"] == latest_end)
    by = {(r["metric"], r["period_end"]): store.row_to_observation(r) for r in rows if r["basis"] == basis}
    cur_end = date.fromisoformat(latest_end)
    q_end, y_end = metrics.expected_prior(cur_end, "qoq"), metrics.expected_prior(cur_end, "yoy")

    out_rows = []
    for m in metrics.HEADLINE[taxonomy] + (["ebitda"] if taxonomy == "banking" else []):
        cur = by.get((m, latest_end))
        if cur is None:
            continue
        if cur.status == "not_applicable":      # e.g. bank EBITDA: no comparison, and not "missing" either
            qoq = yoy = metrics.Change(None, "not_applicable", None, None, cur.note)
        else:
            qoq = metrics.compare(cur, by.get((m, q_end.isoformat())), "qoq")
            yoy = metrics.compare(cur, by.get((m, y_end.isoformat())), "yoy")
        out_rows.append({
            "metric": m, "label": metrics.LABELS.get(m, m), "status": cur.status,
            "value_cr": metrics.to_crore(cur.value), "formula": cur.formula, "note": cur.note,
            "qoq": {"pct": qoq.pct, "status": qoq.status, "prev_cr": metrics.to_crore(qoq.previous), "note": qoq.note},
            "yoy": {"pct": yoy.pct, "status": yoy.status, "prev_cr": metrics.to_crore(yoy.previous), "note": yoy.note},
            "source": {"url": cur.source.url, "location": cur.source.location, "retrieved_at": cur.source.retrieved_at,
                       "provenance": cur.source.provenance, "published_at": cur.source.published_at},
        })
    rev_key = "revenue" if taxonomy == "indas" else None
    margin = None
    if rev_key and by.get(("ebitda", latest_end)) and by.get((rev_key, latest_end)):
        margin = metrics.margin(by[("ebitda", latest_end)].value, by[(rev_key, latest_end)].value)
    exc = by.get(("exceptional", latest_end))
    chk = con.execute("SELECT checks FROM integrity WHERE symbol=? AND period_end=? AND basis=?",
                      (symbol, latest_end, basis)).fetchone()
    unav = [dict(r) for r in con.execute("SELECT source, reason, url, http_status, at FROM unavailable WHERE symbol=? "
                                         "ORDER BY id DESC LIMIT 5", (symbol,))]
    return to_jsonable({
        "symbol": symbol, "status": "ok", "period_end": cur_end, "basis": basis, "taxonomy": taxonomy,
        "rows": out_rows, "ebitda_margin_pct": margin,
        # NSE's latest XBRL carries no comparative columns, so prior quarters come from their own original filings.
        # Observed: BAJFINANCE Sep-25 revenue 20,178.90 cr as filed vs 19,990.42 cr regrouped in the Sep-26 PDF.
        "comparison_basis": "QoQ and YoY use each prior quarter as originally filed; later regrouping or restatement "
                            "shown in the current results PDF is not reflected",
        "exceptional_cr": metrics.to_crore(exc.value) if exc and exc.value else None,
        "integrity": json.loads(chk["checks"]) if chk else [], "unavailable": unav,
    })


def ingest_filings(con, symbol: str, *, days: int = 7, offline: bool = False) -> list[Unavailable]:
    end = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
    url = nse_filings.ANN_URL.format(symbol=symbol, start=end - timedelta(days=days), end=end)
    f = http.fetch(url, offline=offline, max_age_s=15 * 60)
    if not f.ok:
        u = Unavailable("nse_announcements", f.reason or "unknown", url, f.status)
        store.put_unavailable(con, symbol, u)
        con.commit()
        return [u]
    for fl in nse_filings.parse_announcements(f.body, fetched_at=f.fetched_at, url=url, sha=f.sha256, provenance=_prov(f)):
        c = classify(fl)
        store.put_filing(con, fl, c.category, c.method)
    con.commit()
    return []


def price_signals(symbol: str, *, offline: bool = False, move_pct: float = 5.0, volume_x: float = 2.0) -> dict:
    ysym = prices.yahoo_symbol(symbol)
    url = prices.CHART_URL.format(symbol=ysym, range="6mo")
    f = http.fetch(url, offline=offline, max_age_s=3600)
    if not f.ok:
        return {"symbol": symbol, "status": "unavailable", "reason": f.reason}
    try:
        bars = prices.parse_chart(f.body, fetched_at=f.fetched_at, url=url, sha=f.sha256, provenance=_prov(f))
    except prices.PriceParseError as e:
        return {"symbol": symbol, "status": "unavailable", "reason": str(e)}
    sig = prices.eod_signals(bars)
    return to_jsonable({"symbol": symbol, "status": "ok", "signal": sig,
                        "alerts": prices.check_alerts(sig, move_pct=move_pct, volume_x=volume_x),
                        "retrieved_at": f.fetched_at, "provenance": _prov(f)})
