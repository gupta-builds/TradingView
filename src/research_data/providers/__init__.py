"""Provider registry and base interfaces for market data providers.

This package contains the provider abstraction layer that enables
provider-agnostic data ingestion. The ProviderRegistry loads configuration,
validates provider entries, and returns concrete provider instances.
"""

from research_data.providers.base import PriceProvider, ProviderRegistry

__all__ = ["PriceProvider", "ProviderRegistry"]
