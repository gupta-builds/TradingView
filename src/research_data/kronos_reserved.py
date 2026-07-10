"""Kronos foundation model — RESERVED architecture only. No inference.

Kronos (Tsinghua, arXiv 2508.02739, AAAI 2026 — not Amazon Chronos) is a
K-line foundation model that MAY later become one evidence input. This
module reserves the contract it must satisfy; it deliberately imports no
model code and downloads nothing.

Admission gates (both mandatory, per the Kronos deep-dive note 2026-06-25):

1. Input quality must be USABLE — PARTIAL/STALE/worse data is never fed to a
   forecaster; the pipeline surfaces INSUFFICIENT_DATA instead.
2. Validated RankIC on THIS universe must be >= 0.03. Until a validation
   pass produces that number, no Kronos output may appear in evidence, and
   nothing Kronos says may influence promote/demote decisions.

A forecast without ``model_rankic_on_universe`` populated is unrepresentable
by design: untested model predictions cannot surface.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator

from research_data.models import QualityStatus

#: Below this validated RankIC the model adds no signal on our universe.
KRONOS_RANKIC_MIN = 0.03

#: Kronos evidence may only ever be built from USABLE-quality inputs.
KRONOS_REQUIRED_QUALITY = QualityStatus.USABLE

#: Path-spread width (10th–90th pct of forecast return) above which the
#: evidence must carry an explicit high-uncertainty flag.
KRONOS_WIDE_SPREAD_THRESHOLD = 0.05


class KronosForecastEvidence(BaseModel):
    """The ONLY shape Kronos output may take if it is ever integrated.

    A price-path forecast becomes an evidence *claim* with provenance and a
    validated-skill figure — never an action label, never a standalone signal.
    """

    symbol: str
    model_variant: str  # e.g. "kronos_small_zero_shot"
    forecast_horizon_sessions: int = Field(gt=0)
    median_forecast_return: float
    path_spread_p10_p90: float = Field(ge=0.0)
    sample_count: int = Field(gt=1)
    input_quality_status: QualityStatus
    model_rankic_on_universe: float  # REQUIRED — no default, no None
    data_as_of: date
    generated_at: datetime
    caveat: str = (
        "Zero-shot model forecast. Not a directional signal in isolation; "
        "confidence is bounded by validated RankIC on this universe."
    )

    @model_validator(mode="after")
    def validate_admission_gates(self) -> "KronosForecastEvidence":
        if self.input_quality_status != KRONOS_REQUIRED_QUALITY:
            raise ValueError(
                f"Kronos evidence requires USABLE input data, got "
                f"{self.input_quality_status.value} — surface INSUFFICIENT_DATA instead"
            )
        if self.model_rankic_on_universe < KRONOS_RANKIC_MIN:
            raise ValueError(
                f"model_rankic_on_universe {self.model_rankic_on_universe} is below "
                f"the {KRONOS_RANKIC_MIN} admission threshold — this forecast may "
                "not surface as evidence"
            )
        return self

    @property
    def high_uncertainty(self) -> bool:
        return self.path_spread_p10_p90 > KRONOS_WIDE_SPREAD_THRESHOLD

    @property
    def max_confidence(self) -> float:
        """Confidence ceiling: the validated RankIC itself (capped at 1.0),
        halved when the path spread is wide."""
        ceiling = min(self.model_rankic_on_universe, 1.0)
        return ceiling / 2 if self.high_uncertainty else ceiling


def kronos_admission_check(
    quality_status: QualityStatus, validated_rankic: float | None
) -> tuple[bool, str]:
    """Pre-flight check before any future Kronos inference call.

    Returns (allowed, reason). Today nothing calls Kronos; this exists so
    the future integration has exactly one place where the gates live.
    """
    if quality_status != KRONOS_REQUIRED_QUALITY:
        return False, (
            f"input quality is {quality_status.value}; Kronos requires "
            f"{KRONOS_REQUIRED_QUALITY.value}"
        )
    if validated_rankic is None:
        return False, (
            "no RankIC validation pass has been run on this universe; "
            "Kronos may not be used"
        )
    if validated_rankic < KRONOS_RANKIC_MIN:
        return False, (
            f"validated RankIC {validated_rankic} < {KRONOS_RANKIC_MIN}; "
            "Kronos adds no admissible signal on this universe"
        )
    return True, "admission gates satisfied"
