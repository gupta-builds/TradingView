"""Orchestration: assemble → (optional LLM) → validate → write (C2).

Happy-path LLM prompts are Fable's job. Cursor ships the E1 fail-closed path
(MISSING/CONTRADICTORY → deterministic INSUFFICIENT_DATA card, zero LLM calls).
"""

from __future__ import annotations

from pathlib import Path

from research_data.agents.assemble import AnalystInputBundle, quality_blocks_llm
from research_data.agents.llm_client import FixtureLLMClient, get_llm_client
from research_data.cards.allowlist import (
    build_allowlist_from_gate_summary,
    build_allowlist_from_score_packet,
    merge_allowlists,
)
from research_data.cards.models import CriticReview, EvidenceCard
from research_data.cards.validators import validate_critic_review, validate_evidence_card
from research_data.cards.writer import write_critic_review, write_evidence_card, write_vault_mirror
from research_data.models import QualityStatus
from research_data.paper.models import ActionLabel


class RunnerError(Exception):
    """Raised when analyze/critique cannot complete."""


def _insufficient_data_card(bundle: AnalystInputBundle) -> EvidenceCard:
    status = bundle.score_packet.data_quality.status
    cap = bundle.score_packet.data_quality.max_confidence
    return EvidenceCard(
        symbol=bundle.symbol,
        as_of=bundle.as_of,
        action=ActionLabel.INSUFFICIENT_DATA,
        confidence=cap,
        summary=(
            f"Analysis blocked: data quality is {status.value}. "
            "No LLM call was made; action is INSUFFICIENT_DATA."
        ),
        evidence=[],
        opposing_evidence=[],
        risks=[f"quality_status={status.value}"],
        invalidation=["Restore USABLE/PARTIAL data before re-running analysis."],
        data_quality_status=status,
        max_confidence=cap,
        source_packet_symbol=bundle.symbol,
        source_packet_as_of=bundle.as_of,
        evidence_ref_keys=sorted(bundle.evidence_ref_keys),
        spec_id=bundle.spec_id,
    )


def run_analyze_symbol(
    bundle: AnalystInputBundle,
    *,
    cards_dir: str | Path,
    vault_mirror_path: str | Path | None = None,
    llm_client: FixtureLLMClient | None = None,
) -> EvidenceCard:
    """Analyze one symbol. Blocks LLM on MISSING/CONTRADICTORY (E1)."""
    cards_dir = Path(cards_dir)

    if quality_blocks_llm(bundle.score_packet.data_quality.status):
        client = llm_client or get_llm_client()
        before = getattr(client, "invocation_count", 0)
        card = _insufficient_data_card(bundle)
        # Assert path did not call LLM
        after = getattr(client, "invocation_count", 0)
        if after != before:
            raise RunnerError("LLM was invoked on blocked quality status")
        allowlist = build_allowlist_from_score_packet(bundle.score_packet)
        validate_evidence_card(card, allowlist, bundle.evidence_ref_keys)
        write_evidence_card(card, cards_dir)
        if vault_mirror_path is not None:
            write_vault_mirror(card, vault_mirror_path)
        return card

    # Happy path — Fable wires prompts; Cursor returns clear error if no fixture card.
    client = llm_client or get_llm_client()
    if not isinstance(client, FixtureLLMClient) or EvidenceCard not in client._canned:
        raise RunnerError(
            "Happy-path analyze-symbol requires Fable LLM client or a "
            "FixtureLLMClient preloaded with an EvidenceCard"
        )
    card = client.complete_structured(
        system="analyst",  # placeholder; Fable replaces
        user=bundle.symbol,
        response_model=EvidenceCard,
    )
    # Enforce cap from ScorePacket (B4)
    card = card.model_copy(
        update={
            "max_confidence": bundle.score_packet.data_quality.max_confidence,
            "data_quality_status": bundle.score_packet.data_quality.status,
            "confidence": min(
                card.confidence,
                bundle.score_packet.data_quality.max_confidence,
            ),
        }
    )
    allowlist = build_allowlist_from_score_packet(bundle.score_packet)
    if bundle.gate_summary is not None:
        allowlist = merge_allowlists(
            allowlist, build_allowlist_from_gate_summary(bundle.gate_summary)
        )
    validate_evidence_card(card, allowlist, bundle.evidence_ref_keys)
    write_evidence_card(card, cards_dir)
    if vault_mirror_path is not None:
        write_vault_mirror(card, vault_mirror_path)
    return card


def run_critique_spec(
    bundle: AnalystInputBundle,
    card: EvidenceCard | None = None,
    *,
    cards_dir: str | Path,
    llm_client: FixtureLLMClient | None = None,
) -> CriticReview:
    """Critic path — requires gate_summary for demo_eligible reviews."""
    if bundle.gate_summary is None and not quality_blocks_llm(
        bundle.score_packet.data_quality.status
    ):
        raise RunnerError("critique-spec requires gate_summary projection on bundle")

    client = llm_client or get_llm_client()
    if quality_blocks_llm(bundle.score_packet.data_quality.status):
        before = getattr(client, "invocation_count", 0)
        review = CriticReview(
            card_id=card.card_id if card else None,
            spec_id=bundle.spec_id,
            suggestion="insufficient_data",
            confidence_delta=0.0,
            rationale="Input quality blocks analysis; no demotion math applied.",
            rejected=False,
        )
        after = getattr(client, "invocation_count", 0)
        if after != before:
            raise RunnerError("LLM was invoked on blocked quality status")
        write_critic_review(review, cards_dir)
        return review

    if not isinstance(client, FixtureLLMClient) or CriticReview not in client._canned:
        raise RunnerError(
            "Happy-path critique-spec requires Fable LLM client or a "
            "FixtureLLMClient preloaded with a CriticReview"
        )
    review = client.complete_structured(
        system="critic",
        user=bundle.spec_id or bundle.symbol,
        response_model=CriticReview,
    )
    allowlist = build_allowlist_from_score_packet(bundle.score_packet)
    if bundle.gate_summary is not None:
        allowlist = merge_allowlists(
            allowlist, build_allowlist_from_gate_summary(bundle.gate_summary)
        )
        review = review.model_copy(
            update={"gate_summary": bundle.gate_summary.model_dump(mode="json")}
        )
    validate_critic_review(review, allowlist)
    write_critic_review(review, cards_dir)
    return review
