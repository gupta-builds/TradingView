"""Assemble analyst/critic input packets — no LLM (B1, E1 pre-guard).

ScorePacket supplies numbers; DataEvidencePacket contributes evidence_refs only
(do not serialize both quality blocks).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from research_data.brain.models import PromotionDecision, TestRunRecord
from research_data.cards.gate_projection import GateSummaryProjection, project_gate_batch
from research_data.evidence import build_evidence_packet
from research_data.factors.packets import ScorePacket
from research_data.models import (
    DataEvidencePacket,
    DataQualityReport,
    OHLCVRecord,
    QualityStatus,
)
from research_data.paper.models import JournalEntry


class AssembleError(Exception):
    """Raised when packets cannot be assembled."""


#: Quality statuses that must never reach the LLM (E1).
_BLOCK_LLM_STATUSES = frozenset(
    {QualityStatus.MISSING, QualityStatus.CONTRADICTORY}
)


@dataclass
class AnalystInputBundle:
    """What the analyst may see for one symbol."""

    symbol: str
    as_of: date
    score_packet: ScorePacket
    evidence_refs: list[dict[str, Any]]
    evidence_ref_keys: set[str] = field(default_factory=set)
    # Spec/critic path (optional)
    spec_id: str | None = None
    gate_summary: GateSummaryProjection | None = None
    promotion_decision: PromotionDecision | None = None
    journal_entries: list[JournalEntry] = field(default_factory=list)

    @property
    def blocks_llm(self) -> bool:
        return self.score_packet.data_quality.status in _BLOCK_LLM_STATUSES


def quality_blocks_llm(status: QualityStatus) -> bool:
    return status in _BLOCK_LLM_STATUSES


def _refs_from_evidence_packet(packet: DataEvidencePacket) -> tuple[list[dict], set[str]]:
    refs = []
    keys: set[str] = set()
    for ref in packet.evidence_refs:
        keys.add(ref.key)
        refs.append(
            {
                "table": ref.table,
                "key": ref.key,
                "source": ref.source,
                "retrieved_at": ref.retrieved_at.isoformat(),
                "data_as_of": ref.data_as_of.isoformat(),
            }
        )
    return refs, keys


def assemble_symbol_input(
    *,
    score_packet: ScorePacket,
    evidence_packet: DataEvidencePacket | None = None,
    records: list[OHLCVRecord] | None = None,
    quality_report: DataQualityReport | None = None,
    benchmark_symbol: str = "VOO",
    benchmark_available: bool = True,
    spec_id: str | None = None,
    gate_runs: list[TestRunRecord] | None = None,
    promotion_decision: PromotionDecision | None = None,
    journal_entries: list[JournalEntry] | None = None,
) -> AnalystInputBundle:
    """Build analyst input. Prefers an existing evidence packet for refs only."""
    if score_packet.symbol != (evidence_packet.symbol if evidence_packet else score_packet.symbol):
        if evidence_packet and evidence_packet.symbol != score_packet.symbol:
            raise AssembleError("ScorePacket and DataEvidencePacket symbol mismatch")

    if evidence_packet is not None:
        refs, keys = _refs_from_evidence_packet(evidence_packet)
    elif records is not None and quality_report is not None:
        built = build_evidence_packet(
            symbol=score_packet.symbol,
            records=records,
            quality_report=quality_report,
            benchmark_symbol=benchmark_symbol,
            benchmark_available=benchmark_available,
            as_of=score_packet.as_of,
        )
        refs, keys = _refs_from_evidence_packet(built)
    else:
        refs, keys = [], set()

    gate_summary = None
    if spec_id and gate_runs is not None:
        gate_summary = project_gate_batch(spec_id, gate_runs)

    return AnalystInputBundle(
        symbol=score_packet.symbol,
        as_of=score_packet.as_of,
        score_packet=score_packet,
        evidence_refs=refs,
        evidence_ref_keys=keys,
        spec_id=spec_id,
        gate_summary=gate_summary,
        promotion_decision=promotion_decision,
        journal_entries=list(journal_entries or []),
    )


def score_packet_to_analyst_dict(packet: ScorePacket) -> dict[str, Any]:
    """Serialize ScorePacket for the LLM — numbers live here only."""
    return packet.model_dump(mode="json")
