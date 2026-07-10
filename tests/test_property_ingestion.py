"""Property tests for ingestion idempotence and raw-before-normalized ordering.

Properties 19 and 4 — Requirements 8.2, 8.5, 3.1, 5.8
"""

from __future__ import annotations

import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, "src")

from research_data.config import ProviderConfig
from research_data.models import ProviderFetchResult
from research_data.normalization import normalize_fetch_result
from research_data.storage import (
    batch_insert_ohlcv,
    init_db,
    write_raw_payload,
)

from helpers import fresh_db, make_ohlcv


def _provider_config() -> ProviderConfig:
    return ProviderConfig(
        source_name="csv_fixture",
        source_url="file://tests/fixtures/",
        license_note="test",
        requires_api_key=False,
        rate_limit=0,
        adjustment_policy="split_dividend_adjusted",
    )


@st.composite
def fetch_results(draw, tmp_hashes=None):
    symbol = draw(st.sampled_from(["VOO", "SPY", "MSFT"]))
    n = draw(st.integers(min_value=1, max_value=8))
    start = date(2024, 1, 2)
    records = []
    payload_lines = ["date,open,high,low,close,volume,adjusted_close"]
    for i in range(n):
        d = date(2024, 1, 2 + i)
        # skip weekends roughly by using weekdays only via offset
        close = 100.0 + i
        rec = make_ohlcv(symbol=symbol, trading_date=d, close=close, source="csv_fixture")
        records.append(rec)
        payload_lines.append(
            f"{d.isoformat()},{close-1},{close+1},{close-2},{close},1000,{close}"
        )
    raw = "\n".join(payload_lines)
    import hashlib

    content_hash = hashlib.sha256(raw.encode()).hexdigest()
    # Align record hashes with payload hash
    records = [
        r.model_copy(update={"raw_payload_hash": content_hash}) for r in records
    ]
    return ProviderFetchResult(
        symbol=symbol,
        provider="csv_fixture",
        request_url="file://tests/fixtures/",
        request_params={"symbol": symbol},
        retrieved_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
        raw_payload=raw,
        content_hash=content_hash,
        records=records,
    )


class TestProperty19IngestionIdempotence:
    @given(fetch=fetch_results())
    @settings(max_examples=25, deadline=None)
    def test_reingest_identical_payload_no_duplicates(self, fetch):
        data_dir = Path("/tmp") / f"rd_idempotence_{uuid.uuid4().hex}"
        data_dir.mkdir(parents=True, exist_ok=True)
        conn = fresh_db()
        run_id = str(uuid.uuid4())
        cfg = _provider_config()

        write_raw_payload(conn, run_id, fetch, data_dir)
        norm1 = normalize_fetch_result(fetch, cfg)
        batch_insert_ohlcv(conn, norm1.valid_records)

        write_raw_payload(conn, run_id, fetch, data_dir)
        norm2 = normalize_fetch_result(fetch, cfg)
        batch_insert_ohlcv(conn, norm2.valid_records)

        count = conn.execute(
            "SELECT COUNT(*) FROM daily_ohlcv WHERE symbol = ?", [fetch.symbol]
        ).fetchone()[0]
        assert count == len(norm1.valid_records)

        raw_count = conn.execute(
            "SELECT COUNT(*) FROM raw_market_payloads WHERE symbol = ?",
            [fetch.symbol],
        ).fetchone()[0]
        assert raw_count == 1


class TestProperty4RawBeforeNormalized:
    @given(fetch=fetch_results())
    @settings(max_examples=25, deadline=None)
    def test_every_normalized_row_has_prior_raw_payload(self, fetch):
        data_dir = Path("/tmp") / f"rd_raw_before_{uuid.uuid4().hex}"
        data_dir.mkdir(parents=True, exist_ok=True)
        conn = fresh_db()
        run_id = str(uuid.uuid4())
        cfg = _provider_config()

        write_raw_payload(conn, run_id, fetch, data_dir)
        norm = normalize_fetch_result(fetch, cfg)
        batch_insert_ohlcv(conn, norm.valid_records)

        rows = conn.execute(
            """
            SELECT d.raw_payload_hash, d.retrieved_at, r.retrieved_at
            FROM daily_ohlcv d
            LEFT JOIN raw_market_payloads r
              ON d.raw_payload_hash = r.raw_payload_hash
            WHERE d.symbol = ?
            """,
            [fetch.symbol],
        ).fetchall()
        assert rows
        for payload_hash, norm_ts, raw_ts in rows:
            assert payload_hash is not None
            assert raw_ts is not None
            # raw retrieved_at <= normalized retrieved_at
            assert raw_ts <= norm_ts
