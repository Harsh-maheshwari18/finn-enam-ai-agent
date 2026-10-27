"""SQLite persistence. One file; provenance stored next to every value."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

from finn import tz
from finn.models import Filing, Observation, PriceBar, SourceRef, Unavailable

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY, doc_type TEXT NOT NULL, url TEXT, content_hash TEXT, retrieved_at TEXT NOT NULL,
  provenance TEXT NOT NULL, title TEXT, published_at TEXT,
  UNIQUE(url, content_hash)
);
CREATE TABLE IF NOT EXISTS observations (
  symbol TEXT NOT NULL, metric TEXT NOT NULL, period_start TEXT NOT NULL, period_end TEXT NOT NULL,
  basis TEXT NOT NULL, taxonomy TEXT NOT NULL, value TEXT, status TEXT NOT NULL, source_id INTEGER NOT NULL REFERENCES sources(id),
  location TEXT, reported_tag TEXT, reported_rounding TEXT, formula TEXT, note TEXT,
  PRIMARY KEY (symbol, metric, period_start, period_end, basis)
);
CREATE TABLE IF NOT EXISTS filings (
  seq_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, isin TEXT, company TEXT, nse_desc TEXT, headline TEXT,
  broadcast_at TEXT NOT NULL, attachment_url TEXT, category TEXT, category_method TEXT, source_id INTEGER REFERENCES sources(id)
);
CREATE TABLE IF NOT EXISTS integrity (
  symbol TEXT, period_end TEXT, basis TEXT, checks TEXT, PRIMARY KEY (symbol, period_end, basis)
);
CREATE TABLE IF NOT EXISTS unavailable (
  id INTEGER PRIMARY KEY, symbol TEXT, source TEXT, reason TEXT, url TEXT, http_status INTEGER, at TEXT
);
CREATE TABLE IF NOT EXISTS price_bars (
  symbol TEXT NOT NULL, day TEXT NOT NULL, open REAL, high REAL, low REAL, close REAL NOT NULL, volume INTEGER,
  volume_suspect INTEGER NOT NULL, source_id INTEGER NOT NULL REFERENCES sources(id), PRIMARY KEY (symbol, day)
);
"""


def connect(path: str | Path = "data/finn.db") -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def _iso(v):
    return v.isoformat() if isinstance(v, (date, datetime)) else v


def put_source(con, s: SourceRef) -> int:
    con.execute("INSERT OR IGNORE INTO sources(doc_type,url,content_hash,retrieved_at,provenance,title,published_at) "
                "VALUES (?,?,?,?,?,?,?)", (s.doc_type, s.url, s.content_hash, _iso(s.retrieved_at), s.provenance,
                                            s.title, _iso(s.published_at)))
    row = con.execute("SELECT id FROM sources WHERE url IS ? AND content_hash IS ?", (s.url, s.content_hash)).fetchone()
    return row["id"]


def put_observations(con, obs: list[Observation], taxonomy: str) -> None:
    for o in obs:
        sid = put_source(con, o.source)
        con.execute("INSERT OR REPLACE INTO observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            o.symbol, o.metric, o.period_start.isoformat(), o.period_end.isoformat(), o.basis, taxonomy,
            str(o.value) if o.value is not None else None, o.status, sid, o.source.location, o.reported_tag,
            o.reported_rounding, o.formula, o.note))


def put_integrity(con, symbol, period_end: date, basis, checks: list[dict]) -> None:
    con.execute("INSERT OR REPLACE INTO integrity VALUES (?,?,?,?)", (symbol, period_end.isoformat(), basis, json.dumps(checks)))


def put_filing(con, f: Filing, category: Optional[str], method: str) -> None:
    sid = put_source(con, f.source)
    con.execute("INSERT OR REPLACE INTO filings VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
        f.seq_id, f.symbol, f.isin, f.company, f.nse_desc, f.headline, f.broadcast_at.isoformat(), f.attachment_url,
        category, method, sid))


def put_price_bars(con, symbol: str, bars: list[PriceBar]) -> None:
    for b in bars:
        sid = put_source(con, b.source)
        con.execute("INSERT OR REPLACE INTO price_bars VALUES (?,?,?,?,?,?,?,?,?)", (
            symbol, b.day.isoformat(), b.open, b.high, b.low, b.close, b.volume, int(b.volume_suspect), sid))


def get_price_bars(con, symbol: str) -> list[PriceBar]:
    rows = con.execute("SELECT p.*, s.url, s.retrieved_at, s.content_hash, s.provenance, s.title FROM price_bars p "
                       "JOIN sources s ON s.id = p.source_id WHERE p.symbol = ? ORDER BY p.day", (symbol,)).fetchall()
    return [PriceBar(symbol=symbol, day=date.fromisoformat(r["day"]), open=r["open"], high=r["high"], low=r["low"],
                     close=r["close"], volume=r["volume"], provisional=False, volume_suspect=bool(r["volume_suspect"]),
                     source=SourceRef("price_feed", r["url"], datetime.fromisoformat(r["retrieved_at"]), r["content_hash"],
                                      r["provenance"], r["title"])) for r in rows]


def put_unavailable(con, symbol: str, u: Unavailable) -> None:
    con.execute("INSERT INTO unavailable(symbol,source,reason,url,http_status,at) VALUES (?,?,?,?,?,?)",
                (symbol, u.source, u.reason, u.url, u.http_status, datetime.now(timezone.utc).isoformat(timespec="seconds")))


def get_observations(con, symbol: str) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT o.*, s.url AS source_url, s.retrieved_at, s.provenance, s.content_hash, s.title AS source_title, "
        "s.published_at FROM observations o JOIN sources s ON s.id = o.source_id WHERE o.symbol = ? "
        "ORDER BY o.period_end DESC", (symbol,)).fetchall()


def row_to_observation(r) -> Observation:
    src = SourceRef(doc_type="xbrl_result", url=r["source_url"], retrieved_at=datetime.fromisoformat(r["retrieved_at"]),
                    content_hash=r["content_hash"], provenance=r["provenance"], title=r["source_title"],
                    published_at=tz.as_ist(datetime.fromisoformat(r["published_at"])) if r["published_at"] else None,   # NSE time; older DBs stored it naive
                    location=r["location"])
    return Observation(symbol=r["symbol"], metric=r["metric"], value=Decimal(r["value"]) if r["value"] is not None else None,
                       period_start=date.fromisoformat(r["period_start"]), period_end=date.fromisoformat(r["period_end"]),
                       basis=r["basis"], status=r["status"], source=src, reported_tag=r["reported_tag"],
                       reported_rounding=r["reported_rounding"], formula=r["formula"], note=r["note"])
