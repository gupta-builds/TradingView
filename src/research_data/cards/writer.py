"""Write EvidenceCard / CriticReview JSON under data/cards/."""

from __future__ import annotations

from pathlib import Path

from research_data.cards.allowlist import (
    CONFIDENCE_DISPLAY_DECIMALS,
    FLOAT_DISPLAY_DECIMALS,
)
from research_data.cards.models import CriticReview, EvidenceCard


def format_card_float(value: float, *, confidence: bool = False) -> str:
    """Canonical display format — must match allowlist rounding."""
    decimals = CONFIDENCE_DISPLAY_DECIMALS if confidence else FLOAT_DISPLAY_DECIMALS
    return f"{value:.{decimals}f}"


def write_evidence_card(
    card: EvidenceCard,
    cards_dir: str | Path,
) -> Path:
    """Write ``{symbol}_{as_of}_{card_id}.json``; return path."""
    root = Path(cards_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{card.symbol}_{card.as_of.isoformat()}_{card.card_id}.json"
    path.write_text(
        card.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return path


def write_critic_review(
    review: CriticReview,
    cards_dir: str | Path,
) -> Path:
    root = Path(cards_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"review_{review.review_id}.json"
    path.write_text(review.model_dump_json(indent=2), encoding="utf-8")
    return path


def card_to_vault_markdown(card: EvidenceCard) -> str:
    """One-way DB→vault mirror body (D4). Never authoritative."""
    lines = [
        f"# EvidenceCard — {card.symbol} ({card.as_of.isoformat()})",
        "",
        f"> Mirror export only. DuckDB / `data/cards/` JSON is SoT. card_id=`{card.card_id}`",
        "",
        f"- **action:** `{card.action.value}`",
        f"- **confidence:** {format_card_float(card.confidence, confidence=True)} "
        f"(cap {format_card_float(card.max_confidence, confidence=True)})",
        f"- **quality:** `{card.data_quality_status.value}`",
        f"- **schema_version:** {card.schema_version}",
        "",
        "## Summary",
        "",
        card.summary,
        "",
        "## Evidence",
        "",
    ]
    for ev in card.evidence:
        ref = f" (`{ev.ref_key}`)" if ev.ref_key else ""
        lines.append(f"- [{ev.source}]{ref} {ev.point}")
    if card.opposing_evidence:
        lines.extend(["", "## Opposing", ""])
        lines.extend(f"- {x}" for x in card.opposing_evidence)
    if card.risks:
        lines.extend(["", "## Risks", ""])
        lines.extend(f"- {x}" for x in card.risks)
    if card.invalidation:
        lines.extend(["", "## Invalidation", ""])
        lines.extend(f"- {x}" for x in card.invalidation)
    lines.append("")
    return "\n".join(lines)


def write_vault_mirror(card: EvidenceCard, vault_path: str | Path) -> Path:
    path = Path(vault_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(card_to_vault_markdown(card), encoding="utf-8")
    return path
