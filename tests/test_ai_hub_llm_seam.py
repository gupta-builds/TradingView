"""Fixture-mode coverage for the Phase 3 LLM seam (prompts, runner, fail-fast).

Everything here runs offline; no litellm import is triggered because the
LiveLLMClient is only constructed with an injected stub.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from research_data.agents.analyst import (
    ANALYST_SYSTEM_PROMPT,
    build_analyst_user_prompt,
)
from research_data.agents.assemble import assemble_symbol_input
from research_data.agents.critic import CRITIC_SYSTEM_PROMPT, build_critic_user_prompt
from research_data.agents.llm_client import (
    ROUTER_MAX_FAILURES,
    FixtureLLMClient,
    LiveLLMClient,
    LLMClientError,
    get_llm_client,
)
from research_data.agents.runner import run_analyze_symbol, run_critique_spec
from research_data.cards.gate_projection import GateSummaryProjection
from research_data.cards.models import CriticReview, EvidenceCard, EvidencePoint
from research_data.cards.validators import CardValidationError
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

SPEC_ID = "5f003778-42bc-4d8a-ac12-839699d98a02"


def _packet(ret: float = 0.142876581) -> ScorePacket:
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
        safety_score=SafetyScore(status=ScoreStatus.INSUFFICIENT_DATA, universe_size=10),
        quality_fcf_score=QualityFCFScore(
            status=ScoreStatus.INSUFFICIENT_DATA, universe_size=10
        ),
        valuation=ValuationContext(status=ScoreStatus.INSUFFICIENT_DATA),
        etf_baseline=EtfBaselineComparison(
            status=ScoreStatus.INSUFFICIENT_DATA, benchmark_symbol="VOO"
        ),
        ta_context=TAContext(),
        data_quality=PacketDataQuality(
            status=QualityStatus.USABLE, max_confidence=1.0, price_rows_used=100
        ),
        provenance=PacketProvenance(
            generated_at=datetime(2026, 7, 10, tzinfo=timezone.utc)
        ),
    )


def _gate_summary() -> GateSummaryProjection:
    return GateSummaryProjection(
        spec_id=SPEC_ID,
        all_passed=True,
        oos_net_sharpe=1.52,
        mc_p5_return=0.081,
        wf_pct_positive=1.0,
        deflated_sharpe_probability=0.9947,
    )


def _good_card() -> EvidenceCard:
    return EvidenceCard(
        symbol="NVDA",
        as_of=date(2026, 7, 10),
        action=ActionLabel.WATCH,
        confidence=0.6,
        summary="Momentum leadership with a twelve-minus-one return of 0.1429.",
        evidence=[
            EvidencePoint(source="momentum_score", point="Top decile momentum rank.")
        ],
        opposing_evidence=["Safety and quality inputs are unavailable."],
        risks=["Single-factor evidence only."],
        invalidation=["Momentum leadership fades below the universe median."],
        data_quality_status=QualityStatus.USABLE,
        max_confidence=1.0,
    )


# -- prompts -----------------------------------------------------------------


def test_analyst_prompt_is_evidence_bound() -> None:
    bundle = assemble_symbol_input(score_packet=_packet())
    prompt = build_analyst_user_prompt(bundle)
    assert "QUOTABLE_NUMBERS" in prompt
    assert "0.1429" in prompt  # 4dp display of the momentum return
    assert "ALLOWED_EVIDENCE_REF_KEYS" in prompt
    for label in ActionLabel:
        assert label.value in ANALYST_SYSTEM_PROMPT


def test_critic_prompt_requires_gate_summary() -> None:
    bundle = assemble_symbol_input(score_packet=_packet())
    with pytest.raises(ValueError, match="GateSummaryProjection"):
        build_critic_user_prompt(bundle)
    bundle.gate_summary = _gate_summary()
    bundle.spec_id = SPEC_ID
    prompt = build_critic_user_prompt(bundle)
    assert "0.9947" in prompt and "1.5200" in prompt
    assert "hold" in CRITIC_SYSTEM_PROMPT and "demote" in CRITIC_SYSTEM_PROMPT


# -- runner happy path (fixture) ----------------------------------------------


def test_fixture_happy_path_writes_validated_card(tmp_path) -> None:
    bundle = assemble_symbol_input(score_packet=_packet())
    client = FixtureLLMClient(canned={EvidenceCard: _good_card()})
    card = run_analyze_symbol(bundle, cards_dir=tmp_path, llm_client=client)
    assert client.invocation_count == 1
    assert card.action is ActionLabel.WATCH
    assert card.confidence <= card.max_confidence
    written = list(tmp_path.glob("NVDA_*.json"))
    assert len(written) == 1


def test_fixture_card_with_invented_number_fails_closed(tmp_path) -> None:
    bad = _good_card().model_copy(
        update={"summary": "A Sharpe ratio of 3.7 makes this compelling."}
    )
    bundle = assemble_symbol_input(score_packet=_packet())
    client = FixtureLLMClient(canned={EvidenceCard: bad})
    with pytest.raises(CardValidationError, match="not in numeric allowlist"):
        run_analyze_symbol(bundle, cards_dir=tmp_path, llm_client=client)
    assert list(tmp_path.glob("NVDA_*.json")) == []


def test_sentence_ending_integer_lexes_as_float_but_passes(tmp_path) -> None:
    """Live-run regression: 'ranked X.' lexes as float X.0; the allowlisted
    integer must still be accepted (and a non-allowlisted one still rejected)."""
    ok = _good_card().model_copy(
        update={"summary": "Momentum leadership within a rankable field of 9."}
    )
    bundle = assemble_symbol_input(score_packet=_packet())
    client = FixtureLLMClient(canned={EvidenceCard: ok})
    card = run_analyze_symbol(bundle, cards_dir=tmp_path, llm_client=client)
    assert card.action is ActionLabel.WATCH

    bad = _good_card().model_copy(
        update={"summary": "Momentum leadership within a rankable field of 37."}
    )
    client = FixtureLLMClient(canned={EvidenceCard: bad})
    with pytest.raises(CardValidationError, match="not in numeric allowlist"):
        run_analyze_symbol(bundle, cards_dir=tmp_path, llm_client=client)


def test_fixture_critic_path_stamps_provenance(tmp_path) -> None:
    bundle = assemble_symbol_input(score_packet=_packet())
    bundle.gate_summary = _gate_summary()
    bundle.spec_id = SPEC_ID
    canned = CriticReview(
        suggestion="hold",
        confidence_delta=-0.1,
        rationale=(
            "One bull regime; the walk-forward fraction of 1.0000 will not "
            "generalize without more regimes."
        ),
    )
    client = FixtureLLMClient(canned={CriticReview: canned})
    card = _good_card()
    review = run_critique_spec(bundle, card, cards_dir=tmp_path, llm_client=client)
    assert review.spec_id == SPEC_ID
    assert review.card_id == card.card_id
    assert review.gate_summary["oos_net_sharpe"] == 1.52
    assert list(tmp_path.glob("review_*.json"))


def test_fixture_critic_planted_sharpe_fails_closed(tmp_path) -> None:
    bundle = assemble_symbol_input(score_packet=_packet())
    bundle.gate_summary = _gate_summary()
    bundle.spec_id = SPEC_ID
    planted = CriticReview(
        suggestion="ok",
        confidence_delta=0.0,
        rationale="An out-of-sample Sharpe of 9.4321 clears every bar.",
    )
    client = FixtureLLMClient(canned={CriticReview: planted})
    with pytest.raises(CardValidationError, match="not in numeric allowlist"):
        run_critique_spec(bundle, None, cards_dir=tmp_path, llm_client=client)


# -- live client scaffolding (no network, no litellm import) -------------------


def test_live_client_fail_fast_after_max_failures() -> None:
    calls = {"n": 0}

    def boom(**kwargs):
        calls["n"] += 1
        raise RuntimeError("provider down")

    client = LiveLLMClient(structured_create=boom)
    for _ in range(ROUTER_MAX_FAILURES):
        with pytest.raises(LLMClientError, match="live LLM call failed"):
            client.complete_structured(
                system="s", user="u", response_model=EvidenceCard
            )
    with pytest.raises(LLMClientError, match="fail-fast"):
        client.complete_structured(system="s", user="u", response_model=EvidenceCard)
    assert calls["n"] == ROUTER_MAX_FAILURES


def test_live_client_success_resets_failure_counter() -> None:
    card = _good_card()
    state = {"fail": True, "n": 0}

    def flaky(**kwargs):
        state["n"] += 1
        if state["fail"]:
            raise RuntimeError("transient")
        return card

    client = LiveLLMClient(structured_create=flaky)
    with pytest.raises(LLMClientError):
        client.complete_structured(system="s", user="u", response_model=EvidenceCard)
    state["fail"] = False
    got = client.complete_structured(system="s", user="u", response_model=EvidenceCard)
    assert got is card
    state["fail"] = True
    # Counter was reset by the success — the next failure is a fresh strike.
    with pytest.raises(LLMClientError, match="live LLM call failed"):
        client.complete_structured(system="s", user="u", response_model=EvidenceCard)


def test_get_llm_client_defaults_to_fixture(monkeypatch) -> None:
    monkeypatch.delenv("RESEARCH_DATA_LLM", raising=False)
    assert isinstance(get_llm_client(), FixtureLLMClient)
    monkeypatch.setenv("RESEARCH_DATA_LLM", "weird")
    with pytest.raises(LLMClientError):
        get_llm_client()
