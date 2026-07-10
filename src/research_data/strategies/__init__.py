"""Production strategy packs — deterministic hooks for approved specs.

Each module here implements one strategy spec's ``hook_ref``: a deterministic
function that turns stored prices (+ fundamentals) into a StrategyReturns
series for the four-gate harness. Strategies live outside ``factors/`` so the
factor scorers stay pure, and outside the ingestion spine entirely.
"""

from research_data.strategies.quality_momentum import (
    QualityMomentumStudy,
    RebalanceRecord,
    quality_momentum_tilt_hook,
    run_quality_momentum_study,
)

__all__ = [
    "QualityMomentumStudy",
    "RebalanceRecord",
    "quality_momentum_tilt_hook",
    "run_quality_momentum_study",
]
