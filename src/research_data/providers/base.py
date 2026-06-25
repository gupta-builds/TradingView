"""Provider registry and base protocol for market data providers.

Defines the PriceProvider Protocol that all data providers must conform to,
and the ProviderRegistry class that loads configuration, validates providers,
and returns concrete provider instances.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Protocol, runtime_checkable

from research_data.config import (
    AppConfig,
    ConfigError,
    ProviderConfig,
    load_config,
    load_providers_config,
    validate_api_key,
)
from research_data.models import ProviderCapabilities, ProviderFetchResult


@runtime_checkable
class PriceProvider(Protocol):
    """Protocol that all data providers must implement.

    Each provider exposes its capabilities and a method to fetch daily OHLCV
    data for a given symbol and date range.
    """

    capabilities: ProviderCapabilities

    def fetch_daily_ohlcv(
        self,
        symbol: str,
        start: date,
        end: date,
        adjusted: bool,
    ) -> ProviderFetchResult:
        """Fetch daily OHLCV data for a symbol within a date range.

        Args:
            symbol: Ticker symbol (uppercase ASCII, e.g. "AAPL").
            start: Start date (inclusive) for the data range.
            end: End date (inclusive) for the data range.
            adjusted: If True, request split-and-dividend-adjusted prices.

        Returns:
            ProviderFetchResult containing raw payload, parsed records,
            and metadata about the fetch operation.
        """
        ...


class ProviderRegistry:
    """Registry that loads provider configuration and returns concrete provider instances.

    The registry validates provider configuration at construction time,
    checks API key availability before returning providers that require keys,
    and rejects requests for unknown provider names with a clear error.

    Usage:
        registry = ProviderRegistry()  # auto-discovers config
        provider = registry.get_provider("polygon")
        capabilities = registry.get_capabilities("polygon")
        all_names = registry.list_providers()
    """

    def __init__(
        self,
        config: AppConfig | None = None,
        config_dir: Path | None = None,
    ) -> None:
        """Initialize the provider registry.

        Args:
            config: Pre-loaded AppConfig. If provided, config_dir is ignored.
            config_dir: Path to the config directory. If None and config is None,
                        auto-discovers relative to the project root.

        Raises:
            ConfigError: If configuration files are missing, malformed, or invalid.
        """
        if config is not None:
            self._providers = config.providers
            self._default_provider = config.default_provider
        else:
            app_config = load_config(config_dir)
            self._providers = app_config.providers
            self._default_provider = app_config.default_provider

        # Build capabilities map from provider configs
        self._capabilities: dict[str, ProviderCapabilities] = {}
        for name, prov_config in self._providers.items():
            self._capabilities[name] = _build_capabilities(prov_config)

    @property
    def default_provider_name(self) -> str:
        """Return the name of the default provider."""
        return self._default_provider

    def list_providers(self) -> list[str]:
        """Return a sorted list of all registered provider names."""
        return sorted(self._providers.keys())

    def get_provider_config(self, name: str) -> ProviderConfig:
        """Return the configuration for a named provider.

        Args:
            name: Provider name (e.g. "polygon", "csv_fixture").

        Returns:
            ProviderConfig for the requested provider.

        Raises:
            ConfigError: If the provider name is not registered.
        """
        self._validate_provider_name(name)
        return self._providers[name]

    def get_provider(self, name: str | None = None) -> PriceProvider:
        """Return a concrete provider instance by name.

        Validates that the required API key is present in the environment
        before returning providers that require keys. This ensures no
        network calls are attempted without proper credentials.

        Args:
            name: Provider name. If None, uses the default provider.

        Returns:
            A concrete PriceProvider instance.

        Raises:
            ConfigError: If the provider name is unknown, the API key is
                         missing, or the provider implementation is not available.
        """
        if name is None:
            name = self._default_provider

        self._validate_provider_name(name)
        provider_config = self._providers[name]

        # Validate API key presence before any network call (Requirement 1.3)
        validate_api_key(provider_config)

        # Import and instantiate the concrete provider
        return _create_provider_instance(name, provider_config, self._capabilities[name])

    def get_capabilities(self, name: str) -> ProviderCapabilities:
        """Return the capabilities for a named provider.

        Exposes provider capabilities to the Data_Quality_Auditor and other
        components that need to understand provider limitations.

        Args:
            name: Provider name (e.g. "polygon", "csv_fixture").

        Returns:
            ProviderCapabilities for the requested provider.

        Raises:
            ConfigError: If the provider name is not registered.
        """
        self._validate_provider_name(name)
        return self._capabilities[name]

    def _validate_provider_name(self, name: str) -> None:
        """Validate that a provider name is registered.

        Raises:
            ConfigError: If the name is not in the registry, with a message
                         listing all available provider names.
        """
        if name not in self._providers:
            available = ", ".join(self.list_providers())
            raise ConfigError(
                f"Unknown provider '{name}'. "
                f"Registered providers: {available}"
            )


def _build_capabilities(config: ProviderConfig) -> ProviderCapabilities:
    """Build a ProviderCapabilities model from a ProviderConfig."""
    return ProviderCapabilities(
        source_name=config.source_name,
        asset_classes=["equity", "etf"],
        supports_daily_ohlcv=config.supports_daily_ohlcv,
        supports_adjusted_prices=config.supports_adjusted_prices,
        supports_corporate_actions=config.supports_corporate_actions,
        min_history_years_free=config.min_history_years_free,
        rate_limit_per_minute=config.rate_limit_per_minute,
        requires_api_key=config.requires_api_key,
        license_note=config.license_note,
        experimental=config.experimental,
    )


def _create_provider_instance(
    name: str,
    config: ProviderConfig,
    capabilities: ProviderCapabilities,
) -> PriceProvider:
    """Create a concrete provider instance based on the provider name.

    This function lazily imports provider implementations to avoid
    circular imports and unnecessary dependencies.

    Args:
        name: Provider name.
        config: Provider configuration.
        capabilities: Provider capabilities.

    Returns:
        A concrete PriceProvider instance.

    Raises:
        ConfigError: If the provider implementation module is not available.
    """
    try:
        if name == "csv_fixture":
            from research_data.providers.csv_fixture import CSVFixtureProvider
            return CSVFixtureProvider(config=config, capabilities=capabilities)
        elif name == "polygon":
            from research_data.providers.polygon import PolygonProvider
            return PolygonProvider(config=config, capabilities=capabilities)
        elif name == "tiingo":
            from research_data.providers.tiingo import TiingoProvider
            return TiingoProvider(config=config, capabilities=capabilities)
        elif name == "alpha_vantage":
            from research_data.providers.alpha_vantage import AlphaVantageProvider
            return AlphaVantageProvider(config=config, capabilities=capabilities)
        elif name == "fmp":
            from research_data.providers.fmp import FMPProvider
            return FMPProvider(config=config, capabilities=capabilities)
        else:
            raise ConfigError(
                f"No implementation available for provider '{name}'. "
                f"Provider is configured but its implementation module is missing."
            )
    except ImportError as e:
        raise ConfigError(
            f"Cannot load provider '{name}': implementation module not found. "
            f"Error: {e}"
        ) from e
