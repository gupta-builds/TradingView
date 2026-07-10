"""Kronos reservation tests: gates hold, no inference code exists."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from research_data.kronos_reserved import (
    KRONOS_RANKIC_MIN,
    KronosForecastEvidence,
    kronos_admission_check,
)
from research_data.models import QualityStatus


def make_evidence(**overrides) -> KronosForecastEvidence:
    defaults = dict(
        symbol="MSFT",
        model_variant="kronos_small_zero_shot",
        forecast_horizon_sessions=20,
        median_forecast_return=0.023,
        path_spread_p10_p90=0.079,
        sample_count=20,
        input_quality_status=QualityStatus.USABLE,
        model_rankic_on_universe=0.07,
        data_as_of=date(2026, 6, 25),
        generated_at=datetime(2026, 6, 25, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return KronosForecastEvidence(**defaults)


def test_evidence_requires_usable_quality() -> None:
    with pytest.raises(ValueError, match="USABLE"):
        make_evidence(input_quality_status=QualityStatus.PARTIAL)


def test_evidence_requires_validated_rankic_above_threshold() -> None:
    with pytest.raises(ValueError, match="admission threshold"):
        make_evidence(model_rankic_on_universe=0.02)
    assert KRONOS_RANKIC_MIN == 0.03


def test_wide_spread_halves_confidence_ceiling() -> None:
    wide = make_evidence()
    assert wide.high_uncertainty is True
    assert wide.max_confidence == pytest.approx(0.07 / 2)
    narrow = make_evidence(path_spread_p10_p90=0.02)
    assert narrow.high_uncertainty is False
    assert narrow.max_confidence == pytest.approx(0.07)


def test_admission_check_fails_closed() -> None:
    allowed, reason = kronos_admission_check(QualityStatus.STALE, 0.10)
    assert allowed is False and "stale" in reason
    allowed, reason = kronos_admission_check(QualityStatus.USABLE, None)
    assert allowed is False and "validation" in reason
    allowed, reason = kronos_admission_check(QualityStatus.USABLE, 0.01)
    assert allowed is False
    allowed, _ = kronos_admission_check(QualityStatus.USABLE, 0.05)
    assert allowed is True


def test_no_inference_dependencies_reserved_module() -> None:
    """The reservation must not import torch/transformers/huggingface/etc."""
    import research_data.kronos_reserved as module

    source = open(module.__file__).read().lower()
    for banned in ("torch", "transformers", "huggingface", "from_pretrained", "onnx"):
        assert banned not in source
