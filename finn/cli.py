"""python -m finn.cli {ingest,card,prices} SYMBOL... [--offline] [--db PATH]"""
from __future__ import annotations

import argparse
import json
import sys

from finn import service, store


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="finn")
    ap.add_argument("command", choices=["ingest", "card", "prices"])
    ap.add_argument("symbols", nargs="+")
    ap.add_argument("--offline", action="store_true", help="use raw cache only; never touch the network")
    ap.add_argument("--db", default="data/finn.db")
    a = ap.parse_args(argv)
    con = store.connect(a.db)
    for sym in (s.upper() for s in a.symbols):
        if a.command == "ingest":
            probs = service.ingest_results(con, sym, offline=a.offline) + service.ingest_filings(con, sym, offline=a.offline)
            print(json.dumps({"symbol": sym, "problems": [p.__dict__ for p in probs]}, default=str))
        elif a.command == "card":
            print(json.dumps(service.results_card(con, sym), indent=1, default=str))
        else:
            print(json.dumps(service.price_signals(sym, offline=a.offline), indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
