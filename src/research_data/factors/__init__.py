"""Factor engine — deterministic, documented, killable math.

Primary signals (evidence-backed): momentum 12-1 rank, safety (inverse vol)
rank, quality/FCF composite, valuation FCF/EV, ETF baseline vs VOO.
TA (MA/RSI/Bollinger) is descriptive context only.

Every score carries its formula inputs, window, and status; anything that
cannot be computed from real data is INSUFFICIENT_DATA, never a guess.
"""

from research_data.factors.engine import FactorEngine
from research_data.factors.packets import (
    EtfBaselineComparison,
    MomentumScore,
    PacketDataQuality,
    PacketProvenance,
    QualityFCFScore,
    SafetyScore,
    ScorePacket,
    ScoreStatus,
    TAContext,
    ValuationContext,
)
from research_data.factors.quality_fcf import FundamentalInputs

__all__ = [
    "EtfBaselineComparison",
    "FactorEngine",
    "FundamentalInputs",
    "MomentumScore",
    "PacketDataQuality",
    "PacketProvenance",
    "QualityFCFScore",
    "SafetyScore",
    "ScorePacket",
    "ScoreStatus",
    "TAContext",
    "ValuationContext",
]
