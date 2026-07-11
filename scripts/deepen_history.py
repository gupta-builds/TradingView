#!/usr/bin/env python
"""Deepen daily OHLCV history for default walk-forward — without touching gate constants.

Walk-forward literature defaults (unchanged):
  train=504, test=126, step=126, min_windows=3
  → need R >= 882 strategy-return sessions
Momentum warm-up consumes 253 sessions before the first return
  → need panel N >= 1135 OHLCV sessions (~4.5y); recommended N >= 1513 (~6.0y)
  See Docs/PHASE2B_SOLUTION_DESIGN.md.

Massive/Polygon plan reality (https://massive.com/pricing):
  Basic $0  → ~2 years history (this key currently truncates to ~501 bars
              from 2024-07-10) — NOT enough for default WF
  Starter $29 → 5 years — minimum for Phase 2b promotion study
  Developer $79 → 10 years — optional headroom

Tiingo (registry: 5y free, 50 req/hour, split+dividend adjusted `adjClose`)
covers the minimum tier only, added as an alternative to a paid Massive plan
per explicit user instruction — see Docs/PHASE2B_SOLUTION_DESIGN.md §2
("no second price source before F1" refers to *mixing* two sources in
`daily_ohlcv`; switching providers and fully re-backfilling the window with
one source is the supported path, see scripts/rebuild_price_source.py).

This script:
  1. Probes how far back the current key actually returns data
  2. Ingests from --start-date (default 2021-01-01 ≈ 5y) via the existing CLI
  3. Prints a clear PASS/BLOCKED verdict for WF-capable depth
  4. Never modifies gate constants

Usage:
  source .venv/bin/activate
  python scripts/deepen_history.py                  # probe + ingest if deep enough (polygon)
  python scripts/deepen_history.py --probe-only     # no writes
  python scripts/deepen_history.py --start-date 2021-01-01 --force-ingest
  python scripts/deepen_history.py --provider tiingo --probe-only --start-date 2022-01-02
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

from research_data.env import load_dotenv

# Minimum OHLCV sessions for default WF after momentum warm-up (do not change gates).
MIN_SESSIONS_FOR_DEFAULT_WF = 1135
PROBE_TICKER = "VOO"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def probe_depth(api_key: str, start: str, end: str, ticker: str = PROBE_TICKER) -> tuple[int, date | None, date | None, str]:
    """Return (n_bars, first, last, status_note) for one Polygon/Massive aggregates request."""
    url = (
        f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/"
        f"{start}/{end}?adjusted=true&sort=asc&limit=50000&apiKey={api_key}"
    )
    try:
        with urllib.request.urlopen(url, timeout=90) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:400]
        return 0, None, None, f"HTTP {e.code}: {body}"
    except Exception as e:  # noqa: BLE001 — probe must never crash the runner
        return 0, None, None, f"{type(e).__name__}: {e}"

    results = data.get("results") or []
    if not results:
        return 0, None, None, f"no results status={data.get('status')} error={data.get('error')}"

    first = datetime.fromtimestamp(results[0]["t"] / 1000, tz=timezone.utc).date()
    last = datetime.fromtimestamp(results[-1]["t"] / 1000, tz=timezone.utc).date()
    requested_start = date.fromisoformat(start)
    truncated = first > requested_start + __import__("datetime").timedelta(days=14)
    note = "OK"
    if truncated:
        note = (
            f"TRUNCATED: requested {start} but first bar is {first} "
            f"(plan history cap — upgrade Massive Starter+ for 5y)"
        )
    return len(results), first, last, note


def probe_depth_tiingo(
    api_key: str, start: str, end: str, ticker: str = PROBE_TICKER
) -> tuple[int, date | None, date | None, str]:
    """Return (n_bars, first, last, status_note) for one Tiingo EOD request.

    Auth via the Authorization header (never the URL / query string) so the
    key is never present in a printed/logged request. The key itself is
    never echoed by this function under any code path.
    """
    url = f"https://api.tiingo.com/tiingo/daily/{ticker}/prices?startDate={start}&endDate={end}&format=json"
    req = urllib.request.Request(
        url, headers={"Authorization": f"Token {api_key}", "Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:400]
        return 0, None, None, f"HTTP {e.code}: {body}"
    except Exception as e:  # noqa: BLE001 — probe must never crash the runner
        return 0, None, None, f"{type(e).__name__}: {e}"

    if isinstance(data, dict):
        return 0, None, None, f"error payload: {data.get('detail', data)}"
    results = data or []
    if not results:
        return 0, None, None, "no results (empty list)"

    first = date.fromisoformat(str(results[0]["date"])[:10])
    last = date.fromisoformat(str(results[-1]["date"])[:10])
    requested_start = date.fromisoformat(start)
    truncated = first > requested_start + __import__("datetime").timedelta(days=14)
    note = "OK"
    if truncated:
        note = f"TRUNCATED: requested {start} but first bar is {first} (free-tier history cap)"
    return len(results), first, last, note


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--start-date",
        default="2022-01-02",
        help="Target history start (YYYY-MM-DD). Min tier ≈2022-01-02 (N≥1135); "
        "recommended ≈2020-07-06 (N≥1513). See Docs/PHASE2B_SOLUTION_DESIGN.md.",
    )
    parser.add_argument("--end-date", default=None, help="End date (default: today UTC)")
    parser.add_argument("--db-path", default=str(PROJECT_ROOT / "data" / "market.duckdb"))
    parser.add_argument(
        "--provider",
        default="polygon",
        choices=["polygon", "tiingo"],
        help="Price provider to probe/ingest with (default: polygon/Massive)",
    )
    parser.add_argument("--probe-only", action="store_true")
    parser.add_argument(
        "--force-ingest",
        action="store_true",
        help="Ingest even if probe shows depth below WF minimum (extends DB as far as plan allows)",
    )
    args = parser.parse_args()

    end = args.end_date or date.today().isoformat()

    if args.provider == "tiingo":
        api_key = os.environ.get("TIINGO_API_KEY")
        if not api_key:
            print("BLOCKED: TIINGO_API_KEY not set in .env")
            return 2
        print(f"Probing Tiingo depth for {PROBE_TICKER} {args.start_date} → {end} …")
        n, first, last, note = probe_depth_tiingo(api_key, args.start_date, end)
        upgrade_note = "Tiingo free tier covers ~5y; if truncated, no higher paid tier extends it further."
    else:
        api_key = os.environ.get("POLYGON_API_KEY") or os.environ.get("MASSIVE_API_KEY")
        if not api_key:
            print("BLOCKED: POLYGON_API_KEY / MASSIVE_API_KEY not set in .env")
            return 2
        print(f"Probing Massive/Polygon depth for {PROBE_TICKER} {args.start_date} → {end} …")
        n, first, last, note = probe_depth(api_key, args.start_date, end)
        upgrade_note = "Upgrade Massive Stocks Starter ($29/mo, 5y history) or higher."

    print(f"  bars={n} first={first} last={last}")
    print(f"  {note}")
    print(f"  WF minimum (unchanged gates): >= {MIN_SESSIONS_FOR_DEFAULT_WF} OHLCV sessions")

    wf_ready = n >= MIN_SESSIONS_FOR_DEFAULT_WF
    if wf_ready:
        print("VERDICT: depth sufficient for default walk-forward on real DuckDB")
    else:
        print(
            "VERDICT: BLOCKED for Phase 2b promotion study — "
            f"{upgrade_note} "
            f"Current plan returns {n} bars (need >= {MIN_SESSIONS_FOR_DEFAULT_WF})."
        )
        print("  After upgrade: re-run this script (same flags); gate constants stay untouched.")

    if args.probe_only:
        return 0 if wf_ready else 1

    if not wf_ready and not args.force_ingest:
        print("Skipping ingest (pass --force-ingest to store whatever the plan allows).")
        return 1

    cmd = [
        sys.executable,
        "-m",
        "research_data",
        "ingest-prices",
        "--provider",
        args.provider,
        "--start-date",
        args.start_date,
        "--end-date",
        end,
        "--db-path",
        args.db_path,
    ]
    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        return result.returncode

    # Report stored depth
    try:
        import duckdb

        con = duckdb.connect(args.db_path, read_only=True)
        row = con.execute(
            "SELECT MIN(trading_date), MAX(trading_date), COUNT(*) "
            "FROM daily_ohlcv WHERE symbol = 'VOO'"
        ).fetchone()
        print(f"DuckDB VOO: min={row[0]} max={row[1]} n={row[2]}")
        if row[2] >= MIN_SESSIONS_FOR_DEFAULT_WF:
            print("DuckDB now meets default-WF session floor.")
        else:
            print(
                f"DuckDB still below WF floor ({row[2]} < {MIN_SESSIONS_FOR_DEFAULT_WF}). "
                "Upgrade Massive plan, then re-run without --force-ingest."
            )
    except Exception as e:  # noqa: BLE001
        print(f"(could not read DuckDB summary: {e})")

    return 0 if wf_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
