"""EOD prices from Yahoo's chart endpoint (the JSON yfinance itself uses; called directly to
avoid pulling pandas into the deploy).

Observed 2026-10-27: during market hours the last bar is the *live session* (TCS.NS bar for
27-Oct stamped 11:41 IST). It must not be treated as an EOD close. Zero-volume bars appear on
some non-trading dates (e.g. 2026-01-15) and are excluded from volume averages.
"""
from __future__ import annotations

import json
from datetime import datetime, time, timedelta, timezone
from typing import Optional

from finn.models import PriceBar, SourceRef

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={range}&interval=1d"
IST = timezone(timedelta(hours=5, minutes=30))
EOD_SETTLED = time(16, 0)   # NSE closes 15:30 IST; treat bars as final from 16:00 IST


class PriceParseError(ValueError):
    pass


def yahoo_symbol(nse_symbol: str, exchange: str = "NS") -> str:
    return f"{nse_symbol.upper()}.{exchange}"


def parse_chart(body: bytes, *, fetched_at: datetime, url: str, sha: Optional[str], provenance: str) -> list[PriceBar]:
    try:
        doc = json.loads(body)
    except json.JSONDecodeError as e:
        raise PriceParseError(f"not JSON: {e}") from None
    chart = doc.get("chart") or {}
    if chart.get("error"):
        raise PriceParseError(f"source error: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise PriceParseError("empty result")
    r = results[0]
    meta = r.get("meta", {})
    symbol = meta.get("symbol")
    if meta.get("currency") not in (None, "INR"):
        raise PriceParseError(f"unexpected currency {meta.get('currency')}")
    ts = r.get("timestamp") or []
    q = (r.get("indicators", {}).get("quote") or [{}])[0]
    cols = {k: q.get(k) or [None] * len(ts) for k in ("open", "high", "low", "close", "volume")}
    if any(len(v) != len(ts) for v in cols.values()):
        raise PriceParseError("column length mismatch")

    src = SourceRef(doc_type="price_feed", url=url, retrieved_at=fetched_at, content_hash=sha, provenance=provenance,
                    title=f"Yahoo chart {symbol}")
    fetched_ist = fetched_at.astimezone(IST)
    by_day: dict = {}
    for i, t in enumerate(ts):
        if not isinstance(t, (int, float)):
            continue
        day = datetime.fromtimestamp(t, IST).date()
        close = cols["close"][i]
        if not isinstance(close, (int, float)) or close <= 0:
            continue                          # no trade / null bar: skipped, not zero-filled
        vol = cols["volume"][i]
        vol = int(vol) if isinstance(vol, (int, float)) else None
        provisional = day == fetched_ist.date() and fetched_ist.time() < EOD_SETTLED
        by_day[day] = PriceBar(symbol=symbol, day=day, open=cols["open"][i], high=cols["high"][i], low=cols["low"][i],
                               close=float(close), volume=vol, provisional=provisional,
                               volume_suspect=(vol == 0), source=src)   # later duplicate of a day wins
    return [by_day[d] for d in sorted(by_day)]


def eod_signals(bars: list[PriceBar], lookback: int = 20) -> Optional[dict]:
    """Latest *final* bar's day move and volume ratio vs. the prior `lookback` usable sessions."""
    final = [b for b in bars if not b.provisional]
    if len(final) < 2:
        return None
    last, prev = final[-1], final[-2]
    hist = [b.volume for b in final[:-1] if b.volume and not b.volume_suspect][-lookback:]
    avg = sum(hist) / len(hist) if len(hist) >= max(5, lookback // 2) else None
    return {
        "symbol": last.symbol, "day": last.day, "close": last.close, "prev_close": prev.close,
        "move_pct": round((last.close - prev.close) / prev.close * 100, 2),
        "volume": last.volume, "avg_volume": round(avg) if avg else None, "lookback_used": len(hist),
        "volume_ratio": round(last.volume / avg, 2) if avg and last.volume is not None and not last.volume_suspect else None,
        "provisional_bar_excluded": len(final) != len(bars),
    }


def session_stats(bars: list[PriceBar], lookback: int = 20) -> list[dict]:
    """Per completed session: close-to-close move and volume vs. the average of the prior `lookback` usable sessions.
    Same rules as eod_signals: provisional bars are dropped, zero-volume bars never enter an average, and a ratio
    needs at least max(5, lookback // 2) prior sessions, otherwise it is None (cannot be evaluated, not zero)."""
    final = [b for b in bars if not b.provisional]
    need = max(5, lookback // 2)
    out = []
    for i in range(1, len(final)):
        b, prev = final[i], final[i - 1]
        hist = [x.volume for x in final[:i] if x.volume and not x.volume_suspect][-lookback:]
        avg = sum(hist) / len(hist) if len(hist) >= need else None
        out.append({
            "day": b.day, "close": b.close, "prev_close": prev.close, "prev_day": prev.day,
            "move_pct": round((b.close - prev.close) / prev.close * 100, 2),
            "volume": b.volume, "avg_volume": round(avg) if avg else None, "lookback_used": len(hist),
            "lookback_needed": need,
            "volume_ratio": round(b.volume / avg, 2) if avg and b.volume is not None and not b.volume_suspect else None,
        })
    return out


def check_alerts(sig: Optional[dict], *, move_pct: float = 5.0, volume_x: float = 2.0) -> list[str]:
    """Threshold rules; >= is a breach. Thresholds are user settings, defaults from the brief."""
    if not sig:
        return []
    out = []
    if abs(sig["move_pct"]) >= move_pct:
        out.append("price_move")
    if sig["volume_ratio"] is not None and sig["volume_ratio"] >= volume_x:
        out.append("volume_spike")
    return out
