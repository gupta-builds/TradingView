"""Orchestration: assemble → (optional LLM) → validate → write (C2).

Happy path (USABLE/PARTIAL/…): structured LLM behind ``get_llm_client`` with
the evidence-bound prompts from ``analyst``/``critic``. The E1 fail-closed
path is unchanged: MISSING/CONTRADICTORY quality yields a deterministic
INSUFFICIENT_DATA card with zero LLM calls.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from research_data.agents.analyst import ANALYST_SYSTEM_PROMPT, build_analyst_user_prompt
from research_data.agents.assemble import AnalystInputBundle, quality_blocks_llm
from research_data.agents.critic import CRITIC_SYSTEM_PROMPT, build_critic_user_prompt
from research_data.agents.llm_client import FixtureLLMClient, StructuredLLM, get_llm_client
from research_data.cards.allowlist import (
    build_allowlist_from_gate_summary,
    build_allowlist_from_score_packet,
    merge_allowlists,
)
from research_data.cards.models import CriticReview, EvidenceCard
from research_data.cards.validators import (
    CardValidationError,
    validate_critic_review,
    validate_evidence_card,
)
from research_data.cards.writer import write_critic_review, write_evidence_card, write_vault_mirror
from research_data.models import QualityStatus
from research_data.paper.models import ActionLabel


class RunnerError(Exception):
    """Raised when analyze/critique cannot complete."""


def _validation_retry_note(error: CardValidationError) -> str:
    return (
        "\n\nYour previous attempt was REJECTED by the validator with this "
        f"error:\n  {error}\nFix exactly that problem and produce the output "
        "again. Remember: no digits in prose except QUOTABLE_NUMBERS verbatim."
    )


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
    llm_client: StructuredLLM | None = None,
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

    # Happy path — evidence-bound structured LLM (fixture or live).
    client = llm_client or get_llm_client()
    if isinstance(client, FixtureLLMClient) and EvidenceCard not in client._canned:
        raise RunnerError(
            "Happy-path analyze-symbol needs RESEARCH_DATA_LLM=live or a "
            "FixtureLLMClient preloaded with an EvidenceCard"
        )
    allowlist = build_allowlist_from_score_packet(bundle.score_packet)
    if bundle.gate_summary is not None:
        allowlist = merge_allowlists(
            allowlist, build_allowlist_from_gate_summary(bundle.gate_summary)
        )
    user_prompt = build_analyst_user_prompt(bundle)
    retryable = not isinstance(client, FixtureLLMClient)
    for attempt in range(2):
        card = client.complete_structured(
            system=ANALYST_SYSTEM_PROMPT,
            user=user_prompt,
            response_model=EvidenceCard,
        )
        # Enforce cap from ScorePacket (B4); ids are never model-authored.
        card = card.model_copy(
            update={
                "card_id": str(uuid.uuid4()),
                "max_confidence": bundle.score_packet.data_quality.max_confidence,
                "data_quality_status": bundle.score_packet.data_quality.status,
                "confidence": min(
                    card.confidence,
                    bundle.score_packet.data_quality.max_confidence,
                ),
                "source_packet_symbol": bundle.symbol,
                "source_packet_as_of": bundle.as_of,
                "spec_id": bundle.spec_id,
            }
        )
        try:
            validate_evidence_card(card, allowlist, bundle.evidence_ref_keys)
            break
        except CardValidationError as e:
            # One corrective retry with the validator error fed back (live only —
            # a fixture would just return the same canned object again).
            if attempt == 0 and retryable:
                user_prompt = build_analyst_user_prompt(bundle) + _validation_retry_note(e)
                continue
            raise
    write_evidence_card(card, cards_dir)
    if vault_mirror_path is not None:
        write_vault_mirror(card, vault_mirror_path)
    return card


def run_critique_spec(
    bundle: AnalystInputBundle,
    card: EvidenceCard | None = None,
    *,
    cards_dir: str | Path,
    llm_client: StructuredLLM | None = None,
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

    if isinstance(client, FixtureLLMClient) and CriticReview not in client._canned:
        raise RunnerError(
            "Happy-path critique-spec needs RESEARCH_DATA_LLM=live or a "
            "FixtureLLMClient preloaded with a CriticReview"
        )
    allowlist = build_allowlist_from_score_packet(bundle.score_packet)
    if bundle.gate_summary is not None:
        allowlist = merge_allowlists(
            allowlist, build_allowlist_from_gate_summary(bundle.gate_summary)
        )
    user_prompt = build_critic_user_prompt(bundle, card)
    retryable = not isinstance(client, FixtureLLMClient)
    for attempt in range(2):
        review = client.complete_structured(
            system=CRITIC_SYSTEM_PROMPT,
            user=user_prompt,
            response_model=CriticReview,
        )
        # Provenance fields come from the bundle, never from model output.
        update = {
            "review_id": str(uuid.uuid4()),
            "card_id": card.card_id if card else None,
            "spec_id": bundle.spec_id,
        }
        if bundle.gate_summary is not None:
            update["gate_summary"] = bundle.gate_summary.model_dump(mode="json")
        review = review.model_copy(update=update)
        try:
            validate_critic_review(review, allowlist)
            break
        except CardValidationError as e:
            if attempt == 0 and retryable:
                user_prompt = build_critic_user_prompt(bundle, card) + _validation_retry_note(e)
                continue
            raise
    write_critic_review(review, cards_dir)
    return review
