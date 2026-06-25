"""Property-based tests for provider registry validation (Property 10).

Property 10: Provider Registry Rejects Invalid Configuration
For any provider configuration entry missing one or more required fields
(source_name, source_url, license_note, requires_api_key, rate_limit,
adjustment_policy), the Provider_Registry SHALL refuse to load that provider
and emit an error identifying the missing fields.

**Validates: Requirements 1.1, 1.2**
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "src")

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from research_data.config import (
    ConfigError,
    REQUIRED_PROVIDER_FIELDS,
    load_providers_config,
)

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# All required fields for a valid provider entry
_ALL_REQUIRED = sorted(REQUIRED_PROVIDER_FIELDS)

# TOML-safe alphabet for string values (printable ASCII without control chars)
_TOML_SAFE_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-./:"

# Valid values for each required field
_VALID_FIELD_VALUES = {
    "source_name": st.text(min_size=1, max_size=30, alphabet="abcdefghijklmnopqrstuvwxyz_"),
    "source_url": st.text(min_size=5, max_size=50, alphabet="abcdefghijklmnopqrstuvwxyz0123456789:/._-"),
    "license_note": st.text(min_size=1, max_size=100, alphabet=_TOML_SAFE_ALPHABET),
    "requires_api_key": st.booleans(),
    "rate_limit": st.integers(min_value=0, max_value=1000),
    "adjustment_policy": st.sampled_from(["raw", "split_adjusted", "split_dividend_adjusted", "unknown"]),
}


@st.composite
def provider_config_with_missing_fields(draw):
    """Generate a provider config dict with a random non-empty subset of required fields removed.

    Returns a tuple of (provider_name, config_dict, missing_fields_set).
    """
    # Choose which fields to remove (at least 1, up to all)
    fields_to_remove = draw(
        st.lists(
            st.sampled_from(_ALL_REQUIRED),
            min_size=1,
            max_size=len(_ALL_REQUIRED),
            unique=True,
        )
    )

    # Build a complete config dict first
    config = {}
    for field_name in _ALL_REQUIRED:
        config[field_name] = draw(_VALID_FIELD_VALUES[field_name])

    # Remove the selected fields
    for field_name in fields_to_remove:
        del config[field_name]

    # Generate a provider name
    provider_name = draw(
        st.text(min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz_0123456789")
    )

    return provider_name, config, set(fields_to_remove)


def _write_providers_toml(config_dir: Path, provider_name: str, provider_entry: dict) -> None:
    """Write a providers.toml file with a single provider entry."""
    lines = [
        '[default]',
        f'provider = "{provider_name}"',
        '',
        f'[providers.{provider_name}]',
    ]
    for key, value in provider_entry.items():
        if isinstance(value, bool):
            lines.append(f'{key} = {str(value).lower()}')
        elif isinstance(value, int):
            lines.append(f'{key} = {value}')
        elif isinstance(value, str):
            # Escape backslashes and quotes for TOML
            escaped = value.replace('\\', '\\\\').replace('"', '\\"')
            lines.append(f'{key} = "{escaped}"')
        else:
            lines.append(f'{key} = "{value}"')

    toml_content = '\n'.join(lines) + '\n'
    providers_path = config_dir / "providers.toml"
    providers_path.write_text(toml_content)


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------


class TestProperty10ProviderRegistryRejectsInvalidConfig:
    """Property 10: Provider Registry Rejects Invalid Configuration.

    For any provider configuration entry missing one or more required fields,
    the Provider_Registry SHALL refuse to load that provider and emit an error
    identifying the missing fields.

    **Validates: Requirements 1.1, 1.2**
    """

    @given(data=provider_config_with_missing_fields())
    @settings(max_examples=100, deadline=None)
    def test_missing_required_fields_raises_config_error(self, data):
        """Verify that load_providers_config raises ConfigError when required fields are missing."""
        provider_name, config_entry, missing_fields = data

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            _write_providers_toml(config_dir, provider_name, config_entry)

            # load_providers_config should raise ConfigError
            with pytest.raises(ConfigError) as exc_info:
                load_providers_config(config_dir)

            error_message = str(exc_info.value)

            # Verify the error identifies the provider name
            assert provider_name in error_message, (
                f"Error message should identify provider '{provider_name}', "
                f"got: {error_message}"
            )

            # Verify the error identifies each missing field
            for field_name in missing_fields:
                assert field_name in error_message, (
                    f"Error message should identify missing field '{field_name}', "
                    f"got: {error_message}"
                )
