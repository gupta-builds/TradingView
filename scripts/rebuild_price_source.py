#!/usr/bin/env python
"""Purge daily_ohlcv rows for one source before a clean single-source re-backfill.

Phase 2b requires "one price source for the entire deepened window per
symbol" (Docs/PHASE2B_SOLUTION_DESIGN.md §2) -- `daily_ohlcv`'s primary key
includes `source`, so switching providers without first purging the old
source's rows would leave two providers' rows coexisting on overlapping
dates and corrupt the per-symbol session calendar (the F1 risk documented
for the later study code). This script deletes the old rows so the very
next `research_data ingest-prices --provider <new>` run repopulates a clean,
single-source table -- no rows are ever synthesized here, only removed.

Only touches `daily_ohlcv`. Leaves `raw_market_payloads` / `ingestion_runs`
/ `data_quality_reports` alone (historical provenance; harmless to leave
stale, and not read by the V1-V5 verification queries).

Usage:
  source .venv/bin/activate
  python scripts/rebuild_price_source.py --old-source polygon              # dry run (default)
  python scripts/rebuild_price_source.py --old-source polygon --confirm    # actually delete
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-source", required=True, help="source value to purge from daily_ohlcv")
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=None,
        help="Symbols to purge (default: all symbols currently stored for --old-source)",
    )
    parser.add_argument("--db-path", default=str(PROJECT_ROOT / "data" / "market.duckdb"))
    parser.add_argument("--confirm", action="store_true", help="Actually delete (default is dry-run)")
    args = parser.parse_args()

    con = duckdb.connect(args.db_path)
    try:
        where = "source = ?"
        params: list[object] = [args.old_source]
        if args.symbols:
            placeholders = ", ".join("?" for _ in args.symbols)
            where += f" AND symbol IN ({placeholders})"
            params.extend(s.upper() for s in args.symbols)

        rows = con.execute(
            f"SELECT symbol, COUNT(*) FROM daily_ohlcv WHERE {where} GROUP BY symbol ORDER BY symbol",
            params,
        ).fetchall()
        total = sum(n for _, n in rows)
        print(f"Matched {total} rows across {len(rows)} symbols for source='{args.old_source}':")
        for symbol, n in rows:
            print(f"  {symbol}: {n} rows")

        if not args.confirm:
            print("Dry run only (pass --confirm to delete). No rows removed.")
            return 0

        con.execute(f"DELETE FROM daily_ohlcv WHERE {where}", params)
        remaining = con.execute(f"SELECT COUNT(*) FROM daily_ohlcv WHERE {where}", params).fetchone()[0]
        print(f"Deleted. Remaining rows matching filter: {remaining} (expect 0).")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
