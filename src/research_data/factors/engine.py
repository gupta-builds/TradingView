"""FactorEngine — deterministic universe scoring into ScorePackets.

Reads prices exclusively through ``PriceReadAPI`` (require_usable=True),
takes fundamentals as explicit inputs (no fetching here), computes each
factor with its documented formula, and stamps quality + provenance on the
result. No LLM calls, no fabricated values: what cannot be computed is
reported as INSUFFICIENT_DATA.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from research_data.factors import momentum as momentum_mod
from research_data.factors import safety as safety_mod
from research_data.factors.etf_baseline import compare_to_benchmark
from research_data.factors.packets import (
    EtfBaselineComparison,
    MomentumScore,
    PacketDataQuality,
    PacketProvenance,
    QualityFCFComponents,
    QualityFCFScore,
    SafetyScore,
    ScorePacket,
    ScoreStatus,
    TAContext,
    ValuationContext,
)
from research_data.factors.quality_fcf import (
    FundamentalInputs,
    composite_scores,
    derive_metrics,
)
from research_data.factors.ranking import ascending_ranks, inverse_ranks
from research_data.factors.ta_context import build_ta_context
from research_data.models import OHLCVRecord, QualityStatus
from research_data.read_api import PriceReadAPI

#: Calendar days of history requested to cover 253 trading sessions comfortably.
HISTORY_CALENDAR_DAYS = 550

#: Sessions needed for full momentum/safety windows.
FULL_WINDOW_SESSIONS = 253

#: Last price older than this many calendar days before as_of → STALE.
STALE_CALENDAR_DAYS = 5


class FactorEngine:
    """Computes ScorePackets for a universe as of a date."""

    def __init__(
        self,
        price_api: PriceReadAPI,
        benchmark_symbol: str = "VOO",
        price_source: str | None = None,
    ) -> None:
        self._price_api = price_api
        self._benchmark_symbol = benchmark_symbol
        self._price_source = price_source

    def compute_packets(
        self,
        symbols: list[str],
        as_of: date,
        fundamentals: dict[str, FundamentalInputs] | None = None,
        start: date | None = None,
    ) -> list[ScorePacket]:
        """Score every symbol in ``symbols`` as of ``as_of``.

        ``fundamentals`` maps symbol → FundamentalInputs for equities that
        have statement data; symbols absent from the map (including all ETFs)
        get INSUFFICIENT_DATA quality/valuation scores.
        """
        fundamentals = fundamentals or {}
        start = start or (as_of - timedelta(days=HISTORY_CALENDAR_DAYS))

        query_symbols = list(symbols)
        if self._benchmark_symbol not in query_symbols:
            query_symbols.append(self._benchmark_symbol)

        records = self._price_api.get_price_frame(
            symbols=query_symbols,
            start=start,
            end=as_of,
            source=self._price_source,
            require_usable=True,
        )
        by_symbol: dict[str, list[OHLCVRecord]] = {s: [] for s in query_symbols}
        for record in records:
            by_symbol[record.symbol].append(record)

        series: dict[str, list[tuple[date, float]]] = {}
        price_fields: dict[str, str] = {}
        for symbol, recs in by_symbol.items():
            use_adjusted = bool(recs) and all(r.adjusted_close is not None for r in recs)
            price_fields[symbol] = "adjusted_close" if use_adjusted else "close"
            series[symbol] = [
                (r.trading_date, r.adjusted_close if use_adjusted else r.close)
                for r in recs
            ]

        # Cross-sectional signals over the requested universe only.
        momentum_returns = {
            s: momentum_mod.twelve_minus_one_return([p for _, p in series[s]])
            for s in symbols
        }
        momentum_ranks = ascending_ranks(momentum_returns)
        momentum_ranked_count = sum(1 for r in momentum_ranks.values() if r is not None)

        vols = {
            s: safety_mod.realized_volatility_annualized([p for _, p in series[s]])
            for s in symbols
        }
        safety_ranks = inverse_ranks(vols)
        safety_ranked_count = sum(1 for r in safety_ranks.values() if r is not None)

        metrics = {}
        for symbol in symbols:
            inputs = fundamentals.get(symbol)
            if inputs is None:
                continue
            last_price = series[symbol][-1][1] if series[symbol] else None
            metrics[symbol] = derive_metrics(inputs, last_price)
        quality_values = composite_scores(metrics) if metrics else {}
        quality_ranked_count = sum(1 for v in quality_values.values() if v is not None)

        benchmark_series = series.get(self._benchmark_symbol, [])
        generated_at = datetime.now(timezone.utc)

        return [
            self._build_packet(
                symbol=symbol,
                as_of=as_of,
                universe=list(symbols),
                records=by_symbol[symbol],
                series=series[symbol],
                price_field=price_fields[symbol],
                momentum_return=momentum_returns[symbol],
                momentum_rank=momentum_ranks[symbol],
                momentum_ranked_count=momentum_ranked_count,
                vol=vols[symbol],
                safety_rank=safety_ranks[symbol],
                safety_ranked_count=safety_ranked_count,
                quality_value=quality_values.get(symbol),
                quality_ranked_count=quality_ranked_count,
                quality_metrics=metrics.get(symbol),
                benchmark_series=benchmark_series,
                generated_at=generated_at,
            )
            for symbol in symbols
        ]

    # -- per-symbol assembly ---------------------------------------------------

    def _build_packet(
        self,
        *,
        symbol: str,
        as_of: date,
        universe: list[str],
        records: list[OHLCVRecord],
        series: list[tuple[date, float]],
        price_field: str,
        momentum_return: float | None,
        momentum_rank: int | None,
        momentum_ranked_count: int,
        vol: float | None,
        safety_rank: int | None,
        safety_ranked_count: int,
        quality_value: float | None,
        quality_ranked_count: int,
        quality_metrics,
        benchmark_series: list[tuple[date, float]],
        generated_at: datetime,
    ) -> ScorePacket:
        closes = [p for _, p in series]
        dates = [d for d, _ in series]
        universe_size = len(universe)
        is_etf = bool(records) and records[0].asset_type == "etf"

        window = momentum_mod.momentum_window(dates)
        momentum_score = MomentumScore(
            status=ScoreStatus.OK if momentum_rank is not None else ScoreStatus.INSUFFICIENT_DATA,
            rank=momentum_rank,
            universe_size=universe_size,
            ranked_count=momentum_ranked_count,
            twelve_minus_one_return=momentum_return,
            window_start=window[0] if window else None,
            window_end=window[1] if window else None,
            price_field=price_field,
            context=(
                f"Ranks {momentum_rank} of {momentum_ranked_count} rankable symbols "
                f"on 12-1 month total return."
                if momentum_rank is not None
                else "Insufficient history for the 12-1 month window (needs 253 sessions)."
            ),
        )

        safety_score = SafetyScore(
            status=ScoreStatus.OK if safety_rank is not None else ScoreStatus.INSUFFICIENT_DATA,
            rank=safety_rank,
            universe_size=universe_size,
            ranked_count=safety_ranked_count,
            realized_vol_annualized=vol,
            window_start=dates[-safety_mod.MIN_SESSIONS] if len(dates) >= safety_mod.MIN_SESSIONS else None,
            window_end=dates[-1] if dates else None,
            context=(
                f"Ranks {safety_rank} of {safety_ranked_count} on inverse 12m realized "
                f"volatility (higher rank = lower volatility)."
                if safety_rank is not None
                else "Insufficient history for the 252-session volatility window."
            ),
        )

        if quality_metrics is not None:
            components = QualityFCFComponents(
                fcf_ev=quality_metrics.fcf_ev,
                fcf_margin=quality_metrics.fcf_margin,
                op_margin_stability=quality_metrics.op_margin_stability,
                debt_to_equity=quality_metrics.debt_to_equity,
                enterprise_value=quality_metrics.enterprise_value,
                market_cap=quality_metrics.market_cap,
                fundamentals_as_of=quality_metrics.fundamentals_as_of,
                fundamentals_source=quality_metrics.fundamentals_source,
            )
        else:
            components = QualityFCFComponents()

        quality_score = QualityFCFScore(
            status=ScoreStatus.OK if quality_value is not None else ScoreStatus.INSUFFICIENT_DATA,
            value=quality_value,
            universe_size=universe_size,
            ranked_count=quality_ranked_count,
            components=components,
            context=(
                "Weighted rank composite of FCF/EV, FCF margin, margin stability, leverage."
                if quality_value is not None
                else (
                    "ETF: issuer fundamentals not applicable."
                    if is_etf
                    else "No fundamentals available; composite not computed."
                )
            ),
        )

        p_fcf = None
        fcf_ev = quality_metrics.fcf_ev if quality_metrics else None
        if (
            quality_metrics is not None
            and quality_metrics.market_cap
            and quality_metrics.fcf_ev is not None
            and quality_metrics.enterprise_value
        ):
            fcf = quality_metrics.fcf_ev * quality_metrics.enterprise_value
            if fcf > 0:
                p_fcf = quality_metrics.market_cap / fcf
        valuation = ValuationContext(
            status=ScoreStatus.OK if fcf_ev is not None else ScoreStatus.INSUFFICIENT_DATA,
            fcf_ev=fcf_ev,
            p_fcf=p_fcf,
            sector_note=(
                "ETF — valuation applies to holdings, not the fund wrapper."
                if is_etf
                else "Raw P/E is not comparable across sectors; FCF/EV is primary."
            ),
            caveats=(
                []
                if fcf_ev is not None
                else ["FCF/EV unavailable — valuation context not computed."]
            ),
        )

        if symbol == self._benchmark_symbol:
            etf_baseline = EtfBaselineComparison(
                status=ScoreStatus.OK,
                benchmark_symbol=self._benchmark_symbol,
                windows=[],
                context="This symbol is the benchmark.",
            )
        else:
            comparisons = compare_to_benchmark(series, benchmark_series)
            etf_baseline = EtfBaselineComparison(
                status=ScoreStatus.OK if comparisons else ScoreStatus.INSUFFICIENT_DATA,
                benchmark_symbol=self._benchmark_symbol,
                windows=comparisons,
                context=(
                    "Total return vs benchmark over overlapping usable sessions."
                    if comparisons
                    else "Insufficient overlapping sessions with the benchmark."
                ),
            )

        ta = build_ta_context(closes) if closes else TAContext()

        data_quality = self._derive_data_quality(records, dates, as_of)

        risk_flags: list[str] = []
        if vol is not None and vol > safety_mod.HIGH_VOL_FLAG_THRESHOLD:
            risk_flags.append(
                f"12m realized volatility {vol:.2f} exceeds {safety_mod.HIGH_VOL_FLAG_THRESHOLD:.2f} —"
                " risk is elevated regardless of trend."
            )
        if (
            safety_rank is not None
            and safety_ranked_count >= 6
            and safety_rank <= max(2, safety_ranked_count // 5)
        ):
            risk_flags.append(
                f"safety_score rank {safety_rank} of {safety_ranked_count}: among the most volatile in the universe."
            )
        if not is_etf and quality_value is None:
            risk_flags.append("No fundamentals coverage — quality/valuation unassessed.")
        if data_quality.status != QualityStatus.USABLE:
            risk_flags.append(
                f"Data quality {data_quality.status.value}: confidence capped at {data_quality.max_confidence:.1f}."
            )

        provenance = PacketProvenance(
            price_source=records[0].source if records else None,
            price_field=price_field,
            first_price_date=dates[0] if dates else None,
            last_price_date=dates[-1] if dates else None,
            fundamentals_source=(
                quality_metrics.fundamentals_source if quality_metrics else None
            ),
            generated_at=generated_at,
        )

        return ScorePacket(
            symbol=symbol,
            as_of=as_of,
            universe=universe,
            momentum_score=momentum_score,
            safety_score=safety_score,
            quality_fcf_score=quality_score,
            valuation=valuation,
            etf_baseline=etf_baseline,
            ta_context=ta,
            risk_flags=risk_flags,
            data_quality=data_quality,
            provenance=provenance,
        )

    def _derive_data_quality(
        self, records: list[OHLCVRecord], dates: list[date], as_of: date
    ) -> PacketDataQuality:
        """Quality status for the packet, consistent with quality.py precedence.

        MISSING > STALE > INSUFFICIENT_DATA > PARTIAL > USABLE (CONTRADICTORY
        cannot occur here: require_usable filtering upstream excludes it).
        """
        rows = len(records)
        notes: list[str] = []
        if rows == 0:
            return PacketDataQuality(
                status=QualityStatus.MISSING,
                max_confidence=0.0,
                price_rows_used=0,
                notes=["No usable price rows in the requested window."],
            )
        last_date = dates[-1]
        if (as_of - last_date).days > STALE_CALENDAR_DAYS:
            status, cap = QualityStatus.STALE, 0.5
            notes.append(f"Last usable price is {last_date}, as_of is {as_of}.")
        elif rows < 50:
            status, cap = QualityStatus.INSUFFICIENT_DATA, 0.4
            notes.append(f"Only {rows} usable sessions (<50).")
        elif rows < FULL_WINDOW_SESSIONS:
            status, cap = QualityStatus.PARTIAL, 0.7
            notes.append(
                f"{rows} usable sessions — momentum/safety windows need {FULL_WINDOW_SESSIONS}."
            )
        else:
            status, cap = QualityStatus.USABLE, 1.0
        return PacketDataQuality(
            status=status, max_confidence=cap, price_rows_used=rows, notes=notes
        )
