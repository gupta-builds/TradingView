"""Property 20+ — AI hub card allowlist and fail-closed runner (Phase 3).

Extends the hypothesis property series; not a one-off golden suite.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from research_data.agents.assemble import assemble_symbol_input, quality_blocks_llm
from research_data.agents.llm_client import FixtureLLMClient
from research_data.agents.runner import run_analyze_symbol
from research_data.cards.allowlist import (
    FLOAT_DISPLAY_DECIMALS,
    NumericAllowlist,
    build_allowlist_from_score_packet,
)
from research_data.cards.models import EvidenceCard, EvidencePoint
from research_data.cards.validators import CardValidationError, validate_evidence_card
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
from research_data.models import QualityStatus
from research_data.paper.models import ActionLabel


def _packet(
    *,
    status: QualityStatus = QualityStatus.USABLE,
    max_confidence: float = 1.0,
    ret: float = 0.142876581,
) -> ScorePacket:
    return ScorePacket(
        symbol="NVDA",
        as_of=date(2026, 7, 10),
        universe=["NVDA"],
        momentum_score=MomentumScore(
            status=ScoreStatus.OK,
            rank=1,
            universe_size=10,
            ranked_count=9,
            twelve_minus_one_return=ret,
        ),
        safety_score=SafetyScore(
            status=ScoreStatus.INSUFFICIENT_DATA, universe_size=10
        ),
        quality_fcf_score=QualityFCFScore(
            status=ScoreStatus.INSUFFICIENT_DATA, universe_size=10
        ),
        valuation=ValuationContext(status=ScoreStatus.INSUFFICIENT_DATA),
        etf_baseline=EtfBaselineComparison(
            status=ScoreStatus.INSUFFICIENT_DATA, benchmark_symbol="VOO"
        ),
        ta_context=TAContext(),
        data_quality=PacketDataQuality(
            status=status, max_confidence=max_confidence, price_rows_used=100
        ),
        provenance=PacketProvenance(generated_at=datetime(2026, 7, 10, tzinfo=timezone.utc)),
    )


@given(st.floats(min_value=-2.0, max_value=2.0, allow_nan=False, allow_infinity=False))
@settings(max_examples=40)
def test_property_20_float_allowlist_rounding_boundary(raw: float) -> None:
    """Property 20: floats match iff equal after FLOAT_DISPLAY_DECIMALS rounding."""
    packet = _packet(ret=raw)
    allowlist = build_allowlist_from_score_packet(packet)
    rounded = round(raw, FLOAT_DISPLAY_DECIMALS)
    assert allowlist.allows_float(rounded)
    # Perturb just outside the rounded bucket when possible
    step = 10 ** (-FLOAT_DISPLAY_DECIMALS)
    outsider = rounded + step
    if round(outsider, FLOAT_DISPLAY_DECIMALS) != rounded:
        assert not allowlist.allows_float(outsider)


def test_property_21_missing_blocks_llm_zero_invocations(tmp_path) -> None:
    """Property 21: MISSING/CONTRADICTORY → INSUFFICIENT_DATA, zero LLM calls."""
    for status, cap in (
        (QualityStatus.MISSING, 0.0),
        (QualityStatus.CONTRADICTORY, 0.3),
    ):
        packet = _packet(status=status, max_confidence=cap)
        assert quality_blocks_llm(status)
        bundle = assemble_symbol_input(score_packet=packet)
        client = FixtureLLMClient()
        card = run_analyze_symbol(bundle, cards_dir=tmp_path, llm_client=client)
        assert client.invocation_count == 0
        assert card.action == ActionLabel.INSUFFICIENT_DATA


def test_property_22_citation_hallucination_rejected() -> None:
    """Property 22: evidence_ref not in assembler input → reject (kronos-style)."""
    packet = _packet()
    allowlist = build_allowlist_from_score_packet(packet)
    card = EvidenceCard(
        symbol="NVDA",
        as_of=date(2026, 7, 10),
        action=ActionLabel.WATCH,
        confidence=0.5,
        summary="Watching without citing a real ref.",
        evidence=[
            EvidencePoint(
                source="prices",
                point="Momentum return mentioned without number.",
                ref_key="ghost-ref-not-in-input",
            )
        ],
        data_quality_status=QualityStatus.USABLE,
        max_confidence=1.0,
        evidence_ref_keys=["ghost-ref-not-in-input"],
    )
    with pytest.raises(CardValidationError, match="not in assembler input"):
        validate_evidence_card(card, allowlist, allowed_ref_keys=set())


@given(st.floats(min_value=-2.0, max_value=2.0, allow_nan=False, allow_infinity=False))
@settings(max_examples=25)
def test_property_23_runner_accepts_display_precision_quotes(raw: float) -> None:
    """Property 23: a card quoting any packet float at display precision (4dp)
    always survives the full runner validate path, end to end."""
    import tempfile

    from research_data.agents.runner import run_analyze_symbol
    from research_data.cards.writer import format_card_float

    packet = _packet(ret=raw)
    card = EvidenceCard(
        symbol="NVDA",
        as_of=date(2026, 7, 10),
        action=ActionLabel.WATCH,
        confidence=0.5,
        summary=f"Twelve-minus-one return of {format_card_float(raw)} leads the pack.",
        data_quality_status=QualityStatus.USABLE,
        max_confidence=1.0,
    )
    bundle = assemble_symbol_input(score_packet=packet)
    client = FixtureLLMClient(canned={EvidenceCard: card})
    with tempfile.TemporaryDirectory() as tmp:
        out = run_analyze_symbol(bundle, cards_dir=tmp, llm_client=client)
    assert client.invocation_count == 1
    assert out.confidence <= out.max_confidence


def test_int_bucket_exact() -> None:
    al = NumericAllowlist()
    al.add_int(9)
    assert al.allows_int(9)
    assert not al.allows_int(10)
