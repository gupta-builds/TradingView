"""Unit tests for the Provider Registry and configuration loading.

Tests cover:
- Valid config loads successfully (using actual config/providers.toml)
- Missing required fields produce specific error messages
- Missing API key exits before network call
- Unknown provider name rejected with available providers listed
- Config file not found raises ConfigError with expected path
- Invalid TOML syntax raises ConfigError with parse failure message

Requirements: 1.1, 1.2, 1.3, 1.4, 1.6, 1.7
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from research_data.config import ConfigError, load_config, load_providers_config, validate_api_key
from research_data.providers.base import ProviderRegistry


# ---------------------------------------------------------------------------
# Test 1: Valid config loads successfully
# ---------------------------------------------------------------------------


class TestValidConfigLoads:
    """Test that the actual config/providers.toml loads without errors."""

    def test_load_config_from_project_root(self) -> None:
        """Valid config loads successfully using the actual config directory."""
        # Use the real config directory at the project root
        config_dir = Path(__file__).resolve().parent.parent / "config"
        assert config_dir.exists(), f"Config dir not found: {config_dir}"

        # Should not raise
        app_config = load_config(config_dir)

        # Verify providers were loaded
        assert len(app_config.providers) > 0
        assert "polygon" in app_config.providers
        assert "csv_fixture" in app_config.providers
        assert app_config.default_provider == "polygon"

    def test_provider_registry_from_config_dir(self) -> None:
        """ProviderRegistry initializes successfully with valid config."""
        config_dir = Path(__file__).resolve().parent.parent / "config"
        registry = ProviderRegistry(config_dir=config_dir)

        providers = registry.list_providers()
        assert "polygon" in providers
        assert "csv_fixture" in providers
        assert registry.default_provider_name == "polygon"

    def test_provider_capabilities_exposed(self) -> None:
        """ProviderRegistry exposes capabilities for registered providers."""
        config_dir = Path(__file__).resolve().parent.parent / "config"
        registry = ProviderRegistry(config_dir=config_dir)

        caps = registry.get_capabilities("polygon")
        assert caps.source_name == "polygon"
        assert caps.supports_daily_ohlcv is True
        assert caps.requires_api_key is True
        assert caps.rate_limit_per_minute == 5

    def test_provider_config_accessible(self) -> None:
        """ProviderRegistry returns provider config for known providers."""
        config_dir = Path(__file__).resolve().parent.parent / "config"
        registry = ProviderRegistry(config_dir=config_dir)

        config = registry.get_provider_config("csv_fixture")
        assert config.source_name == "csv_fixture"
        assert config.requires_api_key is False


# ---------------------------------------------------------------------------
# Test 2: Missing required fields produce specific error messages
# ---------------------------------------------------------------------------


class TestMissingRequiredFields:
    """Test that missing required fields in provider config produce clear errors."""

    def test_missing_single_field(self, tmp_path: Path) -> None:
        """A provider missing one required field produces an error naming that field."""
        providers_toml = tmp_path / "providers.toml"
        providers_toml.write_text(textwrap.dedent("""\
            [default]
            provider = "test_provider"

            [providers.test_provider]
            source_name = "test_provider"
            source_url = "https://example.com"
            license_note = "Test license"
            requires_api_key = false
            rate_limit = 10
            # adjustment_policy is missing
        """))

        # Also need assets.toml for load_config
        assets_toml = tmp_path / "assets.toml"
        assets_toml.write_text(textwrap.dedent("""\
            [universe]
            name = "test"
            description = "Test universe"
            symbols = ["AAPL"]

            [benchmarks]
            default = "VOO"

            [assets.AAPL]
            symbol = "AAPL"
            asset_type = "equity"
            name = "Apple Inc"
            exchange = "NASDAQ"
        """))

        with pytest.raises(ConfigError) as exc_info:
            load_providers_config(tmp_path)

        error_msg = str(exc_info.value)
        assert "test_provider" in error_msg
        assert "adjustment_policy" in error_msg

    def test_missing_multiple_fields(self, tmp_path: Path) -> None:
        """A provider missing multiple required fields lists all missing fields."""
        providers_toml = tmp_path / "providers.toml"
        providers_toml.write_text(textwrap.dedent("""\
            [default]
            provider = "incomplete"

            [providers.incomplete]
            source_name = "incomplete"
            # Missing: source_url, license_note, requires_api_key, rate_limit, adjustment_policy
        """))

        with pytest.raises(ConfigError) as exc_info:
            load_providers_config(tmp_path)

        error_msg = str(exc_info.value)
        assert "incomplete" in error_msg
        assert "source_url" in error_msg
        assert "license_note" in error_msg
        assert "requires_api_key" in error_msg
        assert "rate_limit" in error_msg
        assert "adjustment_policy" in error_msg

    def test_missing_fields_error_identifies_provider_name(self, tmp_path: Path) -> None:
        """Error message identifies the provider name with missing fields."""
        providers_toml = tmp_path / "providers.toml"
        providers_toml.write_text(textwrap.dedent("""\
            [default]
            provider = "good_provider"

            [providers.good_provider]
            source_name = "good_provider"
            source_url = "https://good.example.com"
            license_note = "Good license"
            requires_api_key = false
            rate_limit = 10
            adjustment_policy = "raw"

            [providers.bad_provider]
            source_name = "bad_provider"
            # Missing all other required fields
        """))

        with pytest.raises(ConfigError) as exc_info:
            load_providers_config(tmp_path)

        error_msg = str(exc_info.value)
        assert "bad_provider" in error_msg
        # The good provider should not appear in the error
        assert "good_provider" not in error_msg or "validation failed" in error_msg


# ---------------------------------------------------------------------------
# Test 3: Missing API key exits before network call
# ---------------------------------------------------------------------------


class TestMissingApiKey:
    """Test that missing API key raises ConfigError before any network call."""

    def test_missing_api_key_raises_config_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Provider requiring API key raises ConfigError when env var is not set."""
        # Ensure the env var is not set
        monkeypatch.delenv("POLYGON_API_KEY", raising=False)

        config_dir = Path(__file__).resolve().parent.parent / "config"
        registry = ProviderRegistry(config_dir=config_dir)

        with pytest.raises(ConfigError) as exc_info:
            registry.get_provider("polygon")

        error_msg = str(exc_info.value)
        assert "POLYGON_API_KEY" in error_msg
        assert "polygon" in error_msg

    def test_missing_api_key_error_includes_env_var_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Error message includes the expected environment variable name."""
        monkeypatch.delenv("TIINGO_API_KEY", raising=False)

        config_dir = Path(__file__).resolve().parent.parent / "config"
        registry = ProviderRegistry(config_dir=config_dir)

        with pytest.raises(ConfigError) as exc_info:
            registry.get_provider("tiingo")

        error_msg = str(exc_info.value)
        assert "TIINGO_API_KEY" in error_msg
        assert "tiingo" in error_msg

    def test_provider_not_requiring_key_succeeds(self) -> None:
        """Provider that doesn't require API key doesn't raise on get_provider."""
        config_dir = Path(__file__).resolve().parent.parent / "config"
        registry = ProviderRegistry(config_dir=config_dir)

        # csv_fixture doesn't require an API key - should not raise ConfigError
        # (may raise ImportError if csv_fixture module isn't implemented yet,
        # but should NOT raise ConfigError about API keys)
        try:
            registry.get_provider("csv_fixture")
        except ConfigError as e:
            # Should not be an API key error
            assert "API key" not in str(e) and "api_key" not in str(e).lower()

    def test_validate_api_key_directly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """validate_api_key raises ConfigError for missing env var."""
        from research_data.config import ProviderConfig

        monkeypatch.delenv("MY_TEST_KEY", raising=False)

        config = ProviderConfig(
            source_name="test_provider",
            source_url="https://example.com",
            license_note="Test",
            requires_api_key=True,
            rate_limit=10,
            adjustment_policy="raw",
            api_key_env_var="MY_TEST_KEY",
        )

        with pytest.raises(ConfigError) as exc_info:
            validate_api_key(config)

        assert "MY_TEST_KEY" in str(exc_info.value)
        assert "test_provider" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Test 4: Unknown provider name rejected with available providers listed
# ---------------------------------------------------------------------------


class TestUnknownProviderRejected:
    """Test that unknown provider names are rejected with helpful error messages."""

    def test_unknown_provider_raises_config_error(self) -> None:
        """Requesting an unknown provider raises ConfigError."""
        config_dir = Path(__file__).resolve().parent.parent / "config"
        registry = ProviderRegistry(config_dir=config_dir)

        with pytest.raises(ConfigError) as exc_info:
            registry.get_provider("nonexistent_provider")

        error_msg = str(exc_info.value)
        assert "nonexistent_provider" in error_msg

    def test_unknown_provider_lists_available_providers(self) -> None:
        """Error for unknown provider lists all registered provider names."""
        config_dir = Path(__file__).resolve().parent.parent / "config"
        registry = ProviderRegistry(config_dir=config_dir)

        with pytest.raises(ConfigError) as exc_info:
            registry.get_provider("fake_provider")

        error_msg = str(exc_info.value)
        # Should list available providers
        assert "polygon" in error_msg
        assert "csv_fixture" in error_msg

    def test_unknown_provider_get_capabilities(self) -> None:
        """get_capabilities also rejects unknown provider names."""
        config_dir = Path(__file__).resolve().parent.parent / "config"
        registry = ProviderRegistry(config_dir=config_dir)

        with pytest.raises(ConfigError) as exc_info:
            registry.get_capabilities("unknown_source")

        error_msg = str(exc_info.value)
        assert "unknown_source" in error_msg
        assert "polygon" in error_msg

    def test_unknown_provider_get_config(self) -> None:
        """get_provider_config also rejects unknown provider names."""
        config_dir = Path(__file__).resolve().parent.parent / "config"
        registry = ProviderRegistry(config_dir=config_dir)

        with pytest.raises(ConfigError) as exc_info:
            registry.get_provider_config("no_such_provider")

        error_msg = str(exc_info.value)
        assert "no_such_provider" in error_msg


# ---------------------------------------------------------------------------
# Test 5: Config file not found raises ConfigError with expected path
# ---------------------------------------------------------------------------


class TestConfigFileNotFound:
    """Test that missing config files produce clear error messages."""

    def test_missing_providers_toml(self, tmp_path: Path) -> None:
        """Missing providers.toml raises ConfigError with the expected path."""
        # Create only assets.toml, not providers.toml
        assets_toml = tmp_path / "assets.toml"
        assets_toml.write_text(textwrap.dedent("""\
            [universe]
            name = "test"
            description = "Test"
            symbols = ["AAPL"]

            [benchmarks]
            default = "VOO"

            [assets.AAPL]
            symbol = "AAPL"
            asset_type = "equity"
            name = "Apple"
            exchange = "NASDAQ"
        """))

        with pytest.raises(ConfigError) as exc_info:
            load_providers_config(tmp_path)

        error_msg = str(exc_info.value)
        assert "providers.toml" in error_msg

    def test_missing_config_dir_for_registry(self, tmp_path: Path) -> None:
        """ProviderRegistry raises ConfigError when config dir doesn't have providers.toml."""
        # Empty directory - no config files
        empty_dir = tmp_path / "empty_config"
        empty_dir.mkdir()

        with pytest.raises(ConfigError):
            ProviderRegistry(config_dir=empty_dir)


# ---------------------------------------------------------------------------
# Test 6: Invalid TOML syntax raises ConfigError with parse failure message
# ---------------------------------------------------------------------------


class TestInvalidTomlSyntax:
    """Test that invalid TOML syntax produces clear parse error messages."""

    def test_invalid_toml_raises_config_error(self, tmp_path: Path) -> None:
        """Invalid TOML syntax raises ConfigError mentioning parse failure."""
        providers_toml = tmp_path / "providers.toml"
        providers_toml.write_text("this is not valid [[[toml syntax ===")

        with pytest.raises(ConfigError) as exc_info:
            load_providers_config(tmp_path)

        error_msg = str(exc_info.value)
        assert "providers.toml" in error_msg
        # Should indicate a parse/syntax issue
        assert "TOML" in error_msg or "syntax" in error_msg.lower() or "parse" in error_msg.lower()

    def test_invalid_toml_with_unclosed_bracket(self, tmp_path: Path) -> None:
        """Unclosed bracket in TOML raises ConfigError."""
        providers_toml = tmp_path / "providers.toml"
        providers_toml.write_text(textwrap.dedent("""\
            [default
            provider = "polygon"
        """))

        with pytest.raises(ConfigError) as exc_info:
            load_providers_config(tmp_path)

        error_msg = str(exc_info.value)
        assert "TOML" in error_msg or "syntax" in error_msg.lower()

    def test_invalid_toml_with_bad_value(self, tmp_path: Path) -> None:
        """TOML with invalid value type raises ConfigError."""
        providers_toml = tmp_path / "providers.toml"
        providers_toml.write_text(textwrap.dedent("""\
            [default]
            provider = "test"

            [providers.test]
            source_name = "test"
            source_url = "https://example.com"
            license_note = "Test"
            requires_api_key = not_a_boolean
            rate_limit = 10
            adjustment_policy = "raw"
        """))

        with pytest.raises(ConfigError) as exc_info:
            load_providers_config(tmp_path)

        error_msg = str(exc_info.value)
        assert "TOML" in error_msg or "syntax" in error_msg.lower() or "Invalid" in error_msg
