"""Property-based tests for raw payload hash consistency (Property 3).

Property 3: Raw Payload Hash Consistency
For any raw payload written to disk, the SHA-256 hash stored in raw_market_payloads
SHALL equal the SHA-256 hash recomputed from the file at the recorded payload_path.

**Validates: Requirements 3.2, 3.3**
"""

import hashlib
import sys
import tempfile
import uuid

sys.path.insert(0, "src")

from datetime import datetime, timezone
from pathlib import Path

import duckdb
from hypothesis import given, settings
from hypothesis import strategies as st

from research_data.models import ProviderFetchResult
from research_data.storage import init_db, record_ingestion_run, write_raw_payload


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Generate non-empty raw payload strings (arbitrary text content)
raw_payloads = st.text(min_size=1, max_size=5000)

# Valid uppercase symbols
valid_symbols = st.from_regex(r"[A-Z]{1,5}", fullmatch=True)

# Valid provider names
valid_providers = st.sampled_from(["polygon", "tiingo", "csv_fixture", "alpha_vantage"])

# Valid retrieved_at timestamps (past, with UTC timezone)
valid_retrieved_at = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2025, 6, 1),
    timezones=st.just(timezone.utc),
)


@st.composite
def fetch_results_with_payload(draw):
    """Generate a ProviderFetchResult with a random raw payload."""
    payload = draw(raw_payloads)
    symbol = draw(valid_symbols)
    provider = draw(valid_providers)
    retrieved_at = draw(valid_retrieved_at)

    # Compute content hash as the real code would
    content_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    return ProviderFetchResult(
        symbol=symbol,
        provider=provider,
        request_url=f"https://api.example.com/v1/ohlcv/{symbol}",
        request_params={"symbol": symbol, "format": "json"},
        retrieved_at=retrieved_at,
        raw_payload=payload,
        content_hash=content_hash,
        records=[],
        provider_warnings=[],
        rate_limit_state={},
    )


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------


class TestProperty3RawPayloadHashConsistency:
    """Property 3: Raw Payload Hash Consistency.

    For any raw payload written to disk, the SHA-256 hash stored in
    raw_market_payloads SHALL equal the SHA-256 hash recomputed from
    the file at the recorded payload_path.

    **Validates: Requirements 3.2, 3.3**
    """

    @given(fetch_result=fetch_results_with_payload())
    @settings(max_examples=100, deadline=None)
    def test_stored_hash_matches_recomputed_hash_from_file(
        self, fetch_result: ProviderFetchResult
    ):
        """Write a raw payload to disk and verify the stored SHA-256 matches
        the hash recomputed from the file content."""
        conn = duckdb.connect(":memory:")
        try:
            conn.execute("SET TimeZone='UTC'")
            init_db(conn)

            # Create a temporary directory for raw payload storage
            with tempfile.TemporaryDirectory() as tmp_dir:
                data_dir = Path(tmp_dir)

                # Record an ingestion run (required for foreign key context)
                run_id = str(uuid.uuid4())
                record_ingestion_run(
                    conn,
                    {
                        "run_id": run_id,
                        "source_name": fetch_result.provider,
                        "started_at": datetime.now(timezone.utc),
                        "completed_at": None,
                        "symbols_requested": [fetch_result.symbol],
                        "start_date": fetch_result.retrieved_at.date(),
                        "end_date": fetch_result.retrieved_at.date(),
                        "adjusted": True,
                        "status": "running",
                        "records_fetched": 0,
                        "records_stored": 0,
                        "error_message": None,
                        "config_hash": "test_config_hash",
                    },
                )

                # Write the raw payload
                returned_hash = write_raw_payload(
                    conn, run_id, fetch_result, data_dir
                )

                # Verify the returned hash matches expected SHA-256
                expected_hash = hashlib.sha256(
                    fetch_result.raw_payload.encode("utf-8")
                ).hexdigest()
                assert returned_hash == expected_hash, (
                    f"Returned hash {returned_hash} != expected {expected_hash}"
                )

                # Query the stored hash and payload_path from the database
                row = conn.execute(
                    """
                    SELECT raw_payload_hash, payload_path
                    FROM raw_market_payloads
                    WHERE raw_payload_hash = ?
                    """,
                    [returned_hash],
                ).fetchone()

                assert row is not None, "No row found in raw_market_payloads"
                stored_hash = row[0]
                payload_path = row[1]

                # Read the file back from disk
                full_path = data_dir / payload_path
                assert full_path.exists(), (
                    f"Payload file not found at {full_path}"
                )
                file_content = full_path.read_bytes()

                # Recompute SHA-256 from the file content
                recomputed_hash = hashlib.sha256(file_content).hexdigest()

                # Verify stored hash matches recomputed hash from file
                assert stored_hash == recomputed_hash, (
                    f"Stored hash {stored_hash} != recomputed hash "
                    f"{recomputed_hash} from file at {payload_path}"
                )

                # Also verify the returned hash matches the stored hash
                assert returned_hash == stored_hash, (
                    f"Returned hash {returned_hash} != stored hash {stored_hash}"
                )
        finally:
            conn.close()
