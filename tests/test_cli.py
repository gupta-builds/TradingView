"""CLI integration tests (Task 12.5).

Requirements: 9.1–9.7, 15.1, 15.2
"""

from __future__ import annotations

import re
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import pytest
from typer.testing import CliRunner

sys.path.insert(0, "src")

from research_data.cli import app, run_benchmark, run_ingestion
from research_data.models import QualityStatus
from research_data.storage import (
    batch_insert_ohlcv,
    init_db,
    seed_metadata,
    store_quality_report,
)
from research_data.config import load_config
from research_data.models import DataQualityReport

from helpers import make_series

runner = CliRunner()
_EXEC_RE = re.compile(r"\b(BUY NOW|SELL NOW|BUY|SELL|HOLD)\b", re.IGNORECASE)


@pytest.fixture
def db_env(tmp_path):
    db_path = tmp_path / "test.duckdb"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return str(db_path), str(data_dir)


class TestCLIIntegration:
    def test_init_db_creates_tables(self, db_env):
        db_path, _ = db_env
        result = runner.invoke(app, ["init-db", "--db-path", db_path])
        assert result.exit_code == 0, result.output
        conn = duckdb.connect(db_path)
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
            ).fetchall()
        }
        for expected in (
            "assets",
            "providers",
            "ingestion_runs",
            "raw_market_payloads",
            "daily_ohlcv",
            "data_quality_reports",
        ):
            assert expected in tables
        conn.close()

    def test_ingest_prices_csv_fixture(self, db_env):
        db_path, data_dir = db_env
        result = runner.invoke(
            app,
            [
                "ingest-prices",
                "--provider", "csv_fixture",
                "--symbols", "VOO",
                "--symbols", "SPY",
                "--symbols", "MSFT",
                "--start-date", "2024-01-01",
                "--end-date", "2024-04-30",
                "--db-path", db_path,
                "--data-dir", data_dir,
            ],
        )
        assert result.exit_code == 0, result.output
        assert "VOO" in result.output
        assert _EXEC_RE.search(result.output) is None
        conn = duckdb.connect(db_path)
        n = conn.execute("SELECT COUNT(*) FROM daily_ohlcv").fetchone()[0]
        assert n > 0
        q = conn.execute("SELECT COUNT(*) FROM data_quality_reports").fetchone()[0]
        assert q >= 3
        conn.close()

    def test_ingest_prices_comma_separated_symbols(self, db_env):
        db_path, data_dir = db_env
        result = runner.invoke(
            app,
            [
                "ingest-prices",
                "--provider", "csv_fixture",
                "--symbols", "VOO,SPY,MSFT",
                "--start-date", "2024-01-01",
                "--end-date", "2024-04-30",
                "--db-path", db_path,
                "--data-dir", data_dir,
            ],
        )
        assert result.exit_code == 0, result.output
        conn = duckdb.connect(db_path)
        symbols = {
            r[0]
            for r in conn.execute("SELECT DISTINCT symbol FROM daily_ohlcv").fetchall()
        }
        assert symbols >= {"VOO", "SPY", "MSFT"}
        conn.close()

    def test_audit_prices_prints_status(self, db_env):
        db_path, data_dir = db_env
        runner.invoke(
            app,
            [
                "ingest-prices",
                "--provider", "csv_fixture",
                "--symbols", "VOO",
                "--start-date", "2024-01-01",
                "--end-date", "2024-04-30",
                "--db-path", db_path,
                "--data-dir", data_dir,
            ],
        )
        result = runner.invoke(
            app,
            ["audit-prices", "--symbols", "VOO", "--db-path", db_path],
        )
        assert result.exit_code == 0, result.output
        assert "VOO" in result.output
        assert "status" in result.output.lower() or "usable" in result.output or "stale" in result.output or "partial" in result.output or "insufficient" in result.output

    def test_benchmark_computes_from_seeded_data(self, db_env):
        db_path, _ = db_env
        conn = duckdb.connect(db_path)
        init_db(conn)
        config = load_config()
        seed_metadata(conn, config)
        today = date.today()
        start = date(today.year - 1, today.month, min(today.day, 28))
        records = make_series("VOO", 60, start=start)
        # Ensure last date is today-ish so not stale for our planted quality
        records[-1] = records[-1].model_copy(update={"trading_date": today, "data_as_of": today})
        batch_insert_ohlcv(conn, records)
        report = DataQualityReport(
            report_id=str(uuid.uuid4()),
            run_id=str(uuid.uuid4()),
            symbol="VOO",
            source_name="csv_fixture",
            generated_at=datetime.now(timezone.utc),
            requested_start_date=start,
            requested_end_date=today,
            first_available_date=records[0].trading_date,
            last_available_date=today,
            expected_sessions=60,
            valid_sessions=60,
            missing_sessions=[],
            rejected_records=0,
            quality_status=QualityStatus.USABLE,
            confidence_cap=1.0,
            issues_json={},
        )
        store_quality_report(conn, report)
        conn.close()

        result = runner.invoke(
            app,
            [
                "benchmark",
                "--symbols", "VOO",
                "--benchmark-symbol", "VOO",
                "--period", "1y",
                "--db-path", db_path,
            ],
        )
        assert result.exit_code == 0, result.output
        assert "total_return" in result.output
        assert _EXEC_RE.search(result.output) is None

    def test_benchmark_refuses_insufficient_nonzero_exit(self, db_env):
        db_path, _ = db_env
        conn = duckdb.connect(db_path)
        init_db(conn)
        report = DataQualityReport(
            report_id=str(uuid.uuid4()),
            run_id=str(uuid.uuid4()),
            symbol="AAPL",
            source_name="csv_fixture",
            generated_at=datetime.now(timezone.utc),
            requested_start_date=date(2024, 1, 1),
            requested_end_date=date(2024, 6, 1),
            expected_sessions=0,
            valid_sessions=0,
            missing_sessions=[],
            rejected_records=0,
            quality_status=QualityStatus.INSUFFICIENT_DATA,
            confidence_cap=0.4,
            issues_json={},
        )
        store_quality_report(conn, report)
        conn.close()
        result = runner.invoke(
            app,
            [
                "benchmark",
                "--symbols", "AAPL",
                "--benchmark-symbol", "VOO",
                "--db-path", db_path,
            ],
        )
        assert result.exit_code != 0
        assert "AAPL" in result.output or "unavailable" in result.output.lower() or "insufficient" in result.output.lower()

    def test_invalid_command_exits_nonzero(self):
        result = runner.invoke(app, ["not-a-real-command"])
        assert result.exit_code != 0
