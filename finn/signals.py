"""Signal Inbox: deterministic, explainable ranking of what changed in the portfolio (docs/signal-rules.md).

Inputs are only what the committed snapshot holds: NSE announcements (verbatim subject and headline, classified by
finn.classify), completed EOD price bars, and the verified results observations. Nothing is fetched, nothing is
summarised by a model. Every signal carries the rule points that produced its score, so the ranking can be audited.

Priority is an attention ranking, not a forecast: it says how much a filing type or a threshold breach usually
deserves a look, never how likely the share price is to move.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from finn import service, store, tz
from finn.adapters import prices

WINDOWS = {"24h": 24, "3d": 72, "7d": 168, "30d": 720}     # 30d = everything the snapshot stores
DEFAULTS = {"window": "24h", "move_pct": 5.0, "volume_x": 2.0, "lookback": 20}
LIMITS = {"move_pct": (0.5, 50.0), "volume_x": (1.1, 20.0), "lookback": (5, 60)}
SESSION_CLOSE = time(15, 30)           # NSE cash market close, IST
NOVELTY_DAYS = 30

# category -> (tier, base points, plain-language reason). Tiers: material and notable are ranked; routine is folded.
RULES: dict[Optional[str], tuple[str, int, str]] = {
    "results": ("material", 80, "Quarterly results change the numbers the thesis rests on"),
    "M&A": ("material", 80, "Acquisitions, mergers and stake changes alter what the company owns"),
    "management_change": ("material", 75, "A change in directors or key managerial personnel"),
    "litigation": ("material", 70, "Litigation or regulatory action can create liabilities"),
    "fund_raise": ("material", 70, "Fund raising or buybacks change the capital base"),
    "pledging": ("material", 65, "Promoter pledges or encumbrances can signal financing stress"),
    "credit_rating": ("notable", 55, "A credit rating action on the company's debt"),
    "bonus_split": ("notable", 55, "Bonus issue or split changes the share count"),
    "capex": ("notable", 50, "Capacity or capital-expenditure announcement"),
    "dividend": ("notable", 45, "Dividend or record date"),
    "earnings_call": ("notable", 40, "Earnings-call transcript or recording: management commentary on record"),
    "press_release": ("notable", 40, "Company press release, order or partnership"),
    "insider_trading": ("routine", 20, "Insider / SAST disclosure; usually routine for large caps"),
    "investor_meetings": ("routine", 15, "Schedule of analyst or investor meetings"),
    "agm_egm": ("routine", 15, "Shareholder-meeting procedure"),
    "postal_ballot": ("routine", 15, "Postal-ballot procedure"),
    "unclassified": ("routine", 10, "Compliance filing (newspaper ad, ESOP allotment, trading window, certificates)"),
    None: ("needs_review", 35, "NSE's label and the headline did not match any rule; FINN does not guess a category"),
}
LABELS = {"results": "Results", "M&A": "M&A", "management_change": "Management change", "litigation": "Litigation",
          "fund_raise": "Fund raise", "pledging": "Pledge", "credit_rating": "Credit rating", "bonus_split": "Bonus / split",
          "capex": "Capex", "dividend": "Dividend", "earnings_call": "Earnings call", "press_release": "Press release",
          "insider_trading": "Insider / SAST", "investor_meetings": "Investor meetings", "agm_egm": "AGM / EGM",
          "postal_ballot": "Postal ballot", "unclassified": "Compliance", None: "Needs review",
          "price_move": "Price move", "volume_spike": "Unusual volume"}
PRICE_BASE = {"price_move": 65, "volume_spike": 60}
WATCH_POINTS = 15
NOVELTY_POINTS = 10


def priority(score: int) -> str:
    return "high" if score >= 70 else "medium" if score >= 40 else "low"


def parse_settings(q: dict[str, str]) -> dict:
    """Validated user settings. Raises ValueError with a message the API returns as 400."""
    s = dict(DEFAULTS)
    if q.get("window"):
        if q["window"] not in WINDOWS:
            raise ValueError(f"window must be one of {', '.join(WINDOWS)}")
        s["window"] = q["window"]
    for k, (lo, hi) in LIMITS.items():
        if q.get(k):
            try:
                v = float(q[k])
            except ValueError:
                raise ValueError(f"{k} must be a number") from None
            if not lo <= v <= hi:
                raise ValueError(f"{k} must be between {lo:g} and {hi:g}")
            s[k] = int(v) if k == "lookback" else v
    known = {c for c in RULES if c} | {"needs_review", "price_move", "volume_spike"}
    for k in ("watch", "mute"):
        vals = [v for v in (q.get(k) or "").split(",") if v]
        bad = [v for v in vals if v not in known]
        if bad:
            raise ValueError(f"unknown category in {k}: {', '.join(bad)}")
        s[k] = vals
    s["symbols"] = [v.strip().upper() for v in (q.get("symbols") or "").split(",") if v.strip()]
    return s


def _meta(con) -> dict:
    return dict(con.execute("SELECT key, value FROM snapshot_meta").fetchall())


def anchor(con) -> Optional[datetime]:
    """The window ends when the snapshot's announcements were retrieved, not at the viewer's clock: a committed
    snapshot does not learn about filings made after it was built, so 'last 24h' must mean the 24h it can see."""
    v = _meta(con).get("announcements_retrieved_at")
    return datetime.fromisoformat(v) if v else None


def _filing_signal(r, cat_key: Optional[str], novelty_from: datetime, history: list[datetime], settings: dict) -> dict:
    tier, base, why = RULES.get(cat_key, RULES[None])
    parts = [{"points": base, "rule": f"category {LABELS.get(cat_key, cat_key)}", "why": why}]
    when = datetime.fromisoformat(r["broadcast_at"])
    prior = [t for t in history if t < when]
    if tier in ("material", "notable"):
        if not prior and (when - novelty_from).days >= 7:
            parts.append({"points": NOVELTY_POINTS, "rule": "novelty",
                          "why": f"first {LABELS.get(cat_key, 'such')} filing for this company in the "
                                 f"{(when - novelty_from).days} days of stored announcements"})
    if (cat_key or "needs_review") in settings.get("watch", []):
        parts.append({"points": WATCH_POINTS, "rule": "your watch list", "why": "you asked to watch this category"})
    score = sum(p["points"] for p in parts)
    unknowns = ["FINN has not read the attached document; the title is NSE's subject and the company's own headline."]
    if cat_key is None:
        unknowns.insert(0, "Category unresolved: the NSE label is vague and no headline rule matched.")
    return {
        "id": f"ann-{r['seq_id']}", "kind": "announcement", "symbol": r["symbol"], "company": r["company"],
        "category": cat_key or "needs_review", "category_label": LABELS.get(cat_key, cat_key), "tier": tier,
        "score": score, "priority": priority(score), "score_parts": parts, "routine": tier == "routine",
        "title": r["headline"] or r["nse_desc"], "nse_subject": r["nse_desc"],
        "what_happened": f"{r['company'] or r['symbol']} filed an announcement with NSE under “{r['nse_desc']}”.",
        "published_at": tz.as_ist(when).isoformat(), "event_time": tz.as_ist(when).isoformat(),
        "classification": {"method": r["category_method"], "category": cat_key},
        "source": {"doc_type": "announcement", "document_url": r["attachment_url"], "listing_url": r["source_url"],
                   "retrieved_at": r["retrieved_at"], "provenance": r["provenance"], "content_hash": r["content_hash"]},
        "unknowns": unknowns,
    }


def _results_numbers(con, sym: str, filed_on: date) -> Optional[dict]:
    """Attach the verified results card when its XBRL was published the same IST day as the filing."""
    card = service.results_card(con, sym)
    if card.get("status") != "ok" or not card["rows"]:
        return None
    pub = card["rows"][0]["source"]["published_at"]
    same_day = bool(pub) and datetime.fromisoformat(pub).astimezone(tz.IST).date() == filed_on
    return {"matches_filing": same_day, "period_end": card["period_end"], "basis": card["basis"],
            "taxonomy": card["taxonomy"], "xbrl_published_at": pub, "xbrl_url": card["rows"][0]["source"]["url"],
            "rows": [{k: row[k] for k in ("metric", "label", "status", "value_cr", "qoq", "yoy", "formula", "note")}
                     for row in card["rows"]] if same_day else [],
            "comparison_basis": card["comparison_basis"]}


def _price_signals(con, sym: str, company: str, start: datetime, end: datetime, settings: dict) -> tuple[list, dict]:
    bars = store.get_price_bars(con, sym)
    cov = {"symbol": sym, "sessions": len(bars), "last_session": bars[-1].day.isoformat() if bars else None,
           "volume_evaluable": None}
    if not bars:
        cov["reason"] = "no completed EOD bars in the snapshot"
        return [], cov
    out = []
    for st in prices.session_stats(bars, lookback=int(settings["lookback"])):
        closed = datetime.combine(st["day"], SESSION_CLOSE, tz.IST)
        if not start < closed <= end:
            continue
        cov["volume_evaluable"] = st["volume_ratio"] is not None
        if st["volume_ratio"] is None:
            cov["reason"] = (f"volume ratio needs {st['lookback_needed']} prior sessions with volume; "
                             f"{st['lookback_used']} available")
        src = bars[-1].source
        common = {"symbol": sym, "company": company, "kind": "price", "tier": "material", "routine": False,
                  "session_day": st["day"].isoformat(), "event_time": closed.isoformat(), "published_at": None,
                  "stats": {k: (v.isoformat() if isinstance(v, date) else v) for k, v in st.items()},
                  "source": {"doc_type": "price_feed", "document_url": None, "listing_url": src.url,
                             "retrieved_at": src.retrieved_at.isoformat(), "provenance": src.provenance,
                             "content_hash": src.content_hash},
                  "unknowns": ["Yahoo Finance EOD data; not reconciled with the NSE bhavcopy.",
                               "FINN does not know why the stock moved; check the same day's announcements."]}
        checks = [("price_move", abs(st["move_pct"]) >= settings["move_pct"], abs(st["move_pct"]) - settings["move_pct"], 2, 20,
                   f"Closed {st['move_pct']:+.2f}% vs the previous session ({st['prev_close']:,.2f} → {st['close']:,.2f})",
                   f"|move| {abs(st['move_pct']):.2f}% ≥ your threshold {settings['move_pct']:g}%",
                   f"({st['close']:,.2f} − {st['prev_close']:,.2f}) / {st['prev_close']:,.2f} = {st['move_pct']:+.2f}%")]
        if st["volume_ratio"] is not None:
            checks.append(("volume_spike", st["volume_ratio"] >= settings["volume_x"], st["volume_ratio"] - settings["volume_x"], 5, 15,
                           f"Volume {st['volume']:,} was {st['volume_ratio']:.2f}× its {st['lookback_used']}-session average",
                           f"ratio {st['volume_ratio']:.2f}× ≥ your threshold {settings['volume_x']:g}×",
                           f"{st['volume']:,} / {st['avg_volume']:,} = {st['volume_ratio']:.2f}×"))
        for kind, hit, excess, per, cap, what, rule, calc in checks:
            if not hit:
                continue
            bonus = min(cap, int(excess * per))
            parts = [{"points": PRICE_BASE[kind], "rule": LABELS[kind], "why": rule}]
            if bonus:
                parts.append({"points": bonus, "rule": "magnitude", "why": f"{per} points per unit beyond the threshold, capped at {cap}"})
            if kind in settings.get("watch", []):
                parts.append({"points": WATCH_POINTS, "rule": "your watch list", "why": "you asked to watch this category"})
            score = sum(p["points"] for p in parts)
            out.append({**common, "id": f"{kind}-{sym}-{st['day'].isoformat()}", "category": kind,
                        "category_label": LABELS[kind], "score": score, "priority": priority(score), "score_parts": parts,
                        "title": what, "what_happened": what, "calculation": calc})
    return out, cov


def inbox(con, settings: dict) -> dict:
    meta = _meta(con)
    end = anchor(con)
    portfolio = json.loads(meta.get("portfolio") or "[]")
    universe = json.loads(meta.get("symbols") or "[]")
    syms = settings.get("symbols") or portfolio
    unknown = [s for s in syms if s not in universe]
    if unknown:
        raise ValueError(f"not in the snapshot: {', '.join(unknown)}")
    if end is None:
        return {"status": "unavailable", "reason": "this snapshot holds no announcements", "signals": [], "folded": []}
    hours = WINDOWS[settings["window"]]
    start = end - timedelta(hours=hours)
    names = dict(con.execute("SELECT symbol, name FROM companies"))
    rows = con.execute(
        "SELECT f.*, s.url AS source_url, s.retrieved_at, s.provenance, s.content_hash FROM filings f "
        "JOIN sources s ON s.id = f.source_id WHERE f.symbol IN (%s) ORDER BY f.broadcast_at" % ",".join("?" * len(syms)),
        syms).fetchall()
    novelty_from = {s: end - timedelta(days=NOVELTY_DAYS) for s in syms}
    history: dict[tuple, list[datetime]] = {}
    for r in rows:
        history.setdefault((r["symbol"], r["category"]), []).append(datetime.fromisoformat(r["broadcast_at"]))
        novelty_from[r["symbol"]] = min(novelty_from[r["symbol"]], datetime.fromisoformat(r["broadcast_at"]))

    signals, folded, muted = [], [], 0
    for r in rows:
        when = datetime.fromisoformat(r["broadcast_at"])
        if not start < when <= end:
            continue
        sig = _filing_signal(r, r["category"], novelty_from[r["symbol"]], history[(r["symbol"], r["category"])], settings)
        if sig["category"] in settings.get("mute", []):
            muted += 1
            continue
        if sig["category"] == "results":
            sig["numbers"] = _results_numbers(con, r["symbol"], when.astimezone(tz.IST).date())
            if sig["numbers"] and not sig["numbers"]["matches_filing"]:
                sig["unknowns"].append(f"The verified results card in this snapshot is for the period ending "
                                       f"{sig['numbers']['period_end']}; this filing's figures were not ingested.")
        (folded if sig["routine"] else signals).append(sig)

    coverage = []
    for s in syms:
        ps, cov = _price_signals(con, s, names.get(s) or s, start, end, settings)
        coverage.append(cov)
        for p in ps:
            if p["category"] in settings.get("mute", []):
                muted += 1
            else:
                signals.append(p)

    signals.sort(key=lambda x: (-x["score"], _neg_time(x["event_time"])))      # score, then newest first
    folded.sort(key=lambda x: x["event_time"], reverse=True)
    unav = [dict(r) for r in con.execute("SELECT symbol, source, reason, http_status FROM unavailable "
                                         "WHERE source IN ('nse_announcements','yahoo_chart')")]
    last_sessions = sorted({c["last_session"] for c in coverage if c["last_session"]})
    return {
        "status": "ok",
        "window": {"key": settings["window"], "hours": hours, "start": start.astimezone(tz.IST).isoformat(),
                   "end": end.astimezone(tz.IST).isoformat(),
                   "anchored_to": "announcements retrieval time of the committed snapshot (not the viewer's clock)"},
        "settings": {k: settings[k] for k in ("window", "move_pct", "volume_x", "lookback", "watch", "mute")},
        "symbols": syms, "portfolio": portfolio,
        "counts": {"ranked": len(signals), "folded": len(folded), "muted": muted,
                   "high": sum(s["priority"] == "high" for s in signals)},
        "signals": signals, "folded": folded,
        "freshness": {"announcements_retrieved_at": meta.get("announcements_retrieved_at"),
                      "prices_retrieved_at": meta.get("prices_retrieved_at"),
                      "last_price_session": last_sessions[-1] if last_sessions else None,
                      "snapshot_as_of": meta.get("as_of")},
        "price_coverage": coverage, "unavailable": unav,
        "ranking": "score = category base + novelty + your watch list (+ magnitude for price/volume); "
                   "priority high ≥ 70, medium 40–69, low < 40; routine categories are folded. "
                   "Priority ranks attention, not the probability of a price move.",
    }


def _neg_time(iso: str) -> float:
    return -datetime.fromisoformat(iso).timestamp()


def company_filings(con, sym: str, days: int = 30) -> dict:
    end = anchor(con)
    rows = con.execute("SELECT f.*, s.url AS source_url, s.retrieved_at, s.provenance, s.content_hash FROM filings f "
                       "JOIN sources s ON s.id = f.source_id WHERE f.symbol = ? ORDER BY f.broadcast_at DESC", (sym,)).fetchall()
    out = []
    for r in rows:
        tier, base, _ = RULES.get(r["category"], RULES[None])
        out.append({"id": f"ann-{r['seq_id']}", "category": r["category"] or "needs_review",
                    "category_label": LABELS.get(r["category"], r["category"]), "tier": tier, "routine": tier == "routine",
                    "title": r["headline"] or r["nse_desc"], "nse_subject": r["nse_desc"],
                    "published_at": tz.as_ist(datetime.fromisoformat(r["broadcast_at"])).isoformat(),
                    "document_url": r["attachment_url"], "listing_url": r["source_url"], "retrieved_at": r["retrieved_at"]})
    bars = store.get_price_bars(con, sym)
    last = prices.session_stats(bars[-2:], lookback=1)[-1] if len(bars) >= 2 else None
    unav = [dict(x) for x in con.execute("SELECT source, reason, http_status FROM unavailable WHERE symbol = ? AND "
                                         "source IN ('nse_announcements','yahoo_chart')", (sym,))]
    return {"symbol": sym, "window_days": days, "window_end": end.astimezone(tz.IST).isoformat() if end else None,
            "count": len(out), "filings": out,
            "last_session": {"day": last["day"].isoformat(), "close": last["close"], "move_pct": last["move_pct"],
                             "volume": last["volume"], "retrieved_at": bars[-1].source.retrieved_at.isoformat(),
                             "source_url": bars[-1].source.url} if last else None,
            "unavailable": unav}
