"""CSV fixture provider for deterministic testing without network access.

Loads sample OHLCV data from CSV files in a fixtures directory, conforming
to the PriceProvider protocol. Returns ProviderFetchResult objects identical
in structure to live providers, enabling downstream normalization, validation,
and quality auditing paths to be exercised without any network calls.

Requirements: 15.1, 15.2, 15.5
"""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import date, datetime, timezone
from pathlib import Path

from research_data.config import ProviderConfig
from research_data.models import (
    OHLCVRecord,
    PriceAdjustment,
    ProviderCapabilities,
    ProviderFetchResult,
    QualityStatus,
)


# Default fixtures path relative to project root
_DEFAULT_FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "tests" / "fixtures"


def _parse_adjustment_policy(policy: str) -> PriceAdjustment:
    """Map a provider config adjustment_policy string to PriceAdjustment enum."""
    mapping = {
        "raw": PriceAdjustment.RAW,
        "split_adjusted": PriceAdjustment.SPLIT_ADJUSTED,
        "split_dividend_adjusted": PriceAdjustment.SPLIT_DIVIDEND_ADJUSTED,
    }
    return mapping.get(policy, PriceAdjustment.UNKNOWN)


class CSVFixtureProvider:
    """Provider that loads deterministic sample data from local CSV fixtures.

    Conforms to the PriceProvider protocol. No network calls are made.

    CSV files are expected in the fixtures directory with the naming convention:
        <SYMBOL>.csv (e.g., VOO.csv, SPY.csv, MSFT.csv)

    CSV format columns:
        date,open,high,low,close,volume,adjusted_close

    Records with parsing errors are skipped with a provider warning.
    Records that would fail downstream validation (negative prices, future dates)
    are still included in the result to exercise the validation pipeline.
    """

    def __init__(
        self,
        config: ProviderConfig,
        capabilities: ProviderCapabilities,
        fixtures_dir: Path | None = None,
    ) -> None:
        """Initialize the CSV fixture provider.

        Args:
            config: Provider configuration from providers.toml.
            capabilities: Provider capabilities derived from config.
            fixtures_dir: Path to the fixtures directory. If None, uses
                          the default tests/fixtures/ relative to project root.
        """
        self.capabilities = capabilities
        self._config = config
        self._fixtures_dir = fixtures_dir or _DEFAULT_FIXTURES_DIR
        self._price_adjustment = _parse_adjustment_policy(config.adjustment_policy)

    def fetch_daily_ohlcv(
        self,
        symbol: str,
        start: date,
        end: date,
        adjusted: bool,
    ) -> ProviderFetchResult:
        """Fetch daily OHLCV data for a symbol from local CSV fixtures.

        Args:
            symbol: Ticker symbol (uppercase ASCII, e.g. "VOO").
            start: Start date (inclusive) for the data range.
            end: End date (inclusive) for the data range.
            adjusted: If True, use adjusted prices from the CSV.

        Returns:
            ProviderFetchResult with raw CSV content, content hash,
            parsed OHLCVRecord instances, and metadata.
        """
        retrieved_at = datetime.now(timezone.utc)
        csv_path = self._fixtures_dir / f"{symbol}.csv"

        # Build request metadata (no secrets to redact for CSV fixture)
        request_url = f"file://{csv_path}"
        request_params = {
            "symbol": symbol,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "adjusted": adjusted,
        }

        # If the CSV file doesn't exist, return empty result (no fabrication)
        if not csv_path.exists():
            return ProviderFetchResult(
                symbol=symbol,
                provider="csv_fixture",
                request_url=request_url,
                request_params=request_params,
                retrieved_at=retrieved_at,
                raw_payload="",
                content_hash=hashlib.sha256(b"").hexdigest(),
                records=[],
                provider_warnings=[f"Fixture file not found: {csv_path}"],
                rate_limit_state={"remaining": None, "reset_at": None},
            )

        # Read raw CSV content
        raw_content = csv_path.read_text(encoding="utf-8")
        content_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()

        # Parse CSV into OHLCVRecord instances
        records: list[OHLCVRecord] = []
        warnings: list[str] = []

        reader = csv.DictReader(io.StringIO(raw_content))
        for row_num, row in enumerate(reader, start=2):  # start=2 accounts for header
            try:
                record = self._parse_row(
                    symbol=symbol,
                    row=row,
                    adjusted=adjusted,
                    retrieved_at=retrieved_at,
                    content_hash=content_hash,
                )
            except (ValueError, KeyError, TypeError) as e:
                warnings.append(f"Row {row_num}: parse error - {e}")
                continue

            # Filter by date range
            if record.trading_date < start or record.trading_date > end:
                continue

            records.append(record)

        return ProviderFetchResult(
            symbol=symbol,
            provider="csv_fixture",
            request_url=request_url,
            request_params=request_params,
            retrieved_at=retrieved_at,
            raw_payload=raw_content,
            content_hash=content_hash,
            records=records,
            provider_warnings=warnings,
            rate_limit_state={"remaining": None, "reset_at": None},
        )

    def _parse_row(
        self,
        symbol: str,
        row: dict[str, str],
        adjusted: bool,
        retrieved_at: datetime,
        content_hash: str,
    ) -> OHLCVRecord:
        """Parse a single CSV row into an OHLCVRecord.

        This method intentionally does NOT reject invalid data (e.g., negative
        prices, future dates). Such records are passed through so that the
        downstream Validator can exercise its rejection logic.

        Args:
            symbol: Ticker symbol.
            row: Dictionary from csv.DictReader.
            adjusted: Whether adjusted prices were requested.
            retrieved_at: Timestamp of the fetch operation.
            content_hash: SHA-256 hash of the raw CSV content.

        Returns:
            OHLCVRecord instance (may contain invalid data for validation testing).

        Raises:
            ValueError: If required fields are missing or unparseable.
            KeyError: If required columns are missing from the CSV.
        """
        trading_date = date.fromisoformat(row["date"].strip())

        open_price = float(row["open"].strip())
        high_price = float(row["high"].strip())
        low_price = float(row["low"].strip())
        close_price = float(row["close"].strip())
        volume = int(row["volume"].strip())

        # Parse adjusted_close (may be empty or absent)
        adjusted_close_str = row.get("adjusted_close", "").strip()
        adjusted_close: float | None = None
        if adjusted_close_str:
            adjusted_close = float(adjusted_close_str)

        # Determine asset type from symbol (ETFs vs equities)
        etf_symbols = {"VOO", "VTI", "SPY", "QQQ"}
        asset_type = "etf" if symbol in etf_symbols else "equity"

        return OHLCVRecord(
            symbol=symbol,
            asset_type=asset_type,
            exchange="NYSE" if asset_type == "etf" else "NASDAQ",
            trading_date=trading_date,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            adjusted_close=adjusted_close,
            volume=volume,
            split_factor=1.0,
            dividend_cash=0.0,
            price_adjustment=self._price_adjustment,
            currency="USD",
            source="csv_fixture",
            retrieved_at=retrieved_at,
            data_as_of=trading_date,
            raw_payload_hash=content_hash,
            quality_status=QualityStatus.USABLE,
        )
