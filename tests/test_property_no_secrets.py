"""Property-based tests for no secrets in stored metadata (Property 13).

Property 13: No Secrets in Stored Metadata
For any request metadata containing secret-like fields (names containing key,
token, secret, password, or authorization), the stored request_params_json in
raw_market_payloads SHALL have those values replaced with "[REDACTED]" while
non-secret fields are preserved unchanged.

**Validates: Requirements 3.5, 14.2, 14.4**
"""

import sys

sys.path.insert(0, "src")

import json
from datetime import datetime, timezone

import duckdb
from hypothesis import given, settings
from hypothesis import strategies as st

from research_data.models import ProviderFetchResult
from research_data.storage import init_db, write_raw_payload


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Secret-like field name fragments (case variations)
_SECRET_FRAGMENTS = ["key", "token", "secret", "password", "authorization"]

# Strategy for generating secret field names (containing one of the secret fragments)
secret_field_names = st.one_of(
    # Simple: just the fragment
    st.sampled_from(_SECRET_FRAGMENTS),
    # Prefixed: e.g., "api_key", "auth_token"
    st.tuples(
        st.from_regex(r"[a-z]{2,6}", fullmatch=True),
        st.sampled_from(_SECRET_FRAGMENTS),
    ).map(lambda t: f"{t[0]}_{t[1]}"),
    # Suffixed: e.g., "key_id", "token_value"
    st.tuples(
        st.sampled_from(_SECRET_FRAGMENTS),
        st.from_regex(r"[a-z]{2,6}", fullmatch=True),
    ).map(lambda t: f"{t[0]}_{t[1]}"),
    # Mixed case: e.g., "API_KEY", "AuthToken"
    st.tuples(
        st.from_regex(r"[A-Za-z]{2,5}", fullmatch=True),
        st.sampled_from([f.upper() for f in _SECRET_FRAGMENTS] + _SECRET_FRAGMENTS),
    ).map(lambda t: f"{t[0]}{t[1]}"),
)

# Strategy for non-secret field names (must NOT contain any secret fragment)
non_secret_field_names = st.from_regex(r"[a-z]{3,8}", fullmatch=True).filter(
    lambda name: not any(frag in name.lower() for frag in _SECRET_FRAGMENTS)
)

# Strategy for secret values (non-empty strings simulating real secrets)
secret_values = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
    min_size=8,
    max_size=64,
).filter(lambda s: s.strip() != "")

# Strategy for non-secret values (various types that could appear in request params)
non_secret_values = st.one_of(
    st.text(min_size=1, max_size=30).filter(lambda s: s.strip() != ""),
    st.integers(min_value=0, max_value=10000),
    st.booleans(),
)


@st.composite
def request_params_with_secrets(draw):
    """Generate a dict with at least one secret field and at least one non-secret field."""
    # Generate 1-3 secret fields
    num_secrets = draw(st.integers(min_value=1, max_value=3))
    secret_fields = {}
    for _ in range(num_secrets):
        name = draw(secret_field_names)
        value = draw(secret_values)
        secret_fields[name] = value

    # Generate 1-3 non-secret fields
    num_non_secrets = draw(st.integers(min_value=1, max_value=3))
    non_secret_fields = {}
    for _ in range(num_non_secrets):
        name = draw(non_secret_field_names)
        value = draw(non_secret_values)
        non_secret_fields[name] = value

    # Combine them
    params = {**secret_fields, **non_secret_fields}
    return params, set(secret_fields.keys()), set(non_secret_fields.keys())


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------


class TestProperty13NoSecretsInStoredMetadata:
    """Property 13: No Secrets in Stored Metadata.

    For any request metadata with secret-like fields, the stored
    request_params_json SHALL have secret values replaced with "[REDACTED]"
    and non-secret fields preserved unchanged.

    **Validates: Requirements 3.5, 14.2, 14.4**
    """

    @given(data=request_params_with_secrets())
    @settings(max_examples=100, deadline=None)
    def test_secrets_redacted_in_stored_metadata(self, data):
        """Verify secret fields are redacted and non-secret fields preserved in stored records."""
        params, secret_keys, non_secret_keys = data

        # Create a ProviderFetchResult with the generated params
        fetch_result = ProviderFetchResult(
            symbol="SPY",
            provider="test_provider",
            request_url="https://api.example.com/v1/prices",
            request_params=params,
            retrieved_at=datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
            raw_payload='{"results": []}',
            content_hash="a" * 64,  # Dummy hash (will be recomputed by write_raw_payload)
            records=[],
            provider_warnings=[],
            rate_limit_state={},
        )

        # Set up in-memory DuckDB
        conn = duckdb.connect(":memory:")
        try:
            conn.execute("SET TimeZone='UTC'")
            init_db(conn)

            # Write the raw payload (this calls redact_secrets internally)
            import tempfile
            import os

            with tempfile.TemporaryDirectory() as tmpdir:
                run_id = "00000000-0000-0000-0000-000000000001"
                write_raw_payload(conn, run_id, fetch_result, tmpdir)

                # Read back the stored request_params_json
                row = conn.execute(
                    """
                    SELECT request_params_json
                    FROM raw_market_payloads
                    WHERE symbol = 'SPY' AND source_name = 'test_provider'
                    """
                ).fetchone()

                assert row is not None, "Expected a row in raw_market_payloads"

                stored_params = json.loads(row[0])

                # Verify all secret fields have value "[REDACTED]"
                for key in secret_keys:
                    if key in stored_params:
                        assert stored_params[key] == "[REDACTED]", (
                            f"Secret field '{key}' should be '[REDACTED]', "
                            f"got: {stored_params[key]!r}"
                        )

                # Verify all non-secret fields are preserved unchanged
                for key in non_secret_keys:
                    if key in stored_params:
                        # Compare with JSON round-trip (values go through json.dumps/loads)
                        expected = params[key]
                        actual = stored_params[key]
                        assert actual == expected, (
                            f"Non-secret field '{key}' should be preserved. "
                            f"Expected: {expected!r}, got: {actual!r}"
                        )

                # Verify that no secret field retains its original value
                # (i.e., every secret field is either absent or "[REDACTED]")
                for key in secret_keys:
                    if key in stored_params:
                        assert stored_params[key] != params[key], (
                            f"Secret field '{key}' still contains its original value"
                        )
        finally:
            conn.close()
