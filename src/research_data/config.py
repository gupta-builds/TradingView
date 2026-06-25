"""Configuration loading and validation for research_data.

Loads and validates TOML configuration from config/assets.toml and
config/providers.toml. Ensures all required provider fields are present
and provides typed access to configuration values.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]


# Required fields for each provider entry per Requirement 1.1
REQUIRED_PROVIDER_FIELDS = frozenset(
    {
        "source_name",
        "source_url",
        "license_note",
        "requires_api_key",
        "rate_limit",
        "adjustment_policy",
    }
)


class ConfigError(Exception):
    """Raised when configuration loading or validation fails."""


@dataclass(frozen=True)
class AssetConfig:
    """Configuration for a single asset in the universe."""

    symbol: str
    asset_type: str
    name: str
    exchange: str
    currency: str = "USD"
    benchmark_symbol: str = "VOO"


@dataclass(frozen=True)
class ProviderConfig:
    """Configuration for a single data provider."""

    source_name: str
    source_url: str
    license_note: str
    requires_api_key: bool
    rate_limit: int
    adjustment_policy: str
    api_key_env_var: str | None = None
    supports_daily_ohlcv: bool = False
    supports_adjusted_prices: bool = False
    supports_corporate_actions: bool = False
    min_history_years_free: float | None = None
    experimental: bool = False
    rate_limit_per_minute: int | None = None

    def __post_init__(self) -> None:
        # rate_limit_per_minute defaults to rate_limit if not explicitly set
        if self.rate_limit_per_minute is None:
            object.__setattr__(self, "rate_limit_per_minute", self.rate_limit)


@dataclass(frozen=True)
class UniverseConfig:
    """Configuration for the asset universe."""

    name: str
    description: str
    symbols: list[str]
    default_benchmark: str
    benchmark_mappings: dict[str, str]
    assets: dict[str, AssetConfig]


@dataclass(frozen=True)
class AppConfig:
    """Top-level application configuration."""

    universe: UniverseConfig
    providers: dict[str, ProviderConfig]
    default_provider: str


def _find_config_dir(start_path: Path | None = None) -> Path:
    """Locate the config directory relative to the project root.

    Searches from start_path upward for a directory containing a 'config' folder
    with the expected TOML files. Falls back to looking relative to this file's
    location in the source tree.
    """
    if start_path is None:
        # Default: look relative to this source file (src/research_data/config.py)
        # Project root is two levels up from src/research_data/
        start_path = Path(__file__).resolve().parent.parent.parent

    config_dir = start_path / "config"
    if config_dir.is_dir():
        return config_dir

    # Walk up from CWD as fallback
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        candidate = parent / "config"
        if candidate.is_dir():
            return candidate

    raise ConfigError(
        f"Cannot locate config directory. Searched from: {start_path}"
    )


def _load_toml_file(path: Path) -> dict[str, Any]:
    """Load and parse a TOML file, raising ConfigError on failure."""
    if not path.exists():
        raise ConfigError(
            f"Configuration file not found: {path}. "
            f"Expected file at: {path.resolve()}"
        )
    if not path.is_file():
        raise ConfigError(f"Configuration path is not a file: {path}")
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(
            f"Invalid TOML syntax in {path}: {e}"
        ) from e


def _validate_provider_entry(
    name: str, entry: dict[str, Any]
) -> list[str]:
    """Validate a single provider entry, returning list of missing fields."""
    missing = []
    for field_name in REQUIRED_PROVIDER_FIELDS:
        if field_name not in entry:
            missing.append(field_name)
    return missing


def load_assets_config(config_dir: Path) -> UniverseConfig:
    """Load and validate assets.toml configuration."""
    assets_path = config_dir / "assets.toml"
    data = _load_toml_file(assets_path)

    universe_data = data.get("universe", {})
    benchmarks_data = data.get("benchmarks", {})
    assets_data = data.get("assets", {})

    symbols = universe_data.get("symbols", [])
    default_benchmark = benchmarks_data.get("default", "VOO")
    benchmark_mappings = benchmarks_data.get("mappings", {})

    assets: dict[str, AssetConfig] = {}
    for symbol, asset_info in assets_data.items():
        assets[symbol] = AssetConfig(
            symbol=asset_info["symbol"],
            asset_type=asset_info["asset_type"],
            name=asset_info["name"],
            exchange=asset_info["exchange"],
            currency=asset_info.get("currency", "USD"),
            benchmark_symbol=asset_info.get("benchmark_symbol", default_benchmark),
        )

    return UniverseConfig(
        name=universe_data.get("name", "v1"),
        description=universe_data.get("description", ""),
        symbols=symbols,
        default_benchmark=default_benchmark,
        benchmark_mappings=benchmark_mappings,
        assets=assets,
    )


def load_providers_config(config_dir: Path) -> tuple[dict[str, ProviderConfig], str]:
    """Load and validate providers.toml configuration.

    Returns a tuple of (providers_dict, default_provider_name).
    Raises ConfigError if any provider is missing required fields.
    """
    providers_path = config_dir / "providers.toml"
    data = _load_toml_file(providers_path)

    default_provider = data.get("default", {}).get("provider", "polygon")
    providers_data = data.get("providers", {})

    if not providers_data:
        raise ConfigError(
            "No providers configured in providers.toml. "
            "At least one provider entry is required."
        )

    # Validate all providers and collect errors
    errors: list[str] = []
    providers: dict[str, ProviderConfig] = {}

    for name, entry in providers_data.items():
        missing = _validate_provider_entry(name, entry)
        if missing:
            errors.append(
                f"Provider '{name}' is missing required fields: {', '.join(sorted(missing))}"
            )
            continue

        providers[name] = ProviderConfig(
            source_name=entry["source_name"],
            source_url=entry["source_url"],
            license_note=entry["license_note"],
            requires_api_key=entry["requires_api_key"],
            rate_limit=entry["rate_limit"],
            adjustment_policy=entry["adjustment_policy"],
            api_key_env_var=entry.get("api_key_env_var"),
            supports_daily_ohlcv=entry.get("supports_daily_ohlcv", False),
            supports_adjusted_prices=entry.get("supports_adjusted_prices", False),
            supports_corporate_actions=entry.get("supports_corporate_actions", False),
            min_history_years_free=entry.get("min_history_years_free"),
            experimental=entry.get("experimental", False),
            rate_limit_per_minute=entry.get("rate_limit_per_minute"),
        )

    if errors:
        raise ConfigError(
            "Provider configuration validation failed:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

    if default_provider not in providers:
        available = ", ".join(sorted(providers.keys()))
        raise ConfigError(
            f"Default provider '{default_provider}' is not configured. "
            f"Available providers: {available}"
        )

    return providers, default_provider


def validate_api_key(provider: ProviderConfig) -> None:
    """Validate that the required API key is available in the environment.

    Raises ConfigError if the provider requires an API key but the
    corresponding environment variable is not set.
    """
    if not provider.requires_api_key:
        return

    env_var = provider.api_key_env_var
    if env_var is None:
        raise ConfigError(
            f"Provider '{provider.source_name}' requires an API key but "
            f"no api_key_env_var is configured."
        )

    if not os.environ.get(env_var):
        raise ConfigError(
            f"Required API key environment variable '{env_var}' is not set "
            f"for provider '{provider.source_name}'. "
            f"Please set {env_var} before proceeding."
        )


def load_config(config_dir: Path | None = None) -> AppConfig:
    """Load and validate all configuration files.

    Args:
        config_dir: Path to the config directory. If None, auto-discovers
                    relative to the project root.

    Returns:
        Fully validated AppConfig instance.

    Raises:
        ConfigError: If configuration files are missing, malformed, or invalid.
    """
    if config_dir is None:
        config_dir = _find_config_dir()

    universe = load_assets_config(config_dir)
    providers, default_provider = load_providers_config(config_dir)

    return AppConfig(
        universe=universe,
        providers=providers,
        default_provider=default_provider,
    )
