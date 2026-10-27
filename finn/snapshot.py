"""Committed, validated SQLite snapshot that the deployed API serves (ADR-014).

    python -m finn.snapshot build [--offline] [--as-of YYYY-MM-DD]   # ingest -> validate -> snapshot/finn_snapshot.db
    python -m finn.snapshot verify                                    # recompute the content digest against the manifest

Reproducible: the same raw inputs (the cache in FINN_CACHE_DIR, or the immutable NSE filings it was filled from)
give the same content digest. The digest covers every table except snapshot_meta and ignores build time.
Validated: the build refuses to write if any golden-set value disagrees, or if any observation lacks a source.
Only source-linked numbers and transcript metadata go in; no PDF bytes and no transcript text.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Optional

from finn import metrics, service, store, transcript_inventory

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "snapshot" / "finn_snapshot.db"
DEFAULT_UNIVERSE = ROOT / "config" / "universe.json"
DEFAULT_GOLDEN = ROOT / "tests" / "fixtures" / "real" / "golden_set.json"
SCHEMA_VERSION = 1
IST = timezone(timedelta(hours=5, minutes=30))

EXTRA_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshot_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS companies (
  symbol TEXT PRIMARY KEY, groups TEXT NOT NULL, status TEXT NOT NULL, validation TEXT NOT NULL,
  latest_period_end TEXT, basis TEXT, taxonomy TEXT, golden_checked INTEGER NOT NULL, integrity TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transcript_filings (
  symbol TEXT NOT NULL, seq_id TEXT NOT NULL, broadcast_at TEXT, url TEXT, nse_headline TEXT, status TEXT NOT NULL,
  reason TEXT, sha256 TEXT, bytes INTEGER, pages INTEGER, text_chars INTEGER, scanned INTEGER, speaker_turns INTEGER,
  management_named INTEGER, is_earnings_call INTEGER, period_end TEXT, fiscal_quarter TEXT, quarter_phrase TEXT,
  quarter_page INTEGER, quarter_ambiguous INTEGER, quarter_votes TEXT, filing_date_quarter TEXT, date_agrees INTEGER,
  retrieved_at TEXT, provenance TEXT, PRIMARY KEY (symbol, seq_id)
);
CREATE TABLE IF NOT EXISTS transcript_coverage (
  symbol TEXT NOT NULL, period_end TEXT NOT NULL, fiscal_quarter TEXT NOT NULL, status TEXT NOT NULL,
  seq_id TEXT, reason TEXT, duplicates TEXT, PRIMARY KEY (symbol, period_end)
);
"""
DIGEST_TABLES = ["sources", "observations", "integrity", "filings", "unavailable", "companies",
                 "transcript_filings", "transcript_coverage"]


class BuildError(RuntimeError):
    """The snapshot failed validation and was not written."""


def load_universe(path: Path = DEFAULT_UNIVERSE) -> dict:
    return json.loads(Path(path).read_text())


def content_digest(con: sqlite3.Connection) -> str:
    """sha256 over a canonical dump of the data tables (rows sorted, ids excluded where they are surrogate)."""
    h = hashlib.sha256()
    for t in DIGEST_TABLES:
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({t})") if not (t in ("sources", "unavailable") and r[1] == "id")]
        sel = ", ".join(cols)
        if t == "observations":     # source_id is a surrogate key: digest the source it points at instead
            sel = sel.replace("source_id", "(SELECT url || '|' || IFNULL(content_hash,'') FROM sources s WHERE s.id = source_id)")
        h.update(f"#{t}:{','.join(cols)}\n".encode())
        for row in sorted(json.dumps(list(r), default=str) for r in con.execute(f"SELECT {sel} FROM {t}")):
            h.update(row.encode() + b"\n")
    return h.hexdigest()


def _golden_check(con, golden: dict, symbols: set[str]) -> tuple[dict[str, int], list[str]]:
    checked: dict[str, int] = {}
    errors = []
    for g in golden["observations"]:
        if g["symbol"] not in symbols:
            continue
        r = con.execute("SELECT value FROM observations WHERE symbol=? AND metric=? AND period_end=? AND basis='consolidated'",
                        (g["symbol"], g["metric"], g["period_end"])).fetchone()
        if r is None:
            continue                           # that period is not in the snapshot window; nothing to compare
        expected = metrics.to_crore(metrics.from_reported(Decimal(g["reported"]), golden["documents"][g["doc"]]["unit"]))
        got = metrics.to_crore(Decimal(r["value"])) if r["value"] is not None else None
        checked[g["symbol"]] = checked.get(g["symbol"], 0) + 1
        if got != expected:
            errors.append(f"{g['symbol']} {g['period_end']} {g['metric']}: snapshot {got} != signed PDF {expected}")
    return checked, errors


def _provenance_check(con) -> list[str]:
    bad = con.execute("SELECT o.symbol, o.metric, o.period_end FROM observations o LEFT JOIN sources s ON s.id = o.source_id "
                      "WHERE s.url IS NULL OR s.url = '' OR s.content_hash IS NULL OR o.location IS NULL").fetchall()
    return [f"{r[0]} {r[2]} {r[1]}: observation without a full source reference" for r in bad]


def _insert(con, table: str, row: dict) -> None:
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
    vals = []
    for c in cols:
        v = row.get(c)
        vals.append(json.dumps(v) if isinstance(v, (dict, list)) else (int(v) if isinstance(v, bool) else v))
    con.execute(f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)


def build(out: Path = DEFAULT_OUT, *, universe: Optional[dict] = None, symbols: Optional[Iterable[str]] = None,
          transcript_symbols: Optional[Iterable[str]] = None, as_of: Optional[date] = None, offline: bool = False,
          golden_path: Path = DEFAULT_GOLDEN, manifest_path: Optional[Path] = None) -> dict:
    universe = universe if universe is not None else load_universe()
    as_of = as_of or datetime.now(IST).date()
    groups: dict[str, list[str]] = {}
    for g in ("portfolio", "research"):
        for s in universe.get(g, []):
            groups.setdefault(s, []).append(g)
    syms = list(dict.fromkeys(symbols if symbols is not None else groups))
    tsyms = list(transcript_symbols if transcript_symbols is not None else universe.get("transcript_audit", []))

    out = Path(out)
    tmp = out.with_suffix(".building")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.unlink(missing_ok=True)
    con = store.connect(tmp)
    con.executescript(EXTRA_SCHEMA)

    for s in syms:
        service.ingest_results(con, s, offline=offline)
    # Build time must not leak into the digest: an unavailable source is stamped with the snapshot date instead.
    con.execute("UPDATE unavailable SET at = ?", (as_of.isoformat(),))

    for s in tsyms:
        cov = transcript_inventory.coverage(s, as_of, quarters=int(universe.get("transcript_quarters", 4)), offline=offline)
        for a in cov["audits"]:
            _insert(con, "transcript_filings", a)
        for r in cov["quarters"]:
            _insert(con, "transcript_coverage", {"symbol": s, **r})
        for p in cov["search_problems"]:
            con.execute("INSERT INTO unavailable(symbol,source,reason,url,http_status,at) VALUES (?,?,?,?,?,?)",
                        (s, "nse_announcements", p, None, None, as_of.isoformat()))

    golden = json.loads(Path(golden_path).read_text())
    golden_counts, errors = _golden_check(con, golden, set(syms))
    errors += _provenance_check(con)
    if errors:
        con.close()
        tmp.unlink(missing_ok=True)
        raise BuildError("snapshot not written:\n  " + "\n  ".join(errors))

    summary = {}
    for s in syms:
        card = service.results_card(con, s)
        checks = card.get("integrity", [])
        statuses = sorted({c["status"] for c in checks})
        if card["status"] != "ok":
            validation = "unavailable"
        elif "fail" in statuses:
            validation = "integrity_failed"
        elif golden_counts.get(s):
            validation = "golden_verified"
        else:
            validation = "integrity_checked"
        row = {"symbol": s, "groups": groups.get(s, ["adhoc"]), "status": card["status"], "validation": validation,
               "latest_period_end": card.get("period_end"), "basis": card.get("basis"), "taxonomy": card.get("taxonomy"),
               "golden_checked": golden_counts.get(s, 0), "integrity": statuses}
        _insert(con, "companies", row)
        summary[s] = {k: row[k] for k in ("validation", "latest_period_end", "basis", "taxonomy", "golden_checked", "integrity")}
    # How the builder obtained a file (live vs its own cache) is not a property of the data; inside the snapshot
    # every source is served from the snapshot. retrieved_at and content_hash still pin the exact bytes.
    con.execute("UPDATE sources SET provenance = 'snapshot'")
    con.execute("UPDATE transcript_filings SET provenance = 'snapshot'")
    con.commit()

    digest = content_digest(con)
    meta = {"schema_version": str(SCHEMA_VERSION), "as_of": as_of.isoformat(), "content_digest": digest,
            "symbols": json.dumps(syms), "transcript_symbols": json.dumps(tsyms), "llm": "none"}
    con.executemany("INSERT OR REPLACE INTO snapshot_meta VALUES (?,?)", list(meta.items()))
    con.commit()
    con.execute("VACUUM")
    con.close()
    os.replace(tmp, out)

    sources = sqlite3.connect(out).execute("SELECT COUNT(*), COUNT(DISTINCT url) FROM sources").fetchone()
    manifest = {
        "_about": "Generated by `python -m finn.snapshot build`. content_digest covers the data, not build time.",
        "schema_version": SCHEMA_VERSION, "as_of": as_of.isoformat(), "content_digest": digest,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "offline_build": offline,
        "db_file": out.name, "db_bytes": out.stat().st_size, "llm": "none",
        "sources": {"rows": sources[0], "distinct_urls": sources[1]},
        "golden_values_checked": sum(golden_counts.values()), "companies": summary,
        "transcripts": _transcript_summary(out),
    }
    (manifest_path or out.with_name("manifest.json")).write_text(json.dumps(manifest, indent=1, default=str) + "\n")
    return manifest


def _transcript_summary(path: Path) -> dict:
    con = sqlite3.connect(path)
    out = {}
    for sym, fq, st in con.execute("SELECT symbol, fiscal_quarter, status FROM transcript_coverage ORDER BY symbol, period_end DESC"):
        out.setdefault(sym, {})[fq] = st
    return out


def open_readonly(path: Path = DEFAULT_OUT) -> sqlite3.Connection:
    """The deployed API never writes: immutable=1 also skips locking, which is safe for a file nobody modifies."""
    uri = Path(path).resolve().as_uri() + "?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def verify(path: Path = DEFAULT_OUT, manifest_path: Optional[Path] = None) -> tuple[bool, str]:
    manifest = json.loads((manifest_path or Path(path).with_name("manifest.json")).read_text())
    con = open_readonly(path)
    got = content_digest(con)
    stored = dict(con.execute("SELECT key, value FROM snapshot_meta").fetchall()).get("content_digest")
    con.close()
    ok = got == stored == manifest["content_digest"]
    return ok, f"recomputed {got[:16]} · stored {str(stored)[:16]} · manifest {manifest['content_digest'][:16]}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="finn.snapshot")
    ap.add_argument("command", choices=["build", "verify"])
    ap.add_argument("--offline", action="store_true", help="raw cache only; never touch the network")
    ap.add_argument("--as-of", type=date.fromisoformat, help="snapshot date (IST); default today")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--symbols", nargs="*", help="override the universe (default: config/universe.json)")
    a = ap.parse_args(argv)
    if a.command == "verify":
        ok, msg = verify(a.out)
        print(("OK " if ok else "MISMATCH ") + msg)
        return 0 if ok else 1
    try:
        m = build(a.out, symbols=[s.upper() for s in a.symbols] if a.symbols else None, as_of=a.as_of, offline=a.offline)
    except BuildError as e:
        print(e, file=sys.stderr)
        return 2
    print(json.dumps({k: m[k] for k in ("as_of", "content_digest", "db_bytes", "golden_values_checked", "sources")}))
    for s, c in m["companies"].items():
        print(f"  {s:<11} {c['validation']:<18} {c['latest_period_end']} {c['basis'] or '':<12} {c['taxonomy'] or '':<8} integrity={c['integrity']}")
    for s, q in m["transcripts"].items():
        print(f"  transcripts {s}: {q}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
