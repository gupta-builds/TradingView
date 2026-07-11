"""Evidence cards and critic reviews — schema, projection, validators, writers.

No LLM imports. Downstream agents consume these models; Python owns validation.
``store.py`` is reserved for DuckDB persistence (build #2 after live card stable).
"""

from research_data.cards.allowlist import (
    CONFIDENCE_DISPLAY_DECIMALS,
    FLOAT_DISPLAY_DECIMALS,
    NumericAllowlist,
    build_allowlist_from_score_packet,
    build_allowlist_from_gate_summary,
)
from research_data.cards.gate_projection import GateSummaryProjection, project_gate_batch
from research_data.cards.models import CriticReview, EvidenceCard
from research_data.cards.validators import (
    CardValidationError,
    validate_confidence_cap,
    validate_evidence_card,
    validate_no_banned_tokens,
    validate_numeric_allowlist,
)
from research_data.cards.writer import write_evidence_card

__all__ = [
    "CONFIDENCE_DISPLAY_DECIMALS",
    "FLOAT_DISPLAY_DECIMALS",
    "CardValidationError",
    "CriticReview",
    "EvidenceCard",
    "GateSummaryProjection",
    "NumericAllowlist",
    "build_allowlist_from_gate_summary",
    "build_allowlist_from_score_packet",
    "project_gate_batch",
    "validate_confidence_cap",
    "validate_evidence_card",
    "validate_no_banned_tokens",
    "validate_numeric_allowlist",
    "write_evidence_card",
]
