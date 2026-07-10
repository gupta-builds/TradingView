"""Typer CLI for the research_data ingestion foundation.

Commands: init-db, ingest-prices, audit-prices, benchmark.
Wires ProviderRegistry → raw payload writer → normalizer → quality auditor
→ storage. Never emits BUY/SELL/HOLD execution language.

Requirements: 9.1–9.7, 13.1–13.6, 14.1, 14.5
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import duckdb
import typer

from research_data.benchmark import BenchmarkError, compute_benchmark
from research_data.calendar import MarketCalendar
from research_data.config import ConfigError, load_config
from research_data.models import QualityStatus
from research_data.normalization import normalize_fetch_result
from research_data.providers.base import ProviderRegistry
from research_data.quality import DataQualityAuditor
from research_data.read_api import PriceReadAPI
from research_data.storage import (
    batch_insert_ohlcv,
    init_db,
    record_ingestion_run,
    seed_metadata,
    store_quality_report,
    update_ingestion_run,
    write_raw_payload,
)

app = typer.Typer(
    name="research-data",
    help=(
        "Local market-data ingestion and quality auditing for research. "
        "This tool does not provide trade execution directives."
    ),
    add_completion=False,
    no_args_is_help=True,
)


def _parse_symbols(raw: list[str] | None) -> list[str] | None:
    """Normalize --symbols from repeated flags and/or comma/space-separated values."""
    if not raw:
        return None
    out: list[str] = []
    for item in raw:
        for part in re.split(r"[\s,]+", item.strip()):
            if part:
                out.append(part.upper())
    return out or None

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DB = str(_PROJECT_ROOT / "data" / "market.duckdb")
_DEFAULT_DATA_DIR = str(_PROJECT_ROOT / "data")

_EXECUTION_PATTERN = re.compile(r"\b(BUY NOW|SELL NOW|BUY|SELL|HOLD)\b", re.IGNORECASE)


class CLIError(Exception):
    """CLI-level error with non-zero exit semantics."""


def verify_env_gitignore(project_root: Path | None = None) -> None:
    """Refuse to start if .env is not listed in .gitignore (Req 14.1, 14.5)."""
    root = project_root or _PROJECT_ROOT
    gitignore = root / ".gitignore"
    if not gitignore.is_file():
        raise CLIError(
            ".gitignore not found; cannot verify that .env is excluded from version control."
        )
    text = gitignore.read_text(encoding="utf-8")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if ".env" not in lines and not any(ln == ".env" or ln.startswith(".env") for ln in lines):
        raise CLIError(
            ".env is not listed in .gitignore. "
            "Add '.env' to .gitignore before loading API keys."
        )


def load_dotenv_if_present(project_root: Path | None = None) -> None:
    """Load key=value pairs from .env into os.environ if the file exists.

    Does not override existing environment variables. Only called after
    verify_env_gitignore succeeds.
    """
    root = project_root or _PROJECT_ROOT
    env_path = root / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _guard_output(text: str) -> str:
    """Strip/refuse execution language in CLI output."""
    if _EXECUTION_PATTERN.search(text):
        raise CLIError("Refusing to emit execution language in CLI output")
    return text


def _parse_date(value: str | None, default: date) -> date:
    if value is None:
        return default
    try:
        return date.fromisoformat(value)
    except ValueError as e:
        raise CLIError(f"Invalid date '{value}': use YYYY-MM-DD") from e


def _open_db(db_path: str) -> duckdb.DuckDBPyConnection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path))


def _config_hash(config_repr: str) -> str:
    return hashlib.sha256(config_repr.encode("utf-8")).hexdigest()


@app.callback()
def main_callback() -> None:
    """Verify .env gitignore and load local secrets before any command."""
    try:
        verify_env_gitignore()
        load_dotenv_if_present()
    except CLIError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e


@app.command("init-db")
def init_db_cmd(
    db_path: str = typer.Option(_DEFAULT_DB, "--db-path", help="Path to DuckDB file"),
) -> None:
    """Create DuckDB tables and seed provider/asset metadata."""
    try:
        config = load_config()
        conn = _open_db(db_path)
        try:
            init_db(conn)
            seed_metadata(conn, config)
        finally:
            conn.close()
        typer.echo(_guard_output(f"Initialized database at {db_path}"))
    except (CLIError, ConfigError) as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e


@app.command("ingest-prices")
def ingest_prices_cmd(
    symbols: Optional[list[str]] = typer.Option(
        None,
        "--symbols",
        "-s",
        help="Symbols to ingest; repeat flag or pass comma/space-separated (default: V1 universe)",
    ),
    start_date: Optional[str] = typer.Option(
        None, "--start-date", help="Start date YYYY-MM-DD (default: 365 days ago)"
    ),
    end_date: Optional[str] = typer.Option(
        None, "--end-date", help="End date YYYY-MM-DD (default: today)"
    ),
    provider: Optional[str] = typer.Option(
        None, "--provider", help="Provider name (default: configured default)"
    ),
    adjusted: bool = typer.Option(True, "--adjusted/--raw", help="Request adjusted prices"),
    db_path: str = typer.Option(_DEFAULT_DB, "--db-path", help="Path to DuckDB file"),
    data_dir: str = typer.Option(_DEFAULT_DATA_DIR, "--data-dir", help="Raw payload directory"),
) -> None:
    """Fetch daily OHLCV, store raw payloads, normalize, and write quality reports."""
    try:
        summary = run_ingestion(
            symbols=_parse_symbols(symbols),
            start_date_str=start_date,
            end_date_str=end_date,
            provider_name=provider,
            adjusted=adjusted,
            db_path=db_path,
            data_dir=data_dir,
        )
        typer.echo(_guard_output(summary))
    except (CLIError, ConfigError) as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e


@app.command("audit-prices")
def audit_prices_cmd(
    symbols: Optional[list[str]] = typer.Option(
        None,
        "--symbols",
        "-s",
        help="Symbols to audit; repeat flag or pass comma/space-separated (default: V1 universe)",
    ),
    provider: Optional[str] = typer.Option(
        None, "--provider", help="Filter by provider/source"
    ),
    db_path: str = typer.Option(_DEFAULT_DB, "--db-path", help="Path to DuckDB file"),
) -> None:
    """Print latest coverage, freshness, gaps, and quality status."""
    try:
        text = run_audit(
            symbols=_parse_symbols(symbols), provider=provider, db_path=db_path
        )
        typer.echo(_guard_output(text))
    except (CLIError, ConfigError) as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e


@app.command("benchmark")
def benchmark_cmd(
    symbols: Optional[list[str]] = typer.Option(
        None,
        "--symbols",
        "-s",
        help="Symbols to evaluate; repeat flag or pass comma/space-separated (default: V1 universe)",
    ),
    benchmark_symbol: str = typer.Option("VOO", "--benchmark-symbol", help="ETF baseline"),
    period: str = typer.Option("1y", "--period", help="Lookback period (e.g. 1y)"),
    db_path: str = typer.Option(_DEFAULT_DB, "--db-path", help="Path to DuckDB file"),
) -> None:
    """Print return, volatility, drawdown, and baseline comparison metrics."""
    try:
        text, ok = run_benchmark(
            symbols=_parse_symbols(symbols),
            benchmark_symbol=benchmark_symbol,
            period=period,
            db_path=db_path,
        )
        typer.echo(_guard_output(text))
        if not ok:
            raise typer.Exit(code=1)
    except (CLIError, ConfigError) as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e


def run_ingestion(
    *,
    symbols: list[str] | None,
    start_date_str: str | None,
    end_date_str: str | None,
    provider_name: str | None,
    adjusted: bool,
    db_path: str,
    data_dir: str,
) -> str:
    """End-to-end ingestion pipeline (CLI → provider → storage → quality)."""
    config = load_config()
    symbol_list = symbols or list(config.universe.symbols)
    today = datetime.now(timezone.utc).date()
    start = _parse_date(start_date_str, today - timedelta(days=365))
    end = _parse_date(end_date_str, today)

    registry = ProviderRegistry(config=config)
    name = provider_name or registry.default_provider_name
    provider = registry.get_provider(name)
    provider_config = registry.get_provider_config(name)

    conn = _open_db(db_path)
    init_db(conn)
    seed_metadata(conn, config)

    started_at = datetime.now(timezone.utc)
    run_id = record_ingestion_run(
        conn,
        {
            "source_name": name,
            "started_at": started_at,
            "completed_at": None,
            "symbols_requested": symbol_list,
            "start_date": start,
            "end_date": end,
            "adjusted": adjusted,
            "status": "running",
            "records_fetched": 0,
            "records_stored": 0,
            "error_message": None,
            "config_hash": _config_hash(f"{name}|{sorted(symbol_list)}|{start}|{end}|{adjusted}"),
        },
    )

    calendar = MarketCalendar()
    auditor = DataQualityAuditor(calendar=calendar)
    total_fetched = 0
    total_stored = 0
    lines: list[str] = [f"Ingestion run {run_id} provider={name}"]
    run_status = "completed"
    error_message: str | None = None

    try:
        for symbol in symbol_list:
            asset = config.universe.assets.get(symbol)
            exchange = asset.exchange if asset else "NYSE"
            try:
                fetch_result = provider.fetch_daily_ohlcv(symbol, start, end, adjusted)
            except Exception as e:
                run_status = "failed"
                error_message = str(e)
                lines.append(f"{symbol}: FAILED fetch ({e})")
                # Still write MISSING quality report
                report = auditor.audit_symbol(
                    symbol=symbol,
                    records=[],
                    exchange=exchange,
                    start_date=start,
                    end_date=end,
                    run_id=run_id,
                    source_name=name,
                    rejected_records=0,
                )
                store_quality_report(conn, report)
                continue

            write_raw_payload(conn, run_id, fetch_result, data_dir)
            norm = normalize_fetch_result(fetch_result, provider_config, calendar=calendar)
            total_fetched += len(fetch_result.records)
            stored = batch_insert_ohlcv(conn, norm.valid_records)
            total_stored += stored

            report = auditor.audit_symbol(
                symbol=symbol,
                records=norm.valid_records,
                exchange=exchange,
                start_date=start,
                end_date=end,
                run_id=run_id,
                source_name=name,
                rejected_records=norm.rejected_count,
            )
            store_quality_report(conn, report)

            # Propagate quality status onto stored rows for this symbol/source
            conn.execute(
                """
                UPDATE daily_ohlcv
                SET quality_status = ?
                WHERE symbol = ? AND source = ?
                  AND trading_date >= ? AND trading_date <= ?
                """,
                [report.quality_status.value, symbol, name, start, end],
            )

            if fetch_result.rate_limit_state.get("waited_seconds", 0) > 0:
                run_status = "partial" if run_status == "completed" else run_status

            lines.append(
                f"{symbol}: stored={stored} rejected={norm.rejected_count} "
                f"status={report.quality_status.value} "
                f"confidence_cap={report.confidence_cap:.2f} "
                f"valid_sessions={report.valid_sessions}"
            )
    except Exception as e:
        run_status = "failed"
        error_message = str(e)
        lines.append(f"Pipeline error: {e}")
    finally:
        update_ingestion_run(
            conn,
            run_id,
            status=run_status,
            completed_at=datetime.now(timezone.utc),
            records_fetched=total_fetched,
            records_stored=total_stored,
            error_message=error_message,
        )
        conn.close()

    lines.append(f"run_status={run_status} fetched={total_fetched} stored={total_stored}")
    return "\n".join(lines)


def run_audit(
    *,
    symbols: list[str] | None,
    provider: str | None,
    db_path: str,
) -> str:
    """Print latest quality reports for symbols."""
    config = load_config()
    symbol_list = symbols or list(config.universe.symbols)
    conn = _open_db(db_path)
    try:
        lines = ["symbol | source | status | valid | missing | last_date | confidence_cap"]
        for symbol in symbol_list:
            params: list[object] = [symbol]
            sql = """
                SELECT symbol, source_name, quality_status, valid_sessions,
                       len(missing_sessions), last_available_date, confidence_cap
                FROM data_quality_reports
                WHERE symbol = ?
            """
            if provider:
                sql += " AND source_name = ?"
                params.append(provider)
            sql += " ORDER BY generated_at DESC LIMIT 1"
            row = conn.execute(sql, params).fetchone()
            if row is None:
                lines.append(f"{symbol} | - | missing | 0 | - | - | 0.00")
            else:
                lines.append(
                    f"{row[0]} | {row[1]} | {row[2]} | {row[3]} | "
                    f"{row[4]} | {row[5]} | {row[6]:.2f}"
                )
        return "\n".join(lines)
    finally:
        conn.close()


def _period_to_start(period: str, end: date) -> date:
    period = period.lower().strip()
    if period.endswith("y") and period[:-1].isdigit():
        years = int(period[:-1])
        return date(end.year - years, end.month, end.day)
    if period.endswith("m") and period[:-1].isdigit():
        months = int(period[:-1])
        year = end.year
        month = end.month - months
        while month <= 0:
            month += 12
            year -= 1
        day = min(end.day, 28)
        return date(year, month, day)
    if period.endswith("d") and period[:-1].isdigit():
        return end - timedelta(days=int(period[:-1]))
    raise CLIError(f"Unsupported period '{period}'; use e.g. 1y, 6m, 90d")


def run_benchmark(
    *,
    symbols: list[str] | None,
    benchmark_symbol: str,
    period: str,
    db_path: str,
) -> tuple[str, bool]:
    """Compute and format benchmark metrics; ok=False if any symbol fails."""
    config = load_config()
    symbol_list = symbols or list(config.universe.symbols)
    end = datetime.now(timezone.utc).date()
    start = _period_to_start(period, end)

    conn = _open_db(db_path)
    try:
        api = PriceReadAPI(conn)
        lines: list[str] = []
        all_ok = True

        # Load benchmark baseline once
        bm_status = _latest_quality(conn, benchmark_symbol)
        try:
            bm_records = api.get_price_frame(
                [benchmark_symbol], start, end, require_usable=False
            )
        except Exception:
            bm_records = []

        for symbol in symbol_list:
            status = _latest_quality(conn, symbol)
            missing_count = _latest_missing_count(conn, symbol)
            try:
                records = api.get_price_frame(
                    [symbol], start, end, require_usable=False
                )
                report = compute_benchmark(
                    symbol=symbol,
                    records=records,
                    quality_status=status,
                    missing_session_count=missing_count,
                    benchmark_symbol=benchmark_symbol,
                    benchmark_records=bm_records if symbol != benchmark_symbol else bm_records,
                )
                # All 8 metrics must be present; excess may be None → fail
                if report.benchmark_excess_return is None and symbol != benchmark_symbol:
                    all_ok = False
                    lines.append(
                        f"{symbol}: incomplete metrics "
                        f"(insufficient overlap with {benchmark_symbol}); "
                        f"quality_status={report.quality_label}"
                    )
                else:
                    # For the baseline itself, excess vs self is 0
                    if symbol == benchmark_symbol and report.benchmark_excess_return is None:
                        # Recompute with self as baseline already done; treat excess as 0
                        from dataclasses import replace

                        report = replace(report, benchmark_excess_return=0.0)
                    lines.append(report.format_text())
            except BenchmarkError as e:
                all_ok = False
                label = map_status_label(e.quality_status) if e.quality_status else "unknown"
                lines.append(
                    f"{symbol}: metrics unavailable — {e.reason}; "
                    f"quality_status={label}"
                )
        return "\n".join(lines), all_ok
    finally:
        conn.close()


def map_status_label(status: QualityStatus | None) -> str:
    from research_data.benchmark import map_quality_label

    if status is None:
        return "unknown"
    return map_quality_label(status)


def _latest_quality(conn: duckdb.DuckDBPyConnection, symbol: str) -> QualityStatus:
    row = conn.execute(
        """
        SELECT quality_status FROM data_quality_reports
        WHERE symbol = ?
        ORDER BY generated_at DESC LIMIT 1
        """,
        [symbol],
    ).fetchone()
    if row is None:
        return QualityStatus.MISSING
    return QualityStatus(row[0])


def _latest_missing_count(conn: duckdb.DuckDBPyConnection, symbol: str) -> int:
    row = conn.execute(
        """
        SELECT len(missing_sessions) FROM data_quality_reports
        WHERE symbol = ?
        ORDER BY generated_at DESC LIMIT 1
        """,
        [symbol],
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def main() -> None:
    """Entrypoint for `python -m research_data.cli`."""
    app()


if __name__ == "__main__":
    main()
