"""research_data - A provider-agnostic market data ingestion and quality auditing system.

This package provides local, timestamped, auditable market-data storage for
research purposes. It fetches daily OHLCV data through a provider-agnostic
architecture, stores raw payloads and normalized records in DuckDB, tracks
complete provenance, and produces data-quality reports.

This is a research and analysis tool only. It does not provide trading signals,
broker integration, or execution capabilities.
"""

__version__ = "0.1.0"
